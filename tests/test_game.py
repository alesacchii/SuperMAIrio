from dataclasses import replace
import unittest
from itertools import product
from unittest.mock import patch

import numpy as np

from app.config import (BEST_CHOICE_PREVIEW, BEST_EXECUTION_MODE, BEST_PARALLEL_REQUESTS, Config,
    parse_config)
from app.contracts import Action, BUTTONS, keyboard_action
from app.game import MarioGame
from app.moves import MOVES
from app.runner import DEMO_LOOP, DEMO_SEQUENCE, demo_moves


class FakeEnvironment:
    def __init__(self, end_at=None, truncated=False):
        self.end_at = end_at
        self.truncated = truncated
        self.rgb = np.zeros((240, 256, 3), dtype=np.uint8)
        self.info = {"nested": {"frame": 0}}
        self.actions = []
        self.closed = 0

    def reset(self, seed=None):
        self.actions.clear()
        self.rgb.fill(0)
        self.info["nested"]["frame"] = 0
        return self.rgb, self.info

    def step(self, action):
        self.actions.append(action)
        count = len(self.actions)
        self.rgb.fill(count)
        self.info["nested"]["frame"] = count
        done = count == self.end_at
        return self.rgb, 1.5, done and not self.truncated, done and self.truncated, self.info

    def close(self):
        self.closed += 1


class GameContractTests(unittest.TestCase):
    def test_joypad_mapping(self):
        expected = [
            ["NOOP"], ["A"], ["left"], ["left", "A"], ["left", "B"],
            ["left", "A", "B"], ["right"], ["right", "A"],
            ["right", "B"], ["right", "A", "B"],
        ]
        raw = FakeEnvironment()
        with patch("app.game.gym.make", return_value=raw) as make, patch("app.game.JoypadSpace", return_value=raw) as wrapper:
            game = MarioGame(17)
            wrapper.assert_called_once_with(raw, expected)
            self.assertEqual(make.call_args.kwargs["max_episode_steps"], 17)
            game.close()

    def test_exact_duration_replacement_release_and_owned_observations(self):
        env = FakeEnvironment()
        with MarioGame(environment=env) as game:
            initial = game.reset(123)
            result = game.step("right_jump", 3)
            game.step(Action.LEFT, 2)
            game.step(Action.NOOP, 1)
            self.assertEqual(env.actions, [7, 7, 7, 2, 2, 0])
            self.assertEqual(result.frames_executed, 3)
            self.assertEqual(result.reward, 4.5)
            self.assertFalse(result.done)
            self.assertEqual(result.observation.rgb[0, 0, 0], 3)
            self.assertEqual(initial.rgb[0, 0, 0], 0)
            self.assertEqual(result.observation.info["nested"]["frame"], 3)
            self.assertTrue(result.observation.rgb.flags.c_contiguous)

    def test_invalid_commands_never_advance(self):
        env = FakeEnvironment()
        with MarioGame(environment=env) as game:
            game.reset()
            for invalid in (0, -1, 1.5, True, "6", None):
                with self.subTest(frames=invalid), self.assertRaises(ValueError):
                    game.step(Action.RIGHT, invalid)
            for invalid in ("up", "RIGHT", 7, None, [], {}):
                with self.subTest(action=invalid), self.assertRaises(ValueError):
                    game.step(invalid, 1)
            self.assertEqual(env.actions, [])
            self.assertEqual(game.step(Action.NOOP, 1).frames_executed, 1)

    def test_termination_and_truncation_require_reset(self):
        for truncated in (False, True):
            env = FakeEnvironment(end_at=2, truncated=truncated)
            game = MarioGame(environment=env)
            with self.assertRaises(RuntimeError):
                game.step(Action.NOOP)
            game.reset()
            result = game.step(Action.RIGHT, 8)
            self.assertEqual(result.frames_executed, 2)
            self.assertEqual(result.terminated, not truncated)
            self.assertEqual(result.truncated, truncated)
            with self.assertRaises(RuntimeError):
                game.step(Action.NOOP)
            game.reset()
            self.assertFalse(game.step(Action.NOOP, 1).done)
            game.close()
            game.close()
            self.assertEqual(env.closed, 1)
            with self.assertRaises(RuntimeError):
                game.reset()

    def test_failure_closes_and_requires_reset(self):
        env = FakeEnvironment()
        game = MarioGame(environment=env)
        with self.assertRaises(OSError), game:
            game.reset()
            with patch.object(env, "step", side_effect=OSError("emulator failure")):
                game.step(Action.RIGHT)
        self.assertEqual(env.closed, 1)

    def test_keyboard_combinations(self):
        for left, right, jump, run in product((False, True), repeat=4):
            action = keyboard_action(left, right, jump, run)
            buttons = BUTTONS[action]
            self.assertEqual("left" in buttons, left and not right)
            self.assertEqual("right" in buttons, right and not left)
            self.assertEqual("A" in buttons, jump)
            self.assertEqual("B" in buttons, run and left != right)

    def test_demo_restarts_and_covers_all_moves(self):
        first, second = demo_moves(), demo_moves()
        count = len(DEMO_SEQUENCE) + 2 * len(DEMO_LOOP)
        sequence = [next(first) for _ in range(count)]
        self.assertEqual({move.name for move in sequence[:len(DEMO_SEQUENCE) + len(DEMO_LOOP)]}, set(MOVES))
        self.assertEqual(sequence, [next(second) for _ in range(count)])

    @patch.dict("app.config.os.environ", {"OPENROUTER_MODEL": Config().model})
    def test_configuration(self):
        self.assertEqual(parse_config([]), replace(Config(), execution_mode=BEST_EXECUTION_MODE,
            choice_preview=BEST_CHOICE_PREVIEW, parallel_requests=BEST_PARALLEL_REQUESTS, image=False))
        for args in (["--mode", "manual", "--headless"], ["--episodes", "0"],
                     ["--max-frames", "-2"], ["--game-fps", "1.5"]):
            with self.subTest(args=args), self.assertRaises(SystemExit), patch("sys.stderr"):
                parse_config(args)


class RealBackendTests(unittest.TestCase):
    def test_rgb_movement_jump_and_repeatable_reset(self):
        with MarioGame() as game:
            initial = game.reset(123)
            self.assertEqual(initial.rgb.shape, (240, 256, 3))
            self.assertEqual(initial.rgb.dtype, np.uint8)
            before = initial.rgb.copy()
            moved = game.step(Action.RIGHT, 30)
            self.assertGreater(moved.observation.info["x_pos"], initial.info["x_pos"])
            np.testing.assert_array_equal(initial.rgb, before)
            reset = game.reset(123)
            np.testing.assert_array_equal(reset.rgb, initial.rgb)
            self.assertEqual(reset.info, initial.info)
            self.assertTrue(reset.info["on_ground"])
            jumped = game.step(Action.JUMP, 12)
            self.assertGreater(jumped.observation.info["y_pos"], reset.info["y_pos"])
            self.assertEqual(jumped.frames_executed, 12)
            self.assertFalse(jumped.observation.info["on_ground"])
            landed = game.step(Action.NOOP, 60)
            self.assertTrue(landed.observation.info["on_ground"])

    def test_real_frame_limit(self):
        with MarioGame(max_frames=7) as game:
            game.reset(123)
            result = game.step(Action.NOOP, 20)
            self.assertEqual(result.frames_executed, 7)
            self.assertTrue(result.truncated)
            self.assertFalse(result.terminated)
            with self.assertRaises(RuntimeError):
                game.step(Action.NOOP)
            game.reset(123)
            self.assertEqual(game.step(Action.NOOP, 2).frames_executed, 2)

    def test_all_actions_execute_in_real_backend(self):
        with MarioGame() as game:
            for action in Action:
                game.reset(123)
                result = game.step(action, 6)
                self.assertEqual(result.frames_executed, 6)
                self.assertFalse(result.done)


if __name__ == "__main__":
    unittest.main()
