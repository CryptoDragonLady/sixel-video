"""Compare converter options on identical frames and write a measured Markdown report.

Install the project first. Raw receipts belong outside the checkout:
python benchmarks/options.py video.mp4 --frames 500 --repeat 3 \
    --json-output /tmp/sixel-options.json --document docs/benchmarks/video.md
"""

import argparse
from collections import Counter
import bz2
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import statistics
import subprocess
import sys
import time
import zlib

os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('OMP_NUM_THREADS', '1')

import cv2
import numpy as np

from sixel_video import __version__
from sixel_video.converter import DeltaEncoder, SixelEncoder, TemporalDenoiser
from sixel_video.kitty import KittyEncoder

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from kitty_reference import commands
from sixel_reference import decode as decode_sixel


def configurations():
    rows = []

    def add(identifier, label, protocol, flags='', **options):
        if protocol == 'sixel' and options.get('delta') and '--accelerator' not in flags:
            flags += ' --accelerator ' + options.get('accelerator', 'numpy')
        rows.append(dict(id=identifier, label=label, protocol=protocol, flags=flags, options=options))

    def sixel(identifier, label, flags='', **options):
        add(identifier, label, 'sixel', flags, delta=True, **options)

    add('S00', 'Full frames, 256 colors', 'sixel')
    sixel('S01', 'Exact sparse deltas, NumPy', '--delta --accelerator numpy')
    sixel('S02', 'Compressed-cost sparse deltas', '--delta --delta-optimize compressed', optimize='compressed')
    sixel('S03', 'Rectangle deltas', '--delta --delta-region rectangle', region='rectangle')
    sixel('S04', 'Adaptive deltas', '--delta --delta-region adaptive', region='adaptive')
    sixel('S05', 'Adaptive, compressed cost', '--delta --delta-region adaptive --delta-optimize compressed',
          region='adaptive', optimize='compressed')
    sixel('S06', 'Exact sparse deltas, Cython', '--delta --accelerator cython', accelerator='cython')
    sixel('S07', '255-color deltas', '--delta --colors 255', colors=255)
    sixel('S08', '128-color deltas', '--delta --colors 128', colors=128)
    sixel('S09', '64-color deltas', '--delta --colors 64', colors=64)
    sixel('S10', 'Scene palette, threshold 35', '--delta --palette scene', palette='scene')
    sixel('S11', 'Scene palette, threshold 15', '--delta --palette scene --scene-threshold 15',
          palette='scene', scene_threshold=15)
    sixel('S12', 'Denoise 0.5', '--delta --denoise 0.5', denoise=0.5)
    sixel('S13', 'Color tolerance 1%', '--delta --delta-threshold 1', threshold=1)
    sixel('S14', 'Color tolerance 2%', '--delta --delta-threshold 2', threshold=2)
    sixel('S15', 'Keyframes within 0.5 s', '--delta --keyframe-interval 0.5', interval=0.5)
    sixel('S16', 'Keyframes within 2 s', '--delta --keyframe-interval 2', interval=2)
    sixel('S17', 'Keyframes within 5 s', '--delta --keyframe-interval 5', interval=5)
    sixel('S18', 'Combined lossy controls', '--delta --palette scene --denoise 0.5 --delta-threshold 1 '
          '--delta-region adaptive --delta-optimize compressed', palette='scene', denoise=0.5,
          threshold=1, region='adaptive', optimize='compressed')
    sixel('S19', 'Exact deltas, no outer bzip2', '--delta --compression none', outer='none')

    def kitty(identifier, label, flags='', **options):
        add(identifier, label, 'kitty', '--format kitty' + (' ' + flags if flags else ''), **options)

    kitty('K00', 'Full frames, auto payload')
    kitty('K01', 'Full RGB, zlib', '--kitty-format rgb', payload_format='rgb')
    kitty('K02', 'Full RGB, no zlib', '--kitty-format rgb --kitty-compression none',
          payload_format='rgb', compression='none')
    kitty('K03', 'Full PNG', '--kitty-format png', payload_format='png')
    kitty('K04', 'Full PNG, no outer bzip2', '--kitty-format png --compression none', payload_format='png', outer='none')
    kitty('K05', 'Auto payload, paced stream', '--kitty-mode stream', mode='stream')
    kitty('K06', 'Exact auto sparse deltas', '--delta', delta=True)
    kitty('K07', 'Auto rectangle deltas', '--delta --delta-region rectangle', delta=True, region='rectangle')
    kitty('K08', 'Auto adaptive deltas', '--delta --delta-region adaptive', delta=True, region='adaptive')
    kitty('K09', 'Auto adaptive, compressed cost', '--delta --delta-region adaptive --delta-optimize compressed',
          delta=True, region='adaptive', optimize='compressed')
    kitty('K10', 'Merge repeated frames', '--delta --kitty-deduplicate', delta=True, deduplicate=True)
    kitty('K11', 'RGB sparse deltas', '--delta --kitty-format rgb', delta=True, payload_format='rgb')
    kitty('K12', 'RGB rectangle deltas', '--delta --kitty-format rgb --delta-region rectangle',
          delta=True, payload_format='rgb', region='rectangle')
    kitty('K13', 'PNG sparse deltas', '--delta --kitty-format png', delta=True, payload_format='png')
    kitty('K14', 'Denoise 0.5', '--delta --denoise 0.5', delta=True, denoise=0.5)
    kitty('K15', 'Color tolerance 1%', '--delta --delta-threshold 1', delta=True, threshold=1)
    kitty('K16', 'Color tolerance 2%', '--delta --delta-threshold 2', delta=True, threshold=2)
    kitty('K17', 'Keyframes within 2 s', '--delta --keyframe-interval 2', delta=True, interval=2)
    kitty('K18', 'Combined lossy controls', '--delta --delta-region adaptive --delta-optimize compressed '
          '--denoise 0.5 --delta-threshold 1 --kitty-deduplicate', delta=True, region='adaptive',
          optimize='compressed', denoise=0.5, threshold=1, deduplicate=True)
    kitty('K19', 'Exact auto deltas, no outer bzip2', '--delta --compression none', delta=True, outer='none')
    return rows


class ObservedSixelEncoder(SixelEncoder):
    """Record the full reference and palette refreshes without altering encoding."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.palette_refreshes = 0
        self.full = None

    def encode(self, rgb):
        previous = self.palette_source
        self.full = super().encode(rgb)
        if self.palette_mode == 'frame' or self.palette_source is not previous:
            self.palette_refreshes += 1
        return self.full


def decode_kitty_update(data, canvas):
    for header, payload in commands(data):
        action = header.get('a', 't')
        if action not in ('t', 'T', 'f'):
            continue
        if header.get('o') == 'z':
            payload = zlib.decompress(payload)
        fmt = int(header['f'])
        if fmt == 100:
            pixels = cv2.imdecode(np.frombuffer(payload, np.uint8), cv2.IMREAD_UNCHANGED)
            order = [2, 1, 0, 3] if pixels.shape[2] == 4 else [2, 1, 0]
            pixels = pixels[:, :, order]
        else:
            pixels = np.frombuffer(payload, np.uint8).reshape(int(header['v']), int(header['s']), fmt // 8)
        if action in ('t', 'T') or 'c' not in header:
            canvas = np.zeros(pixels.shape[:2] + (3,), np.uint8)
        assert canvas is not None
        x, y = int(header.get('x', 0)), int(header.get('y', 0))
        h, w = pixels.shape[:2]
        assert x + w <= canvas.shape[1] and y + h <= canvas.shape[0]
        patch = canvas[y:y + h, x:x + w]
        if pixels.shape[2] == 4 and header.get('X', '0') == '0':
            assert np.isin(pixels[:, :, 3], (0, 255)).all()
            painted = pixels[:, :, 3] == 255
            patch[painted] = pixels[:, :, :3][painted]
        else:
            patch[:] = pixels[:, :, :3]
    return canvas


def run(frames, fps, config, sample_indices=()):
    options = config['options']
    sixel = config['protocol'] == 'sixel'
    interval = max(1, math.floor(fps * options.get('interval', 1)))
    threshold = options.get('threshold', 0)
    denoiser = TemporalDenoiser(options.get('denoise', 0))
    if sixel:
        encoder = ObservedSixelEncoder(None, options.get('colors', 256), options.get('palette', 'frame'),
                                       options.get('scene_threshold', 35))
        delta = DeltaEncoder(encoder, interval, options.get('optimize', 'raw'), options.get('accelerator', 'numpy'),
                             threshold, options.get('region', 'sparse')) if options.get('delta') else None
    else:
        accepted = {key: value for key, value in options.items() if key not in ('outer', 'interval', 'denoise')}
        encoder = KittyEncoder(fps, keyframe_frames=interval, **accepted)
        delta = None
    target = delta or encoder
    compressor = bz2.BZ2Compressor(9) if options.get('outer', 'bzip2') == 'bzip2' else None
    digest = hashlib.sha256()
    raw = stored = 0
    encode_seconds = compress_seconds = 0
    window = []
    payloads = Counter()
    absolute = squared = samples = maximum = 0
    full_frames = delta_frames = 0
    try:
        for index, source in enumerate(frames):
            before = getattr(target, 'keyframes', index)
            started = time.perf_counter()
            rgb = denoiser.process(source)
            data = target.encode(rgb)
            encode_seconds += time.perf_counter() - started
            raw += len(data)
            started = time.perf_counter()
            compressed = compressor.compress(data) if compressor else data
            compress_seconds += time.perf_counter() - started
            stored += len(compressed)
            digest.update(compressed)
            is_full = not options.get('delta') or target.keyframes > before
            full_frames += int(is_full)
            delta_frames += int(not is_full)
            if sample_indices:
                if is_full:
                    window = []
                window.append(data)
                if not sixel:
                    for control in re.findall(rb'\x1b_G([^;]*);', data):
                        match = re.search(rb'(?:^|,)f=(\d+)(?:,|$)', control)
                        if match:
                            payloads[int(match[1])] += 1
                if index in sample_indices:
                    canvas = None
                    for update in window:
                        canvas = decode_sixel(update, canvas)[0] if sixel else decode_kitty_update(update, canvas)
                    if sixel:
                        reference = decode_sixel(encoder.full)[0]
                        assert np.abs(canvas.astype(int) - reference.astype(int)).max() <= threshold
                        displayed = np.floor(canvas.astype(np.float32) * 2.55 + 0.5).astype(np.uint8)
                    else:
                        assert np.abs(canvas.astype(int) - rgb.astype(int)).max() <= math.floor(threshold * 255 / 100)
                        displayed = canvas
                    error = displayed.astype(np.float32) - source.astype(np.float32)
                    absolute += float(np.abs(error).sum(dtype=np.float64))
                    squared += float(np.square(error).sum(dtype=np.float64))
                    maximum = max(maximum, int(np.abs(error).max()))
                    samples += error.size
        if not sixel:
            started = time.perf_counter()
            ending = encoder.finish()
            encode_seconds += time.perf_counter() - started
            raw += len(ending)
            started = time.perf_counter()
            compressed = compressor.compress(ending) if compressor else ending
            compress_seconds += time.perf_counter() - started
            stored += len(compressed)
            digest.update(compressed)
        started = time.perf_counter()
        ending = compressor.flush() if compressor else b''
        compress_seconds += time.perf_counter() - started
        stored += len(ending)
        digest.update(ending)
        mse = squared / samples if samples else 0
        return dict(raw_bytes=raw, stored_bytes=stored, sha256=digest.hexdigest(),
                    encode_seconds=encode_seconds, compress_seconds=compress_seconds,
                    seconds=encode_seconds + compress_seconds, full_frames=full_frames, delta_frames=delta_frames,
                    merged_frames=getattr(encoder, 'repeated_frames', 0),
                    stored_frames=getattr(encoder, 'stored_frames', len(frames)),
                    palette_refreshes=getattr(encoder, 'palette_refreshes', None),
                    payloads={str(key): value for key, value in payloads.items()},
                    mae=absolute / samples if samples else None,
                    psnr_db=10 * math.log10(255 ** 2 / mse) if mse else None, max_error=maximum)
    finally:
        if delta:
            delta.close()
        encoder.close()


def aggregate(runs):
    stable = ('raw_bytes', 'stored_bytes', 'sha256', 'full_frames', 'delta_frames', 'merged_frames', 'stored_frames')
    assert all(all(row[key] == runs[0][key] for key in stable) for row in runs), 'Nondeterministic output'
    result = {key: value for key, value in runs[0].items() if key not in ('seconds', 'encode_seconds', 'compress_seconds')}
    for field in ('seconds', 'encode_seconds', 'compress_seconds'):
        result[field] = statistics.median(row[field] for row in runs)
    result['seconds_min'] = min(row['seconds'] for row in runs)
    result['seconds_max'] = max(row['seconds'] for row in runs)
    result['runs'] = [{key: row[key] for key in ('seconds', 'encode_seconds', 'compress_seconds')} for row in runs]
    return result


def package_versions():
    try:
        return subprocess.check_output(['dpkg-query', '-W', '-f=${Package} ${Version}\n', 'libsixel1', 'libbz2-1.0'],
                                       text=True, stderr=subprocess.DEVNULL).strip().splitlines()
    except (OSError, subprocess.CalledProcessError):
        return []


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def frames_sha256(frames):
    digest = hashlib.sha256()
    for frame in frames:
        digest.update(frame)
    return digest.hexdigest()


def write_document(path, metadata, rows):
    lines = ['# {}-frame {}p Astley benchmark'.format(metadata['frames'], metadata['height']), '',
             'Measured on {}. The tables compare actual emitted bytes and measured conversion work.'.format(metadata['date']), '',
             '## Dataset and method', '',
             '- Source: `{}`; SHA-256 `{}`.'.format(metadata['source_name'], metadata['source_sha256']),
             '- Frames 0–{}, {}×{}, {:g} fps: {:g} seconds of video, decoded directly without resizing or an intermediate video transcode.'.format(
                 metadata['frames'] - 1, metadata['width'], metadata['height'], metadata['fps'], metadata['frames'] / metadata['fps']),
             '- sixel-video {}; converter commit `{}`.'.format(metadata['version'], metadata['commit']),
             '- {} sequential repetitions per configuration, after a {}-frame warm-up; tables report medians and observed ranges.'.format(metadata['repeat'], min(3, metadata['frames'])),
             '- Decoding, RGB conversion and frame hashing took {:.3f} seconds, once, before reusing the cached frames. Timings include denoising, encoding, candidate selection, and outer compression; exclude source decoding, filesystem writes, and reconstruction checks.'.format(metadata['decode_seconds']),
             '- Host: {} {}; {} reported CPUs, `{}`. Python {}, NumPy {}, OpenCV {}. OpenCV/FFmpeg decoding use one thread; other host activity is uncontrolled.'.format(
                 metadata['system'], metadata['machine'], metadata['cpus'], metadata['cpu_model'], metadata['python'], metadata['numpy'], metadata['opencv']),
             '- System compression/graphics packages: {}.'.format('; '.join('`' + value + '`' for value in metadata['packages']) or 'not reported'),
             '- Stored bytes use one continuous bzip2 level-9 stream, including its final flush, except rows explicitly using `--compression none`. Generated animations are not saved.',
             '- Default keyframe interval is one second; SIXEL uses 256 colors and NumPy unless noted; Kitty uses native animation, auto payload selection, and zlib on RGB/RGBA unless noted.',
             '- Output counts and SHA-256 must agree across repetitions. Independent interpreters reconstruct sample frames {} from their preceding full keyframe and verify delta error bounds.'.format(', '.join(map(str, metadata['sample_indices']))),
             '- The cached RGB frame hash is checked after each configuration to verify that every run used the same source pixels.',
             '- MAE, PSNR and maximum error compare those decoded samples with the source RGB. SIXEL percentages are mapped to 8-bit RGB with nearest rounding; terminal-specific rounding can differ by one channel value. Quality figures are sampled, not whole-clip measurements.',
             '', '## How to read the results', '',
             '“Wire” is the full emitted protocol stream after outer decompression; it still contains Kitty’s native zlib/PNG payload compression and base64. “Stored” is the saved file size. MiB is 1,048,576 bytes.', '',
             'Wire counts include the framing newline in SIXEL and Kitty stream mode. Paced players normally remove that one byte per update before sending it to the terminal; native Kitty animation has no framing newlines.', '',
             'SIXEL exact deltas preserve the corresponding quantized full-frame output. Kitty preserves decoded RGB exactly when denoising and color tolerance are disabled. These formats retain different color information, so their sizes are not an equal-quality codec comparison.', '',
             'A positive size reduction means smaller than the protocol’s default full-frame baseline. Full/Delta counts refer to source updates; Kitty merges can reduce the stored animation frame count. MAE is mean absolute per-channel error; PSNR is `10 log10(255² / MSE)`. Infinite PSNR means zero sampled RGB error.', '']
    lines += ['This matrix focuses on settings that affect image encoding, compression, or frame structure. Verbosity/progress control status output; image IDs and loop counts control playback metadata. Splitting partitions the same byte stream rather than changing compression.', '']
    by_id = {row['id']: row for row in rows}
    for protocol, baseline_id in (('sixel', 'S00'), ('kitty', 'K00')):
        selected = [row for row in rows if row['protocol'] == protocol]
        if not selected:
            continue
        baseline = by_id.get(baseline_id)
        lines += ['## ' + ('SIXEL' if protocol == 'sixel' else 'Kitty'), '',
                  '### Output sizes', '',
                  '| ID | Configuration | Wire bytes | Stored bytes | Stored MiB | Reduction vs full |',
                  '| --- | --- | ---: | ---: | ---: | ---: |']
        for row in selected:
            reduction = '{:.2f}%'.format(100 * (1 - row['stored_bytes'] / baseline['stored_bytes'])) if baseline else '—'
            lines.append('| {} | {} | {:,} | {:,} | {:.3f} | {} |'.format(
                row['id'], row['label'], row['raw_bytes'], row['stored_bytes'], row['stored_bytes'] / 1048576, reduction))
        lines += ['', '### Conversion time', '',
                  '| ID | Encode s | Outer compression/pass-through s | Total median s | Total range s | Conversion fps |',
                  '| --- | ---: | ---: | ---: | ---: | ---: |']
        for row in selected:
            lines.append('| {} | {:.3f} | {:.3f} | {:.3f} | {:.3f}–{:.3f} | {:.2f} |'.format(
                row['id'], row['encode_seconds'], row['compress_seconds'], row['seconds'],
                row['seconds_min'], row['seconds_max'], metadata['frames'] / row['seconds']))
        lines += ['', '### Frame structure and sampled fidelity', '',
                  '| ID | Full / delta updates | ' + ('Palette refreshes' if protocol == 'sixel' else 'Stored / merged frames; PNG / RGB / RGBA payloads') + ' | RGB MAE | PSNR dB | Maximum RGB error |',
                  '| --- | ---: | --- | ---: | ---: | ---: |']
        for row in selected:
            detail = str(row['palette_refreshes']) if protocol == 'sixel' else '{} / {}; {} / {} / {}'.format(
                row['stored_frames'], row['merged_frames'], row['payloads'].get('100', 0), row['payloads'].get('24', 0), row['payloads'].get('32', 0))
            lines.append('| {} | {} / {} | {} | {:.3f} | {} | {} |'.format(
                row['id'], row['full_frames'], row['delta_frames'], detail, row['mae'],
                '{:.2f}'.format(row['psnr_db']) if row['psnr_db'] is not None else '∞', row['max_error']))
        lines += ['']
    lines += ['## Findings from this sample', '']
    for protocol, baseline_id, delta_id in (('SIXEL', 'S00', 'S01'), ('Kitty', 'K00', 'K06')):
        baseline, delta = by_id.get(baseline_id), by_id.get(delta_id)
        if baseline and delta:
            lines.append('- {} default exact deltas changed wire bytes by {:+.2f}% and stored bytes by {:+.2f}% versus full frames.'.format(
                protocol, 100 * (delta['raw_bytes'] / baseline['raw_bytes'] - 1),
                100 * (delta['stored_bytes'] / baseline['stored_bytes'] - 1)))
        candidates = [row for row in rows if row['protocol'] == protocol.lower()]
        if candidates:
            smallest = min(candidates, key=lambda row: row['stored_bytes'])
            lines.append('- Smallest measured {} result: {} ({:.3f} MiB; sampled MAE {:.3f}). Read its settings and quality costs before choosing it.'.format(
                protocol, smallest['id'], smallest['stored_bytes'] / 1048576, smallest['mae']))
    if 'S01' in by_id and 'S06' in by_id:
        a, b = by_id['S01'], by_id['S06']
        assert a['sha256'] == b['sha256'], 'NumPy/Cython output differs'
        lines.append('- NumPy and Cython produced identical bytes. Cython changed total median conversion time by {:+.2f}% on this sample.'.format(100 * (b['seconds'] / a['seconds'] - 1)))
    exact = [row for row in rows if row['protocol'] == 'kitty' and not row['options'].get('denoise') and not row['options'].get('threshold')]
    if exact:
        smallest = min(exact, key=lambda row: row['stored_bytes'])
        assert all(row['max_error'] == 0 for row in exact), 'Lossless Kitty sample differs from source'
        lines.append('- Smallest sampled-exact Kitty result: {} ({:.3f} MiB); all Kitty rows without denoising/tolerance reconstructed the sampled RGB exactly.'.format(smallest['id'], smallest['stored_bytes'] / 1048576))
    if 'K10' in by_id:
        lines.append('- Kitty deduplication merged {} source updates in K10; its benefit depends on genuinely repeated or tolerance-equivalent frames.'.format(by_id['K10']['merged_frames']))
    lines += ['', 'The selected opening segment does not represent every scene in the complete video. Timings describe this host and exclude playback; converter fps does not prove terminal rendering throughput. Native Kitty animation loads frames before playing, while SIXEL and Kitty stream output need a pacing process.', '',
              '## Exact option sets', '', 'All options are relative to the converter defaults, except SIXEL comparison uses NumPy explicitly unless the Cython row is selected. Denoising uses the default threshold of 12/255. PNG retains built-in compression even when Kitty RGB compression is disabled.', '',
              '| ID | Converter options |', '| --- | --- |']
    for row in rows:
        lines.append('| {} | `{}` |'.format(row['id'], row['flags'] or '(defaults)'))
    lines += ['', '## Reproduce', '',
              'Use the same source SHA-256, converter revision, library versions, and optional Cython extension. No source video or generated animation is bundled.', '', '```sh',
              'python benchmarks/options.py {} --frames {} --repeat {} \\'.format(metadata['source_name'], metadata['frames'], metadata['repeat']),
              '  --json-output /tmp/astley-720p-results.json \\',
              '  --document docs/benchmarks/astley-720p.md', '```', '',
              '`--only S01,S06` selects configurations by ID. `--resume` reuses completed configurations from the JSON receipt after checking the dataset, code, options, and repetition count. Resume timing results can span different host loads.', '',
              'See [conversion options](../../README.md) and [Kitty optimization notes](../kitty.md) for playback and quality tradeoffs.', '']
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--frames', type=int, default=500)
    parser.add_argument('--repeat', type=int, default=3)
    parser.add_argument('--only', help='Comma-separated configuration IDs')
    parser.add_argument('--json-output', type=Path, help='Raw receipt/checkpoint path; use a path outside the checkout')
    parser.add_argument('--document', type=Path, help='Write the complete Markdown benchmark report after all selected runs pass')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    if args.frames <= 0 or args.repeat <= 0:
        parser.error('--frames and --repeat must be positive')
    if args.resume and not args.json_output:
        parser.error('--resume requires --json-output')
    for target in (args.json_output, args.document):
        if target and target.resolve() == args.source.resolve():
            parser.error('Output paths must differ from the source')
    rows = configurations()
    if args.only:
        ids = set(args.only.split(','))
        if ids - {row['id'] for row in rows}:
            parser.error('Unknown configuration IDs')
        rows = [row for row in rows if row['id'] in ids]
    if any(row['options'].get('accelerator') == 'cython' for row in rows):
        try:
            import sixel_video._delta
        except ImportError:
            parser.error('This matrix includes Cython; build with SIXEL_VIDEO_BUILD_CYTHON=1 or omit S06')
    cv2.setNumThreads(1)
    capture = cv2.VideoCapture(str(args.source), cv2.CAP_FFMPEG, [cv2.CAP_PROP_N_THREADS, 1])
    if not capture.isOpened():
        parser.error('Could not open source video')
    fps = capture.get(cv2.CAP_PROP_FPS)
    if not math.isfinite(fps) or fps <= 0:
        parser.error('Source must report a positive frame rate')
    frames = []
    frame_hash = hashlib.sha256()
    started = time.perf_counter()
    try:
        for _ in range(args.frames):
            ok, frame = capture.read()
            if not ok:
                break
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame_hash.update(rgb)
            frames.append(rgb)
    finally:
        capture.release()
    decode_seconds = time.perf_counter() - started
    if len(frames) != args.frames:
        parser.error('Decoded {} frames, requested {}'.format(len(frames), args.frames))
    try:
        cpu = subprocess.check_output(['lscpu', '-J'], text=True)
        cpu_model = next(item['data'] for item in json.loads(cpu)['lscpu'] if item['field'] == 'Model name:')
    except (OSError, subprocess.CalledProcessError, StopIteration, ValueError):
        cpu_model = platform.processor() or 'unknown'
    sample_indices = sorted(set([0, len(frames) - 1] + list(range(99, len(frames), 100))))
    import sixel_video.converter as converter
    import sixel_video.kitty as kitty_module

    for module, name in ((converter, 'converter.py'), (kitty_module, 'kitty.py')):
        if Path(module.__file__).read_bytes() != (ROOT / 'src/sixel_video' / name).read_bytes():
            parser.error('Installed converter differs from this checkout; install the current source first')
    metadata = dict(date=datetime.now(timezone.utc).date().isoformat(), source_name=args.source.name,
                    source_sha256=file_sha256(args.source),
                    frame_rgb_sha256=frame_hash.hexdigest(), frames=len(frames), width=frames[0].shape[1], height=frames[0].shape[0],
                    fps=fps, repeat=args.repeat, decode_seconds=decode_seconds, sample_indices=sample_indices,
                    version=__version__, commit=subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip(),
                    converter_sha256=hashlib.sha256(Path(converter.__file__).read_bytes()).hexdigest(),
                    kitty_sha256=hashlib.sha256(Path(kitty_module.__file__).read_bytes()).hexdigest(),
                    benchmark_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    system=platform.system(), machine=platform.machine(), cpu_model=cpu_model, cpus=os.cpu_count(),
                    python=platform.python_version(), numpy=np.__version__, opencv=cv2.__version__, packages=package_versions())
    results = []
    if args.resume and args.json_output.exists():
        checkpoint = json.loads(args.json_output.read_text())
        for key in ('source_sha256', 'frame_rgb_sha256', 'frames', 'repeat', 'converter_sha256', 'kitty_sha256',
                    'benchmark_sha256', 'python', 'numpy', 'opencv', 'packages'):
            if checkpoint['metadata'][key] != metadata[key]:
                parser.error('Checkpoint differs: ' + key)
        if checkpoint['configurations'] != rows:
            parser.error('Checkpoint configurations differ')
        results = checkpoint['results']
    done = {row['id'] for row in results}
    print('Decoded {} {}x{} frames at {:g} fps; {} configurations, {} repetitions each'.format(
        len(frames), metadata['width'], metadata['height'], fps, len(rows), args.repeat), flush=True)
    for index, config in enumerate(rows):
        if config['id'] in done:
            continue
        print('[{}/{}] {} {}'.format(index + 1, len(rows), config['id'], config['label']), flush=True)
        run(frames[:3], fps, config)
        attempts = []
        for repetition in range(args.repeat):
            print('  repetition {}/{}'.format(repetition + 1, args.repeat), flush=True)
            attempts.append(run(frames, fps, config, sample_indices if repetition == 0 else ()))
        assert frames_sha256(frames) == metadata['frame_rgb_sha256'], 'An encoder modified the cached source RGB'
        result = dict(config, **aggregate(attempts))
        results.append(result)
        print('  wire {:,}; stored {:,}; median {:.3f}s; sampled MAE {:.3f}'.format(
            result['raw_bytes'], result['stored_bytes'], result['seconds'], result['mae']), flush=True)
        if args.json_output:
            args.json_output.parent.mkdir(parents=True, exist_ok=True)
            checkpoint = args.json_output.with_name(args.json_output.name + '.tmp')
            checkpoint.write_text(json.dumps(dict(metadata=metadata, configurations=rows, results=results), indent=2,
                                            allow_nan=False) + '\n')
            checkpoint.replace(args.json_output)
    if args.document:
        write_document(args.document, metadata, results)
        print('Wrote ' + str(args.document), flush=True)


if __name__ == '__main__':
    main()
