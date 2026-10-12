import bz2
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import cv2
import numpy as np

from sixel_video.kitty import KittyEncoder
from kitty_reference import commands, decode


class KittyTests(unittest.TestCase):
    def test_lossless_payloads_patches_erasure_edges_and_keyframes(self):
        rng = np.random.default_rng(59)
        original = rng.integers(0, 256, (17, 97, 3), dtype=np.uint8)
        changed = original.copy()
        changed[1, 2] = (255, 0, 0)
        changed[-1, -1] = (0, 255, 0)
        sources = [original, original, changed, original, changed]
        for fmt in ('rgb', 'png', 'auto'):
            for compression in ('none', 'zlib'):
                for region in ('sparse', 'rectangle', 'adaptive'):
                    with self.subTest(fmt=fmt, compression=compression, region=region):
                        encoder = KittyEncoder(25, delta=True, keyframe_frames=3, payload_format=fmt,
                                               compression=compression, region=region)
                        data = b''.join(encoder.encode(rgb) for rgb in sources) + encoder.finish()
                        frames, gaps, controls = decode(data)
                        self.assertEqual(len(frames), len(sources))
                        for actual, expected in zip(frames, sources):
                            np.testing.assert_array_equal(actual, expected)
                        self.assertEqual(gaps, [40] * len(sources))
                        self.assertEqual(controls[-1]['v'], '2')
                        self.assertGreater(encoder.delta_frames, 0)
                        self.assertGreaterEqual(encoder.keyframes, 2)
                        for header, _ in commands(data):
                            self.assertEqual(header.get('q'), '2')

    def test_threshold_bounds_cumulative_drift_in_true_color(self):
        sources = [np.full((12, 32, 3), n, np.uint8) for n in range(0, 80, 2)]
        for region in ('sparse', 'rectangle', 'adaptive'):
            encoder = KittyEncoder(25, delta=True, keyframe_frames=100, threshold=1, region=region)
            frames, _, _ = decode(b''.join(encoder.encode(rgb) for rgb in sources) + encoder.finish())
            for actual, expected in zip(frames, sources):
                self.assertLessEqual(np.abs(actual.astype(int) - expected.astype(int)).max(), 2)
            self.assertGreater(frames[-1].max(), 50)

    def test_deduplication_preserves_timing_and_keyframe_cadence(self):
        source = np.full((12, 32, 3), 80, np.uint8)
        encoder = KittyEncoder(29.97, delta=True, deduplicate=True, keyframe_frames=10, loops=0)
        data = b''.join(encoder.encode(source) for _ in range(31)) + encoder.finish()
        frames, gaps, controls = decode(data)
        self.assertEqual(len(frames), 4)
        self.assertEqual(sum(gaps), round(31 * 1000 / 29.97))
        self.assertTrue(all(0 < gap <= 334 for gap in gaps))
        self.assertEqual(controls[-1]['v'], '1')
        for frame in frames:
            np.testing.assert_array_equal(frame, source)

    def test_stream_mode_is_one_complete_static_image_per_line(self):
        rgb = np.arange(24 * 32 * 3, dtype=np.uint8).reshape(24, 32, 3)
        encoder = KittyEncoder(25, mode='stream')
        data = encoder.encode(rgb) + encoder.encode(rgb) + encoder.finish()
        self.assertEqual(len(data.splitlines()), 2)
        self.assertTrue(all(header['a'] == 'T' for header, _ in commands(data)))
        frames, _, _ = decode(data)
        for frame in frames:
            np.testing.assert_array_equal(frame, rgb)

    def test_cli_converts_mp4_without_loading_libsixel_and_outer_compression_is_optional(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'input.mp4'
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*'mp4v'), 25, (32, 24))
            self.assertTrue(writer.isOpened())
            for index in range(8):
                frame = np.zeros((24, 32, 3), np.uint8)
                frame[4:12, index:index + 8] = (25, 200, 80)
                writer.write(frame)
            writer.release()
            capture = cv2.VideoCapture(str(source))
            expected = []
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                expected.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            capture.release()
            outputs = []
            for compression in ('bzip2', 'none'):
                output = Path(directory) / ('output.' + compression)
                result = subprocess.run([sys.executable, '-B', '-m', 'sixel_video', str(source), str(output),
                                         '--format', 'kitty', '--delta', '--delta-region', 'adaptive',
                                         '--library', '/missing/libsixel.so', '--compression', compression,
                                         '--verbose', '--progress', 'text'], capture_output=True, check=True)
                self.assertIn(b'ETA', result.stderr)
                self.assertNotIn(b'\x1b', result.stderr)
                data = output.read_bytes()
                outputs.append(bz2.decompress(data) if compression == 'bzip2' else data)
                frames, gaps, _ = decode(outputs[-1])
                self.assertEqual(gaps, [40] * 8)
                for actual, reference in zip(frames, expected):
                    np.testing.assert_array_equal(actual, reference)
            self.assertEqual(*outputs)

    def test_invalid_kitty_combinations_do_not_create_output(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'output'
            cases = ((['--kitty-mode', 'stream', '--delta'], b'require animation mode'),
                     (['--palette', 'scene'], b'SIXEL-only'), (['--colors', '128'], b'SIXEL-only'),
                     (['--kitty-loops', '-1'], b'--kitty-loops 0..'),
                     (['--kitty-image-id', '0'], b'--kitty-image-id must'),
                     (['--kitty-deduplicate'], b'--kitty-deduplicate requires --delta'),
                     (['--accelerator', 'cython', '--delta'], b'Kitty uses NumPy'))
            for flags, message in cases:
                result = subprocess.run([sys.executable, '-B', '-m', 'sixel_video', 'missing.mp4', str(target),
                                         '--format', 'kitty', *flags], capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertFalse(target.exists())

    def test_compressed_selection_and_adaptive_regions_preserve_pixels(self):
        rng = np.random.default_rng(150)
        original = rng.integers(0, 256, (25, 81, 3), dtype=np.uint8)
        changed = original.copy()
        changed[2:5, 3:6] = (20, 50, 150)
        changed[21:24, 76:79] = (10, 70, 90)
        for optimize in ('raw', 'compressed'):
            costs = []
            for region in ('sparse', 'rectangle', 'adaptive'):
                encoder = KittyEncoder(25, delta=True, optimize=optimize, region=region)
                root, update = encoder.encode(original), encoder.encode(changed)
                frames, _, _ = decode(root + update)
                np.testing.assert_array_equal(frames[-1], changed)
                costs.append(len(bz2.compress(update)) if optimize == 'compressed' else len(update))
            self.assertLessEqual(costs[-1], min(costs[:2]))
