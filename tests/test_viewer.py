"""Opt-in display checks: SUPERMAIRIO_TEST_DISPLAY=1, then unittest discovery."""

import os
import unittest
from pathlib import Path

from supermairio.contracts import Action
from supermairio.game.emulator import MarioGame


@unittest.skipUnless(os.environ.get("SUPERMAIRIO_TEST_DISPLAY") == "1", "requires a Windows/OpenGL display")
class DisplayTests(unittest.TestCase):
    def test_realtime_wait_and_escape(self):
        import json
        import tempfile
        from io import StringIO
        from unittest.mock import patch
        import pyglet
        from pyglet.window import key
        from supermairio.config import Config
        from supermairio.runtime.play import run
        from supermairio.runtime.session import SessionLog
        from supermairio.game.viewer import GameWindow
        from test_decisions import FakeClient

        client = FakeClient(wait=True)
        captions = []
        class Window(GameWindow):
            ticks = 0
            def show(self, observation, caption):
                captions.append(caption)
                super().show(observation, caption)

            def poll(self):
                super().poll()
                self.ticks += 1
                if self.ticks == 3:
                    self.window.dispatch_event("on_draw")
                    screenshot = Path(".local/verification/realtime-window.png")
                    screenshot.parent.mkdir(parents=True, exist_ok=True)
                    with screenshot.open("wb") as output:
                        pyglet.image.get_buffer_manager().get_color_buffer().save(str(screenshot), file=output)
                    self.window.dispatch_event("on_key_press", key.ESCAPE, 0)
                    super().poll()
        with tempfile.TemporaryDirectory() as directory:
            factory = lambda config: SessionLog(config, root=directory)
            with patch("supermairio.runtime.play.decisions_key", return_value="test-key"), \
                 patch("supermairio.agent.load_model", return_value=client), \
                 patch("supermairio.runtime.session.SessionLog", side_effect=factory), \
                 patch("supermairio.game.viewer.GameWindow", Window), patch("sys.stdout", StringIO()):
                run(Config(max_frames=60, control_mode="moves"))
            summary = json.loads(next(Path(directory).glob("*/summary.json")).read_text())
            self.assertEqual(summary["status"], "stopped")
            self.assertEqual(summary["frames"], 2)
            self.assertEqual(summary["waiting_frames"], 2)
            self.assertEqual(summary["cancelled_requests"], 1)
            self.assertTrue(client.cancelled.is_set())
            self.assertTrue(captions)
            self.assertTrue(all("moves 0 | discarded 0" in caption for caption in captions))

    def test_render_keyboard_focus_reset_and_escape(self):
        import pyglet
        from pyglet.window import key
        from supermairio.game.viewer import GameWindow

        window = GameWindow()
        try:
            with MarioGame() as game:
                observation = game.reset(123)
                window.show(observation, "SuperMAIrio — verifica display")
                window.poll()

                def event(name, *args):
                    window.window.dispatch_event(name, *args)
                    window.poll()

                event("on_key_press", key.RIGHT, 0)
                event("on_key_press", key.SPACE, 0)
                event("on_key_press", key.LSHIFT, 0)
                self.assertEqual(window.action(), Action.RIGHT_RUN_JUMP)
                result = game.step(window.action(), 12)
                self.assertGreater(result.observation.info["x_pos"], observation.info["x_pos"])
                self.assertGreater(result.observation.info["y_pos"], observation.info["y_pos"])
                window.show(result.observation, "SuperMAIrio — right + run + jump")

                # Capture the app framebuffer for visual QA, with no OS automation.
                window.window.dispatch_event("on_draw")
                screenshot = Path(".local/verification/window.png")
                screenshot.parent.mkdir(parents=True, exist_ok=True)
                with screenshot.open("wb") as output:
                    pyglet.image.get_buffer_manager().get_color_buffer().save(str(screenshot), file=output)

                event("on_key_release", key.SPACE, 0)
                self.assertEqual(window.action(), Action.RIGHT_RUN)
                event("on_key_press", key.LEFT, 0)
                self.assertEqual(window.action(), Action.NOOP)
                event("on_deactivate")
                self.assertEqual(window.action(), Action.NOOP)
                event("on_key_press", key.RIGHT, 0)
                event("on_key_press", key.R, 0)
                self.assertTrue(window.consume_reset())
                self.assertFalse(window.consume_reset())
                self.assertEqual(window.action(), Action.NOOP)
                game.reset(123)
                event("on_key_press", key.ESCAPE, 0)
                self.assertFalse(window.open)
        finally:
            window.close()

    def test_window_close(self):
        from supermairio.game.viewer import GameWindow
        window = GameWindow()
        try:
            window.poll()
            window.window.dispatch_event("on_close")
            window.poll()
            self.assertFalse(window.open)
        finally:
            window.close()
