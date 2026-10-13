import bz2
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import cv2
import numpy as np

from kitty_reference import decode as decode_kitty
from sixel_reference import decode as decode_sixel


class PresetTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source = Path(self.directory.name) / 'source.mp4'
        writer = cv2.VideoWriter(str(self.source), cv2.VideoWriter_fourcc(*'mp4v'), 25, (48, 32))
        self.assertTrue(writer.isOpened())
        y, x = np.indices((32, 48))
        for index in range(8):
            frame = np.stack((x * 5, y * 7, (x + y) * 3), axis=2).astype(np.uint8)
            frame[4:12, index:index + 8] = (25, 200, 80)
            writer.write(frame)
        writer.release()

    def convert(self, *flags):
        output = Path(self.directory.name) / 'output.bz2'
        result = subprocess.run([sys.executable, '-B', '-m', 'sixel_video', str(self.source), str(output),
                                 '--quiet', *flags], capture_output=True,
                                env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        return output.read_bytes()

    def test_presets_match_measured_option_sets_and_reconstruct_video(self):
        # These explicit commands are the benchmark winners S09, S00, K16, K01.
        cases = [('sixel', 'smallest', ['--delta', '--colors', '64', '--accelerator', 'numpy']),
                 ('sixel', 'fastest', []),
                 ('kitty', 'smallest', ['--delta', '--delta-threshold', '2']),
                 ('kitty', 'fastest', ['--kitty-format', 'rgb'])]
        capture = cv2.VideoCapture(str(self.source))
        expected = []
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            expected.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        capture.release()
        for protocol, preset, flags in cases:
            with self.subTest(protocol=protocol, preset=preset):
                actual = self.convert('--preset', preset, '--format', protocol)
                self.assertEqual(actual, self.convert('--format', protocol, *flags))
                data = bz2.decompress(actual)
                if protocol == 'kitty':
                    frames, gaps, _ = decode_kitty(data)
                    self.assertEqual(len(frames), len(expected))
                    self.assertEqual(gaps, [40] * len(expected))
                    for displayed, source in zip(frames, expected):
                        error = np.abs(displayed.astype(int) - source.astype(int))
                        self.assertLessEqual(error.max(), 5 if preset == 'smallest' else 0)
                else:
                    canvas = None
                    updates = data.splitlines(keepends=True)
                    self.assertEqual(len(updates), len(expected))
                    for update in updates:
                        canvas, coverage = decode_sixel(update, canvas)
                        self.assertEqual(canvas.shape, expected[0].shape)
                        if preset == 'fastest':
                            self.assertTrue(coverage.all())

    def test_explicit_options_override_presets_in_either_order(self):
        cases = [('sixel', 'smallest', ['--colors', '128'],
                  ['--delta', '--colors', '128', '--accelerator', 'numpy']),
                 ('sixel', 'fastest', ['--delta'], ['--delta']),
                 ('kitty', 'smallest', ['--delta-threshold', '0'], ['--delta']),
                 ('kitty', 'fastest', ['--kitty-format', 'png'], ['--kitty-format', 'png'])]
        for protocol, preset, override, explicit in cases:
            reference = self.convert('--format', protocol, *explicit)
            for flags in (['--preset', preset, *override], [*override, '--preset', preset]):
                with self.subTest(protocol=protocol, preset=preset, flags=flags):
                    self.assertEqual(self.convert('--format', protocol, *flags), reference)

    def test_invalid_preset_combinations_do_not_create_output(self):
        output = Path(self.directory.name) / 'invalid.bz2'
        for flags, message in [(['--preset', 'unknown'], b'invalid choice'),
                               (['--format', 'kitty', '--preset', 'smallest', '--kitty-mode', 'stream'],
                                b'require animation mode'),
                               (['--preset', 'smallest', '--kitty-format', 'rgb'],
                                b'--kitty-* options require --format kitty')]:
            result = subprocess.run([sys.executable, '-B', '-m', 'sixel_video', str(self.source),
                                     str(output), *flags], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(message, result.stderr)
            self.assertFalse(output.exists())
