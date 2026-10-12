"""Move catalog and frame-by-frame executor."""

import unittest

from app.contracts import Action, has_jump
from app.moves import CHOICES, CONTINUE, HIGH_HOLD, LANDING_CAP, MOVES, MoveExecutor, jump_reach


def play(executor, frames, on_ground=None):
    """Applied (action, source) for each frame."""
    applied = []
    for _ in range(frames):
        executor.settle(on_ground)
        applied.append(executor.current())
        executor.advance(1)
    return applied


class CatalogTests(unittest.TestCase):
    def test_choices_and_segments(self):
        self.assertEqual(CHOICES, (*MOVES, CONTINUE))
        self.assertNotIn(CONTINUE, MOVES)
        for name, move in MOVES.items():
            with self.subTest(move=name):
                self.assertEqual(move.name, name)
                self.assertTrue(move.description and move.segments)
                self.assertTrue(all(segment.frames > 0 for segment in move.segments))
                # Only jumps commit frames, and a jump starts by pressing A.
                self.assertEqual(any(segment.committed for segment in move.segments), move.jump)
                self.assertEqual(move.summary()[0]["action"], move.segments[0].action.value)

    def test_high_jumps_hold_a_for_full_height(self):
        self.assertGreaterEqual(HIGH_HOLD, 25)
        for name in ("high_jump_right", "high_jump_left", "high_jump_up"):
            first = MOVES[name].segments[0]
            self.assertEqual((first.frames, first.committed, has_jump(first.action)), (HIGH_HOLD, True, True))


class ReachTests(unittest.TestCase):
    def test_measured_points_interpolation_and_bounds(self):
        self.assertEqual(jump_reach(0), {"short_jump": 23, "high_jump": 53})
        self.assertEqual(jump_reach(1.75), {"short_jump": 52, "high_jump": 84})
        self.assertEqual(jump_reach(3.0), {"short_jump": 87, "high_jump": 150})
        self.assertEqual(jump_reach(2.4), {"short_jump": 70, "high_jump": 118})
        self.assertEqual(jump_reach(4.0), jump_reach(3.0))
        self.assertEqual(jump_reach(-1.75), jump_reach(1.75))


class ExecutorTests(unittest.TestCase):
    def test_idle_executor_waits_with_noop(self):
        executor = MoveExecutor()
        self.assertTrue(executor.finished)
        self.assertFalse(executor.committed)
        self.assertEqual(play(executor, 2), [(Action.NOOP, "waiting")] * 2)

    def test_move_runs_its_script_then_holds_direction_without_a(self):
        executor = MoveExecutor()
        executor.start(MOVES["walk_right"])
        self.assertEqual(play(executor, 16), [(Action.RIGHT, "move")] * 16)
        self.assertTrue(executor.finished)
        self.assertEqual(executor.frames, 16)
        self.assertEqual(play(executor, 3), [(Action.RIGHT, "tail")] * 3)
        executor.start(MOVES["high_jump_up"])
        play(executor, HIGH_HOLD + LANDING_CAP)
        self.assertEqual(executor.current(), (Action.NOOP, "tail"))

    def test_jump_commits_a_then_lands_on_ground_signal(self):
        executor = MoveExecutor()
        executor.start(MOVES["high_jump_right"])
        for _ in range(HIGH_HOLD):
            self.assertTrue(executor.committed)
            executor.settle(True)  # Ground reported before take-off never shortens A.
            self.assertEqual(executor.current(), (Action.RIGHT_RUN_JUMP, "move"))
            executor.advance(1)
        self.assertFalse(executor.committed)
        self.assertEqual(play(executor, 5, on_ground=False), [(Action.RIGHT_RUN, "move")] * 5)
        executor.settle(True)
        self.assertTrue(executor.finished)
        self.assertEqual(executor.frames, HIGH_HOLD + 5)

    def test_landing_segment_capped_without_ground_information(self):
        executor = MoveExecutor()
        executor.start(MOVES["short_jump_right"])
        applied = play(executor, 8 + LANDING_CAP + 1)
        self.assertEqual(applied[-1], (Action.RIGHT_RUN, "tail"))
        self.assertEqual(executor.frames, 8 + LANDING_CAP)

    def test_jump_cut_short_ends_committed_a(self):
        executor = MoveExecutor()
        executor.start(MOVES["high_jump_right"])
        play(executor, 2, on_ground=True)  # take-off frames on the ground change nothing
        play(executor, 8, on_ground=False)
        self.assertTrue(executor.committed)
        executor.settle(True)  # a ceiling or a higher platform: back on the ground after 10 frames
        self.assertTrue(executor.finished)
        self.assertFalse(executor.committed)
        self.assertEqual(executor.current(), (Action.RIGHT_RUN, "tail"))
        self.assertEqual(executor.frames, 10)

    def test_double_jump_cut_short_releases_a_then_jumps_again(self):
        executor = MoveExecutor()
        executor.start(MOVES["double_jump_right"])
        play(executor, 6, on_ground=False)
        executor.settle(True)
        self.assertEqual(play(executor, 2, on_ground=True),
            [(Action.RIGHT_RUN, "release"), (Action.RIGHT_RUN_JUMP, "move")])
        self.assertTrue(executor.committed)
        self.assertEqual(executor.remaining, None)

    def test_unknown_ground_keeps_the_full_committed_jump(self):
        executor = MoveExecutor()
        executor.start(MOVES["high_jump_right"])
        self.assertEqual(play(executor, HIGH_HOLD), [(Action.RIGHT_RUN_JUMP, "move")] * HIGH_HOLD)
        self.assertFalse(executor.committed)

    def test_double_jump_commits_until_second_take_off(self):
        executor = MoveExecutor()
        executor.start(MOVES["double_jump_right"])
        play(executor, HIGH_HOLD)
        self.assertEqual(play(executor, 10, on_ground=False), [(Action.RIGHT_RUN, "move")] * 10)
        self.assertTrue(executor.committed)
        executor.settle(True)
        # The landing frame presses A again after released frames: a new jump.
        self.assertEqual(executor.current(), (Action.RIGHT_RUN_JUMP, "move"))
        self.assertTrue(executor.committed)
        play(executor, HIGH_HOLD, on_ground=False)
        self.assertFalse(executor.committed)

    def test_remaining_frames_and_tail_action(self):
        executor = MoveExecutor()
        self.assertEqual((executor.remaining, executor.tail_action), (0, Action.NOOP))
        executor.start(MOVES["walk_right"])
        play(executor, 5)
        self.assertEqual((executor.remaining, executor.tail_action), (11, Action.RIGHT))
        executor.start(MOVES["high_jump_right"])
        self.assertIsNone(executor.remaining)  # ends at the landing, not at a known frame
        self.assertEqual(executor.tail_action, Action.RIGHT_RUN)
        play(executor, HIGH_HOLD + LANDING_CAP)
        self.assertEqual(executor.remaining, 0)
        executor.start(MOVES["high_jump_up"])  # after right+B: no A held, no release frame
        self.assertEqual(executor.tail_action, Action.NOOP)

    def test_new_jump_after_a_releases_it_for_one_frame(self):
        executor = MoveExecutor()
        executor.start(MOVES["short_jump_right"])
        play(executor, 3)
        executor.start(MOVES["high_jump_up"])
        self.assertEqual(play(executor, 2), [(Action.NOOP, "release"), (Action.JUMP, "move")])
        executor.start(MOVES["walk_left"])
        self.assertEqual(executor.current(), (Action.LEFT, "move"))

    def test_can_start_waits_for_commitment_and_landing(self):
        executor = MoveExecutor()
        jump, walk = MOVES["high_jump_right"], MOVES["walk_left"]
        self.assertTrue(executor.can_start(jump, None))
        self.assertFalse(executor.can_start(jump, False))
        self.assertTrue(executor.can_start(walk, False))
        executor.start(jump)
        self.assertFalse(executor.can_start(walk, True))
        play(executor, HIGH_HOLD, on_ground=False)
        self.assertTrue(executor.can_start(walk, False))
        self.assertFalse(executor.can_start(jump, False))
        self.assertTrue(executor.can_start(jump, True))


if __name__ == "__main__":
    unittest.main()
