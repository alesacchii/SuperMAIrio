"""Windows frame waits use short sleeps without losing completion notifications."""

import unittest
from unittest.mock import patch

from app.openrouter import DecisionRequestHandle


class WorkerTimingTests(unittest.TestCase):
    def test_wait_preserves_deadline_and_can_wake_for_completion(self):
        for complete_at in (None, 0.003):
            with self.subTest(complete_at=complete_at):
                handle = DecisionRequestHandle()
                now = [0.0]
                sleeps = []

                def sleep(seconds):
                    sleeps.append(seconds)
                    now[0] += seconds
                    if complete_at is not None and now[0] >= complete_at:
                        handle._ready.set()

                with patch("app.openrouter.sys.platform", "win32"), \
                        patch("app.openrouter.perf_counter", side_effect=lambda: now[0]), \
                        patch("app.openrouter.sleep", side_effect=sleep):
                    self.assertEqual(handle.wait(1 / 60), complete_at is not None)
                    self.assertEqual(handle.wait(0), complete_at is not None)
                self.assertTrue(all(0 < duration <= 0.002 for duration in sleeps))
                if complete_at is None:
                    self.assertAlmostEqual(now[0], 1 / 60)
                else:
                    self.assertLessEqual(now[0] - complete_at, 0.002)


if __name__ == "__main__":
    unittest.main()
