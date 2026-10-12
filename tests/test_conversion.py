import bz2
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import cv2
import numpy as np

from sixel_video.converter import DeltaEncoder, SixelEncoder, SplitOutput, TemporalDenoiser
from sixel_reference import decode


class ConversionTests(unittest.TestCase):
    def test_delta_reconstructs_erasure_palette_changes_and_edges(self):
        rng = np.random.default_rng(100)
        background = np.repeat(rng.integers(0, 3, (13, 300, 1), dtype=np.uint8) * 100, 3, axis=2)
        moving = background.copy()
        moving[7:11, 257:265] = (255, 0, 0)
        changed_palette = background.copy()
        changed_palette[0, 0] = (0, 255, 0)
        changed_palette[-1, -1] = (0, 0, 255)
        frames = [background, background, moving, background, changed_palette]
        frames += [changed_palette] * 7
        for optimize in ('raw', 'compressed'):
            for colors in (2, 16, 256):
                with self.subTest(optimize=optimize, colors=colors):
                    encoder = SixelEncoder(None, colors)
                    reference = SixelEncoder(None, colors)
                    delta = DeltaEncoder(encoder, 3, optimize)
                    canvas = None
                    last_full = 0
                    try:
                        for index, rgb in enumerate(frames):
                            full = reference.encode(rgb)
                            expected, coverage = decode(full)
                            self.assertTrue(coverage.all())
                            output = delta.encode(rgb)
                            canvas, painted = decode(output, canvas)
                            np.testing.assert_array_equal(canvas, expected)
                            if painted.all():
                                last_full = index
                            self.assertLess(index - last_full, 3)
                            if index == 1:
                                self.assertFalse(painted.any())
                            if optimize == 'compressed':
                                self.assertLessEqual(len(bz2.compress(output)), len(bz2.compress(delta.transparent(full))))
                    finally:
                        delta.close()
                        encoder.close()
                        reference.close()

    def test_comparison_backends_match_independent_rgb_reference(self):
        rng = np.random.default_rng(64)
        for shape in ((0, 5, 3), (13, 300, 3), (144, 256, 3)):
            current = rng.integers(0, 101, shape, dtype=np.uint8)
            previous = current.copy()
            previous[::2, ::3] = 0
            for threshold in (0, 1, 7, 100):
                expected = np.any(np.abs(current.astype(np.int16) - previous.astype(np.int16)) > threshold, axis=2)
                np.testing.assert_array_equal(DeltaEncoder.changed_pixels(current, previous, threshold), expected)
                try:
                    from sixel_video._delta import changed_mask
                except ImportError:
                    self.assertNotEqual(os.environ.get('SIXEL_VIDEO_BUILD_CYTHON'), '1', 'Required Cython backend was not built')
                    continue
                np.testing.assert_array_equal(changed_mask(current, previous, threshold), expected)
                with self.assertRaises(ValueError):
                    changed_mask(current, np.zeros((2, 2, 3), dtype=np.uint8))

    def test_accelerators_produce_identical_compressed_streams(self):
        try:
            from sixel_video._delta import changed_mask
        except ImportError:
            self.skipTest('Optional Cython extension not installed')
        rng = np.random.default_rng(432)
        background = rng.integers(0, 101, (23, 37, 3), dtype=np.uint8)
        frames = [background.copy() for _ in range(7)]
        frames[2][7:14, 11:18] = 255
        for optimize in ('raw', 'compressed'):
            streams = []
            for accelerator in ('numpy', 'cython'):
                encoder = SixelEncoder(None, 128)
                delta = DeltaEncoder(encoder, 3, optimize, accelerator)
                try:
                    streams.append(bz2.compress(b''.join(delta.encode(frame) for frame in frames)))
                    self.assertEqual(delta.accelerator, accelerator)
                finally:
                    delta.close()
                    encoder.close()
            self.assertEqual(*streams)

    def test_lossy_skipping_bounds_error_against_displayed_pixels(self):
        # Each step changes by less than the tolerance, but cumulative change
        # must eventually repaint. Comparing adjacent sources would freeze it.
        frames = [np.full((13, 40, 3), value, dtype=np.uint8) for value in range(0, 50, 2)]
        for region in ('sparse', 'rectangle', 'adaptive'):
            encoder = SixelEncoder(None, 16)
            reference = SixelEncoder(None, 16)
            delta = DeltaEncoder(encoder, 100, threshold=2, region=region)
            canvas = None
            try:
                for source in frames:
                    expected, _ = decode(reference.encode(source))
                    canvas, _ = decode(delta.encode(source), canvas)
                    error = np.abs(canvas.astype(np.int16) - expected.astype(np.int16))
                    self.assertLessEqual(error.max(), 2)
                self.assertGreater(canvas.max(), 10)
            finally:
                delta.close()
                encoder.close()
                reference.close()

    def test_adaptive_regions_preserve_sparse_and_filled_rectangle_pixels(self):
        rng = np.random.default_rng(20)
        original = rng.integers(0, 3, (13, 300, 1), dtype=np.uint8) * 100
        original = np.repeat(original, 3, axis=2)
        changed = original.copy()
        changed[1, 3] = (255, 0, 0)
        changed[-1, -1] = (0, 0, 255)
        for mode in ('raw', 'compressed'):
            costs = {}
            for region in ('sparse', 'rectangle', 'adaptive'):
                encoder = SixelEncoder(None, 16)
                reference = SixelEncoder(None, 16)
                delta = DeltaEncoder(encoder, 25, mode, region=region)
                canvas = None
                try:
                    for source in (original, changed, original):
                        expected, _ = decode(reference.encode(source))
                        output = delta.encode(source)
                        canvas, _ = decode(output, canvas)
                        np.testing.assert_array_equal(canvas, expected)
                    costs[region] = len(bz2.compress(output)) if mode == 'compressed' else len(output)
                finally:
                    delta.close()
                    encoder.close()
                    reference.close()
            self.assertLessEqual(costs['adaptive'], min(costs['sparse'], costs['rectangle']))

    def test_scene_palette_stability_refresh_and_single_color(self):
        encoder = SixelEncoder(None, 16, palette_mode='scene', scene_threshold=20)
        try:
            first = np.full((13, 40, 3), (10, 20, 30), dtype=np.uint8)
            shifted = first.copy()
            shifted[:, :, 0] += 1
            a, _ = decode(encoder.encode(first))
            b, _ = decode(encoder.encode(shifted))
            np.testing.assert_array_equal(a, b)
            new_scene = np.full_like(first, (200, 180, 20))
            actual, _ = decode(encoder.encode(new_scene))
            reference = SixelEncoder(None, 16)
            try:
                expected, _ = decode(reference.encode(new_scene))
                np.testing.assert_array_equal(actual, expected)
            finally:
                reference.close()
            again, _ = decode(encoder.encode(new_scene))
            np.testing.assert_array_equal(actual, again)
        finally:
            encoder.close()

    def test_denoising_reduces_noise_and_keeps_large_changes(self):
        original = np.full((12, 32, 3), 100, dtype=np.uint8)
        noisy = original + 6
        denoiser = TemporalDenoiser(0.5, 12)
        np.testing.assert_array_equal(denoiser.process(original), original)
        np.testing.assert_array_equal(denoiser.process(noisy), np.full_like(original, 103))
        cut = np.full_like(original, 200)
        np.testing.assert_array_equal(denoiser.process(cut), cut)
        np.testing.assert_array_equal(TemporalDenoiser(0).process(noisy), noisy)

    def test_split_stream_reassembles_exact_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'animation.bz2'
            output = SplitOutput(path, 10)
            output.write(b'a' * 17)
            output.write(b'b' * 15)
            output.close()
            names = output.manifest().read_text().splitlines()
            parts = [Path(directory) / name for name in names]
            self.assertTrue(all(part.stat().st_size <= 10 for part in parts))
            self.assertEqual(b''.join(part.read_bytes() for part in parts), b'a' * 17 + b'b' * 15)

    def test_cli_progress_and_quiet_do_not_change_video(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.mp4'
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*'mp4v'), 10, (32, 24))
            self.assertTrue(writer.isOpened())
            for index in range(8):
                frame = np.zeros((24, 32, 3), dtype=np.uint8)
                frame[4:12, index:index + 8] = (25, 200, 80)
                writer.write(frame)
            writer.release()
            results = []
            for flags in ([], ['--quiet'], ['--verbose', '--progress', 'text'], ['--verbose', '--progress', 'sixel']):
                output = Path(directory) / ('out{}.bz2'.format(len(results)))
                result = subprocess.run([sys.executable, '-B', '-m', 'sixel_video', str(source), str(output), '--delta', *flags],
                                        capture_output=True, check=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
                results.append(output.read_bytes())
                if '--quiet' in flags:
                    self.assertEqual(result.stdout + result.stderr, b'')
                if '--verbose' in flags:
                    self.assertIn(b'ETA', result.stderr)
                    self.assertIn(b'100.0%', result.stderr)
                    self.assertNotIn(b'\x1b', result.stderr)
                    self.assertIn(b'bzip2:', result.stdout)
            self.assertTrue(all(result == results[0] for result in results))
            self.assertEqual(len(bz2.decompress(results[0]).splitlines()), 8)

    def test_invalid_options_do_not_create_output(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'output.bz2'
            for flags in (['--delta-optimize', 'compressed'], ['--delta', '--keyframe-interval', 'nan'],
                          ['--delta', '--keyframe-interval', '0'], ['--verbose', '--quiet'],
                          ['--denoise', 'nan'], ['--denoise', '1.1'], ['--scene-threshold', '0'],
                          ['--delta-threshold', '1'], ['--delta-region', 'adaptive']):
                result = subprocess.run([sys.executable, '-B', '-m', 'sixel_video', 'missing.mp4', str(target), *flags], capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(target.exists())
