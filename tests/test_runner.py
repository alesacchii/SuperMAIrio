import io
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.config import Config
from app.contracts import Action
from app.game import MarioGame
from app.moves import MOVES
from app.runner import main, run


class FakeWindow:
    def __init__(self):
        self.open = True
        self.tick = 0
        self.closed = False
        self.captions = []

    def poll(self):
        self.tick += 1
        if self.tick == 7:
            self.open = False

    def consume_reset(self):
        return self.tick == 4

    def action(self):
        return Action.RIGHT

    def show(self, observation, caption):
        self.captions.append(caption)

    def close(self):
        self.closed = True


class RunnerTests(unittest.TestCase):
    def test_default_demo_executes_every_move_action_before_end(self):
        game = MarioGame()
        with patch("app.runner.MarioGame", return_value=game), \
             patch.object(game, "step", wraps=game.step) as step, \
             patch("sys.stdout", io.StringIO()):
            run(Config(mode="demo", headless=True))
        scripted = {segment.action for move in MOVES.values() for segment in move.segments}
        self.assertLessEqual(scripted, {call.args[0] for call in step.call_args_list})
        self.assertEqual({call.args[1] for call in step.call_args_list}, {1})

    def test_headless_episodes_and_limit(self):
        output = io.StringIO()
        with patch("sys.stdout", output):
            run(Config(mode="demo", headless=True, episodes=2, max_frames=7))
        self.assertEqual(output.getvalue().count("limite di frame raggiunto; frame=7"), 2)

    def test_manual_waits_after_end_and_resets_on_r(self):
        window = FakeWindow()
        game = MarioGame(max_frames=2)
        with patch("app.runner.MarioGame", return_value=game), \
             patch.dict(sys.modules, {"app.viewer": SimpleNamespace(GameWindow=lambda: window)}), \
             patch.object(game, "reset", wraps=game.reset) as reset, \
             patch.object(game, "step", wraps=game.step) as step, \
             patch("app.runner.sleep"), patch("sys.stdout", io.StringIO()):
            run(Config(mode="manual", max_frames=2))
        self.assertEqual(reset.call_count, 2)
        self.assertEqual(step.call_count, 4)
        self.assertTrue(window.closed)
        self.assertTrue(any("R: nuovo tentativo" in text for text in window.captions))

    def test_step_failure_closes_game_and_window(self):
        window = FakeWindow()
        game = MarioGame()
        with patch("app.runner.MarioGame", return_value=game), \
             patch.dict(sys.modules, {"app.viewer": SimpleNamespace(GameWindow=lambda: window)}), \
             patch.object(game, "step", side_effect=OSError("failure")), \
             patch.object(game, "close", wraps=game.close) as close:
            with self.assertRaises(OSError):
                run(Config(mode="demo"))
        close.assert_called_once()
        self.assertTrue(window.closed)

    def test_interrupt_exit_status(self):
        with patch("app.runner.run", side_effect=KeyboardInterrupt), patch("sys.stdout", io.StringIO()):
            self.assertEqual(main(["--headless"]), 130)


if __name__ == "__main__":
    unittest.main()
