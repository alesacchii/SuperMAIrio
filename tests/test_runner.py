import io
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from helpers import MODEL_ENV

from supermairio.config import Config
from supermairio.contracts import Action
from supermairio.game.emulator import MarioGame
from supermairio.game.moves import MOVES
from supermairio.cli import main
from supermairio.runtime.play import run


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
        with patch("supermairio.runtime.play.MarioGame", return_value=game), \
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
        self.assertEqual(output.getvalue().count("frame limit reached; frames=7"), 2)

    def test_manual_waits_after_end_and_resets_on_r(self):
        window = FakeWindow()
        game = MarioGame(max_frames=2)
        with patch("supermairio.runtime.play.MarioGame", return_value=game), \
             patch.dict(sys.modules, {"supermairio.game.viewer": SimpleNamespace(GameWindow=lambda: window)}), \
             patch.object(game, "reset", wraps=game.reset) as reset, \
             patch.object(game, "step", wraps=game.step) as step, \
             patch("supermairio.runtime.play.sleep"), patch("sys.stdout", io.StringIO()):
            run(Config(mode="manual", max_frames=2))
        self.assertEqual(reset.call_count, 2)
        self.assertEqual(step.call_count, 4)
        self.assertTrue(window.closed)
        self.assertTrue(any("R: new attempt" in text for text in window.captions))

    def test_step_failure_closes_game_and_window(self):
        window = FakeWindow()
        game = MarioGame()
        with patch("supermairio.runtime.play.MarioGame", return_value=game), \
             patch.dict(sys.modules, {"supermairio.game.viewer": SimpleNamespace(GameWindow=lambda: window)}), \
             patch.object(game, "step", side_effect=OSError("failure")), \
             patch.object(game, "close", wraps=game.close) as close:
            with self.assertRaises(OSError):
                run(Config(mode="demo"))
        close.assert_called_once()
        self.assertTrue(window.closed)

    @patch.dict("supermairio.config.os.environ", MODEL_ENV)
    def test_interrupt_exit_status(self):
        with patch("supermairio.runtime.play.run", side_effect=KeyboardInterrupt), patch("sys.stdout", io.StringIO()):
            self.assertEqual(main(["play", "--headless"]), 130)


if __name__ == "__main__":
    unittest.main()
