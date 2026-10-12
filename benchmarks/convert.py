"""Benchmark real conversion without writing video assets."""

import argparse
import bz2
import cProfile
import hashlib
import statistics
import time

import cv2

from sixel_video.converter import DeltaEncoder, SixelEncoder


def convert(frames, interval, mode, accelerator):
    encoder = SixelEncoder(None, 256)
    delta = DeltaEncoder(encoder, interval, mode, accelerator) if mode != 'full' else None
    compressor = bz2.BZ2Compressor(9)
    digest = hashlib.sha256()
    raw_bytes = compressed_bytes = 0
    encode_seconds = compress_seconds = 0
    try:
        for rgb in frames:
            started = time.perf_counter()
            encoded = (delta or encoder).encode(rgb)
            encode_seconds += time.perf_counter() - started
            raw_bytes += len(encoded)
            started = time.perf_counter()
            data = compressor.compress(encoded)
            compress_seconds += time.perf_counter() - started
            compressed_bytes += len(data)
            digest.update(data)
        started = time.perf_counter()
        data = compressor.flush()
        compress_seconds += time.perf_counter() - started
        compressed_bytes += len(data)
        digest.update(data)
        return dict(seconds=encode_seconds + compress_seconds, encode=encode_seconds,
                    compress=compress_seconds, raw=raw_bytes, compressed=compressed_bytes,
                    digest=digest.hexdigest(), backend=delta.accelerator if delta else 'none')
    finally:
        if delta:
            delta.close()
        encoder.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source')
    parser.add_argument('--frames', type=int, default=150)
    parser.add_argument('--repeat', type=int, default=3)
    parser.add_argument('--accelerator', choices=('auto', 'numpy', 'cython'), default='auto')
    parser.add_argument('--profile', help='Write a cProfile report to this path')
    args = parser.parse_args()
    if args.frames <= 0 or args.repeat <= 0:
        parser.error('--frames and --repeat must be positive')
    video = cv2.VideoCapture(args.source)
    if not video.isOpened():
        parser.error('Could not open source')
    interval = max(1, int(video.get(cv2.CAP_PROP_FPS)))
    frames = []
    started = time.perf_counter()
    try:
        for index in range(args.frames):
            ok, frame = video.read()
            if not ok:
                break
            frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    finally:
        video.release()
    if not frames:
        parser.error('No decoded frames')
    print('Decoded {} frames in {:.3f}s; encoding measurements reuse these RGB frames.'.format(len(frames), time.perf_counter() - started))
    for mode in ('full', 'raw', 'compressed'):
        results = [convert(frames, interval, mode, args.accelerator) for _ in range(args.repeat)]
        assert all(row['digest'] == results[0]['digest'] for row in results), 'Nondeterministic output'
        median = statistics.median(row['seconds'] for row in results)
        result = results[0]
        print('{} [{}]: {:.3f}s median ({:.1f} fps), encode {:.3f}s, final compression {:.3f}s, raw {:,}, bzip2 {:,}, sha256 {}'.format(
            mode, result['backend'], median, len(frames) / median,
            statistics.median(row['encode'] for row in results), statistics.median(row['compress'] for row in results),
            result['raw'], result['compressed'], result['digest']))
    if args.profile:
        profiler = cProfile.Profile()
        profiler.runcall(convert, frames, interval, 'raw', args.accelerator)
        profiler.dump_stats(args.profile)


if __name__ == '__main__':
    main()
