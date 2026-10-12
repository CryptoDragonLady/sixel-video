import io
import os
import select
import threading
import unittest

from sixel_video.converter import ConversionProgress, duration, supports_sixel


class TerminalTests(unittest.TestCase):
    def test_duration_and_redirected_progress(self):
        self.assertEqual(duration(None), '--:--')
        self.assertEqual(duration(1.5), '00:02')
        self.assertEqual(duration(3661), '1:01:01')
        stream = io.StringIO()
        self.assertFalse(supports_sixel(stream))
        progress = ConversionProgress(100, style='sixel', stream=stream)
        progress.update(50, force=True)
        progress.update(100, force=True, stage='Done')
        progress.close()
        progress.close()
        self.assertIn('50.0%', stream.getvalue())
        self.assertIn('ETA', stream.getvalue())
        self.assertNotIn('\x1b', stream.getvalue())

    @unittest.skipUnless(os.name == 'posix', 'PTY capability tests need POSIX')
    def test_capability_probe_matches_whole_features_and_restores_terminal(self):
        import pty
        import termios

        for response, expected in ((b'\x1b[?64;1;4;22c', True), (b'\x9b?64;4c', True),
                                   (b'\x1b[?64;14;40c', False), (None, False)):
            master, slave = pty.openpty()
            original = termios.tcgetattr(slave)
            queried = []

            def reply():
                if select.select([master], [], [], 1)[0]:
                    queried.append(os.read(master, 256))
                    if response is not None:
                        os.write(master, response)

            worker = threading.Thread(target=reply)
            worker.start()
            try:
                with os.fdopen(os.dup(slave), 'w') as stream:
                    self.assertEqual(supports_sixel(stream, timeout=0.15), expected)
                worker.join(timeout=2)
                self.assertFalse(worker.is_alive())
                self.assertEqual(queried, [b'\x1b[c'])
                self.assertEqual(termios.tcgetattr(slave), original)
            finally:
                os.close(slave)
                os.close(master)


if __name__ == '__main__':
    unittest.main()
