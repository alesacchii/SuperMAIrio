"""Offline regressions from three recorded deaths; no provider or external run files.

The fixture contains only seed, buttons, frame counts and position checkpoints.
Counterfactual moves are scripted experiments, not evidence of model quality.
"""

import json
from pathlib import Path
import unittest

from app.contracts import Action
from app.game import MarioGame
from app.moves import MOVES, MoveExecutor


REPLAYS = json.loads(Path(__file__).with_name("fixtures").joinpath("jump_replays.json").read_text())


def actions(replay):
    for action, count in replay["actions"]:
        yield from [Action(action)] * count


def prefix(game, replay):
    observation = game.reset(replay["seed"])
    last = Action.NOOP
    for frame, action in enumerate(actions(replay), 1):
        observation = game.step(action, 1).observation
        last = action
        if frame == replay["cut"]:
            break
    return observation, last


def alternative(game, replay, move, frames=80):
    observation, last = prefix(game, replay)
    executor = MoveExecutor()
    executor.last_action = last
    chosen = MOVES[move]
    snapshots = []
    started = None
    for offset in range(1, frames + 1):
        executor.settle(observation.info["on_ground"])
        if started is None and (not chosen.jump or observation.info["on_ground"]):
            executor.start(chosen)
            started = replay["cut"] + offset
        # This historical counterfactual explicitly waits for ground; the live controller never queues jumps.
        action = executor.current()[0] if started is not None else Action.RIGHT_RUN
        result = game.step(action, 1)
        if started is not None:
            executor.advance(result.frames_executed)
        else:
            executor.last_action = action
        observation = result.observation
        snapshots.append(observation.info)
        if result.done:
            break
    return snapshots, started


class JumpReplayTests(unittest.TestCase):
    def test_replacing_jump_releases_a_and_reduces_real_jump_height(self):
        peaks = []
        for interrupt in (False, True):
            with MarioGame(max_frames=90) as game:
                observation = game.reset(123)
                executor = MoveExecutor()
                executor.start(MOVES["high_jump_up"])
                heights = []
                for frame in range(65):
                    executor.settle(observation.info["on_ground"])
                    if interrupt and frame == 5:
                        executor.start(MOVES["wait"])
                    action, _ = executor.current()
                    if interrupt and frame >= 5:
                        self.assertEqual(action, Action.NOOP)
                    result = game.step(action, 1)
                    executor.advance(result.frames_executed)
                    observation = result.observation
                    heights.append(observation.info["y_pos"])
                peaks.append(max(heights))
        self.assertGreater(peaks[0], peaks[1] + 10)

    def test_recorded_deaths_and_corrected_perception(self):
        for replay in REPLAYS:
            with self.subTest(case=replay["case"]), MarioGame() as game:
                game.reset(replay["seed"])
                checkpoints = {frame: (x, ground) for frame, x, ground in replay["positions"]}
                captured = {}
                for frame, action in enumerate(actions(replay), 1):
                    result = game.step(action, 1)
                    info = result.observation.info
                    if frame in checkpoints:
                        self.assertEqual((info["x_pos"], info["on_ground"]), checkpoints[frame])
                        captured[frame] = info
                    self.assertEqual(result.done, frame == replay["death_frame"])
                self.assertTrue(info["death"])
                self.assertEqual(info["x_pos"], replay["death_x"])
                if replay["case"] == "pit":
                    for frame in (662, 680, 688, 696):
                        info = captured[frame]
                        pit = info["scene"]["pit_ahead"]
                        self.assertEqual((info["x_pos"] + pit["dx"], pit["width_px"]), (1376, 48))
                        self.assertFalse(pit["width_is_lower_bound"])
                    self.assertTrue(captured[696]["scene"]["pit_ahead"]["under_mario"])
                elif replay["case"] == "enemy":
                    info = captured[269]
                    self.assertTrue(info["on_ground"])
                    self.assertTrue(any(e["type"] == "goomba" and e["dx"] == 12 and e["dy"] == 0
                        for e in info["scene"]["enemies"]))
                else:
                    partial = captured[1135]["scene"]["pit_ahead"]
                    self.assertEqual(partial["width_px"], 15)  # Last tile is only partly on screen.
                    self.assertTrue(partial["width_is_lower_bound"])
                    self.assertFalse(partial["far_edge_visible"])
                    full = captured[1149]["scene"]["pit_ahead"]
                    self.assertEqual(full["width_px"], 32)
                    self.assertFalse(full["width_is_lower_bound"])
                    self.assertTrue(captured[1158]["on_ground"])
                    self.assertFalse(captured[1164]["on_ground"])
                    self.assertGreater(captured[1164]["scene"]["mario"]["speed"], 2)

    def test_high_jump_clears_the_recorded_gap_but_is_not_a_safe_level_strategy(self):
        replay = next(r for r in REPLAYS if r["case"] == "pit")
        with MarioGame() as game:
            short, _ = alternative(game, replay, "short_jump_right")
            high, _ = alternative(game, replay, "high_jump_right")
        self.assertTrue(short[-1]["death"])
        self.assertEqual(short[-1]["x_pos"], 1417)
        self.assertTrue(any(i["x_pos"] >= 1424 and i["on_ground"] and not i["death"] for i in high))
        # With no further decisions even this better jump later hits another hazard.
        self.assertTrue(high[-1]["death"])
        self.assertGreater(high[-1]["x_pos"], 1424)

    def test_countersteering_avoids_the_recorded_goomba(self):
        replay = next(r for r in REPLAYS if r["case"] == "enemy")
        with MarioGame() as game:
            released, _ = alternative(game, replay, "wait")
            steered, started = alternative(game, replay, "walk_left")
        self.assertTrue(released[-1]["death"])
        self.assertEqual(started, replay["cut"] + 1)
        self.assertEqual(len(steered), 80)
        self.assertFalse(steered[-1]["death"])
        self.assertTrue(steered[-1]["on_ground"])

    def test_stair_edge_requires_earlier_jump_or_braking_not_just_release(self):
        replay = next(r for r in REPLAYS if r["case"] == "stairs")
        with MarioGame() as game:
            released, _ = alternative(game, replay, "wait")
            jumped, started = alternative(game, replay, "high_jump_right")
            steered, _ = alternative(game, replay, "walk_left")
        self.assertTrue(released[-1]["death"])
        self.assertEqual(started, 1159)  # This historical script explicitly waits for ground.
        for snapshots in (jumped, steered):
            self.assertEqual(len(snapshots), 80)
            self.assertFalse(snapshots[-1]["death"])


if __name__ == "__main__":
    unittest.main()
