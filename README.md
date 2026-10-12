# sixel-video

Convert videos into bzip2-compressed sixel animations for graphics-capable
terminals. Conversion happens once; playback needs a decompressor and frame
pacing, with no video decoder or sixel encoder.

The converter supports full frames, exact delta updates, configurable keyframe
intervals, compression-aware frame selection, and conversion progress with an
ETA. On terminals that advertise sixel support, verbose progress uses a sixel
bar; other terminals and redirected logs receive text progress.

## Install

Install libsixel and Python 3.10 or newer. On Debian or Ubuntu:

```sh
sudo apt install libsixel1 python3-venv
python3 -m venv .venv
. .venv/bin/activate
python -m pip install git+https://github.com/CryptoDragonLady/sixel-video.git
```

On macOS, install libsixel with `brew install libsixel`. Windows Terminal can
display the output through WSL; install the converter and libsixel inside WSL.
Use `--library /path/to/libsixel.so` for a nonstandard library location.

## Convert

```sh
sixel-video input.mp4 output.sixel.bz2
sixel-video input.mp4 output.delta.sixel.bz2 --delta --verbose
sixel-video input.mp4 output.storage.sixel.bz2 --delta --delta-optimize compressed --verbose
```

The default mode encodes complete frames. `--delta` omits pixels whose displayed
colors are unchanged and inserts a full keyframe at least every second.
`--keyframe-interval 2` changes that maximum interval to two seconds. All modes
retain the input dimensions and frame count, using up to 256 colors per frame.
The encoder creates a fresh palette context each frame to avoid stale color
mappings when scenes change.

With `--delta-optimize raw`, the converter chooses between a delta and a full
frame by uncompressed sixel length. This is the default and targets the bytes
sent to the terminal. `--delta-optimize compressed` compares trial bzip2 sizes
instead, targeting the stored file size. Trial compression increases conversion
time. These frame costs are estimates: the final compressor also compresses
patterns across adjacent frames. Always compare the resulting files.

Both delta modes preserve exactly the displayed pixels of full-frame conversion;
color quantization itself is lossy. Full frames are used when a patch needs all
256 palette entries or reaches the keyframe interval.

`--colors 128` reduces the palette to save space at the cost of color fidelity.
`--colors 255` also guarantees room for the delta encoder's unpainted index.

## Additional optimizations

Each option is independent and defaults off. The output remains ordinary sixel
commands that the terminal renders directly; these options require no extra
playback decoder.

| Option | Behavior | Tradeoff |
| --- | --- | --- |
| `--palette scene` | Reuse a palette until the mean RGB difference from its source reaches `--scene-threshold` (default 35 of 255). | Reduces palette churn; colors introduced later may be represented less accurately until refresh. |
| `--denoise 0.5` | Smooth small fluctuations using the preceding filtered frame. Changes exceeding `--denoise-threshold` (default 12 of 255 per channel) pass through immediately. | Can soften fine detail; strength ranges from 0 to 1. |
| `--delta-threshold 1` | Skip repainting pixels within one sixel RGB percentage point per channel. | Adds bounded color error relative to full-frame output with the same palette and denoising settings. |
| `--delta-region adaptive` | Try sparse pixels and their filled bounding rectangle, keeping the cheaper candidate or a full frame. | More conversion work; repainting extra pixels can sometimes improve compression. |

`--delta-region sparse` is the default; `--delta-region rectangle` tries only the
rectangle and full frame. Region candidates use the selected `--delta-optimize`
cost. They retain the raster size and leave pixels outside the region unpainted.

Perceptual skipping always compares with the reconstructed image actually on
screen, so small source changes accumulate until repainting is necessary. Its
error bound applies to the quantized, optionally denoised reference, rather than
to the original source video. Scene palettes, denoising and color reduction have
their own quality costs. Full keyframes still refresh every pixel.

For an experimental combination:

```sh
sixel-video input.mp4 output.sixel.bz2 --delta --delta-optimize compressed \
  --palette scene --denoise 0.5 --delta-threshold 1 --delta-region adaptive --verbose
```

Compare each option separately on your content before combining them.

## Progress

```sh
sixel-video input.mp4 output.sixel.bz2 --delta --verbose
sixel-video input.mp4 output.sixel.bz2 --verbose --progress text
sixel-video input.mp4 output.sixel.bz2 --quiet
```

Verbose progress reports the frame count, percentage, ETA and frames per second
on stderr, then reports elapsed time and actual sixel and compressed byte counts.
`--progress auto` probes the terminal with a bounded Primary Device Attributes
query and selects sixel when feature 4 is advertised. `--progress sixel` requests
the same capability check; it falls back to text when support is unavailable.
`--progress text` skips the query. Redirected progress contains no escape codes.
`--quiet` suppresses progress and final statistics.

## Playback

Each decompressed line is one complete sixel update. Feed those updates to the
terminal at the source video's frame rate. For example, for a 25 fps video:

```sh
python - output.delta.sixel.bz2 <<'PY'
import bz2
import sys
import time

started = time.monotonic()
with bz2.open(sys.argv[1], 'rb') as video:
    for index, frame in enumerate(video):
        time.sleep(max(0, started + index / 25 - time.monotonic()))
        sys.stdout.buffer.write(frame.rstrip(b'\n'))
        sys.stdout.buffer.flush()
PY
```

Delta updates depend on previous frames. A player must retain those updates,
including late ones, or skip forward to a complete keyframe. Plain `bzcat`
decompresses incrementally but does not regulate playback speed. The existing
[rickrollrc player](https://github.com/CryptoDragonLady/rickrollrc) provides
capability detection, frame pacing and audio for its bundled assets.

For distribution limits, `--split-mib 64` splits the compressed byte stream and
writes a `.parts` manifest. Concatenating those pieces in manifest order exactly
recreates the single stream; ordinary conversion always produces one file.

## Development

```sh
python -m pip install -e .
python -B -m unittest discover -s tests -v
python benchmarks/convert.py input.mp4 --frames 150 --repeat 3
```

Tests use generated video fixtures and independently interpret sixel commands to
verify pixel reconstruction, palette changes, keyframe cadence and terminal
capability handling. GitHub Actions runs them on supported CPython versions.
The benchmark separates decoding, encoding and bzip2 costs and can also emit a
Python profile with `--profile /tmp/sixel-video.prof`.

The project began as the video converter in rickrollrc. No source videos or
generated animations are included.

## Optional Cython acceleration

The NumPy backend uses vectorized channel comparisons without an axis reduction.
An optional Cython backend performs those comparisons in a single native loop:

```sh
SIXEL_VIDEO_BUILD_CYTHON=1 python -m pip install --no-cache-dir --force-reinstall git+https://github.com/CryptoDragonLady/sixel-video.git
sixel-video input.mp4 output.sixel.bz2 --delta --accelerator cython --verbose
```

Building the extension requires a C compiler and Python development headers
(`sudo apt install build-essential python3-dev` on Debian or Ubuntu). Ordinary installs work without
one. `--accelerator auto` uses the extension when installed and otherwise uses
NumPy. `--accelerator numpy` forces the portable backend for comparisons. The
backends produce identical output bytes; the benchmark can measure their impact
on your source video. Most conversion work still happens in libsixel, OpenCV and
libbzip2, so speeding up pixel comparisons only speeds up part of the pipeline.

PyPy has not been validated for the complete converter. OpenCV and NumPy depend
on native extension compatibility, so its JIT is not an automatic speedup for
this workload. See [PyPy's extension guidance](https://doc.pypy.org/faq.html#do-c-extension-modules-work-with-pypy).
