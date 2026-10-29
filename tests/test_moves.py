"""Move catalog and frame-by-frame executor."""

import unittest

from app.contracts import Action, has_jump, with_jump, without_jump
from app.moves import (CHOICES, CONTINUE, HIGH_HOLD, LANDING_CAP, MOVES, SHORT_HOLD, Flight, MoveExecutor,
    jump_airtime, jump_reach)


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
                # A jump starts by pressing A.
                self.assertEqual(has_jump(move.segments[0].action), move.jump)
                self.assertEqual(move.summary()[0]["action"], move.segments[0].action.value)

    def test_high_jumps_hold_a_for_full_height(self):
        self.assertGreaterEqual(HIGH_HOLD, 25)
        for name in ("high_jump_right", "high_jump_left", "high_jump_up"):
            first = MOVES[name].segments[0]
            self.assertEqual((first.frames, has_jump(first.action)), (HIGH_HOLD, True))


class ReachTests(unittest.TestCase):
    def test_measured_points_interpolation_and_bounds(self):
        self.assertEqual(jump_reach(0), {"short_jump": 23, "high_jump": 53})
        self.assertEqual(jump_reach(1.75), {"short_jump": 52, "high_jump": 84})
        self.assertEqual(jump_reach(3.0), {"short_jump": 87, "high_jump": 150})
        self.assertEqual(jump_reach(2.4), {"short_jump": 70, "high_jump": 118})
        self.assertEqual(jump_reach(4.0), jump_reach(3.0))
        self.assertEqual(jump_reach(-1.75), jump_reach(1.75))

    def test_airtime_follows_the_speed_brackets_and_the_hold(self):
        self.assertEqual([jump_airtime(speed, HIGH_HOLD) for speed in (0, 1.0, 1.12, 1.75, 1.88, 3.0, -3.0)],
            [44, 44, 48, 48, 50, 50, 50])
        self.assertEqual([jump_airtime(speed, SHORT_HOLD) for speed in (0, 1.5, 3.0)], [27, 30, 29])
        self.assertEqual(jump_airtime(0, 1), 27)
        self.assertEqual(jump_airtime(0, 99), 44)
        self.assertEqual(jump_airtime(0, (SHORT_HOLD + HIGH_HOLD) // 2), 36)

    def test_with_jump_is_the_inverse_of_without_jump(self):
        for action in Action:
            with self.subTest(action=action):
                self.assertTrue(has_jump(with_jump(action)))
                if not has_jump(action):
                    self.assertEqual(without_jump(with_jump(action)), action)


class FlightTests(unittest.TestCase):
    def fly(self, action, grounds, speed=3.0, hold=0):
        """Steps with the ground after each frame; returns the estimate after each one.
        hold: A frames still planned before the first of these frames, as the executor reports."""
        estimates = []
        for index, ground in enumerate(grounds, 1):
            self.flight.step(action, self.ground, ground, speed)
            self.ground = ground
            estimates.append(self.flight.landing_in(speed, ground, max(hold - index, 0)))
        return estimates

    def setUp(self):
        self.flight, self.ground = Flight(), True

    def test_estimate_counts_down_from_the_press_and_ends_at_the_landing(self):
        self.assertIsNone(self.flight.landing_in(3.0, True))
        # A jump about to be pressed: counted from now.
        self.assertEqual(self.flight.landing_in(3.0, True, HIGH_HOLD), 50)
        self.assertEqual(self.fly(Action.RIGHT_RUN_JUMP, [True, False, False], hold=HIGH_HOLD), [49, 48, 47])
        self.assertEqual(self.fly(Action.RIGHT_RUN_JUMP, [False, True], hold=HIGH_HOLD - 3), [46, None])
        self.assertIsNone(self.flight.frames)

    def test_hold_still_to_come_and_released_early(self):
        self.fly(Action.JUMP, [True, False], speed=0)
        self.assertEqual(self.flight.landing_in(0, False, HIGH_HOLD - 2), 42)
        self.fly(Action.NOOP, [False], speed=0)  # A released after 2 frames: a short jump
        self.assertEqual(self.flight.landing_in(0, False, HIGH_HOLD), 27 - 3)

    def test_unknown_without_a_jump_or_once_below_take_off_height(self):
        self.assertEqual(self.fly(Action.RIGHT_RUN, [False, False]), [None, None])  # walked off a ledge
        self.setUp()
        self.fly(Action.RIGHT_RUN_JUMP, [False] * 28)
        self.assertIsNone(self.fly(Action.RIGHT_RUN, [False] * 25)[-1])  # into a pit
        self.setUp()
        self.fly(Action.RIGHT_RUN_JUMP, [False] * 3)
        self.assertEqual(self.fly(Action.RIGHT_RUN_JUMP, [None]), [None])

    def test_a_held_from_before_or_on_the_ground_is_not_a_jump(self):
        self.flight.last_action = Action.RIGHT_RUN_JUMP
        self.assertEqual(self.fly(Action.RIGHT_RUN_JUMP, [True]), [None])
        self.setUp()
        self.fly(Action.RIGHT_RUN_JUMP, [True] * 4)  # blocked: A never leaves the ground
        self.assertIsNone(self.flight.frames)


class ExecutorTests(unittest.TestCase):
    def test_idle_executor_waits_with_noop(self):
        executor = MoveExecutor()
        self.assertTrue(executor.finished)
        self.assertEqual(play(executor, 2), [(Action.NOOP, "waiting")] * 2)

    def test_move_runs_its_script_then_holds_direction_without_a(self):
        executor = MoveExecutor()
        executor.start(MOVES["walk_right"])
        self.assertEqual(play(executor, 16), [(Action.RIGHT, "move")] * 16)
        self.assertTrue(executor.finished)
        self.assertEqual(executor.frames, 16)
        self.assertEqual(play(executor, 3), [(Action.NOOP, "waiting")] * 3)
        executor.start(MOVES["high_jump_up"])
        play(executor, HIGH_HOLD + LANDING_CAP)
        self.assertEqual(executor.current(), (Action.NOOP, "waiting"))

    def test_jump_holds_a_then_lands_on_ground_signal(self):
        executor = MoveExecutor()
        executor.start(MOVES["high_jump_right"])
        for _ in range(HIGH_HOLD):
            executor.settle(True)  # Ground reported before take-off never shortens A.
            self.assertEqual(executor.current(), (Action.RIGHT_RUN_JUMP, "move"))
            executor.advance(1)
        self.assertEqual(play(executor, 5, on_ground=False), [(Action.RIGHT_RUN, "move")] * 5)
        executor.settle(True)
        self.assertTrue(executor.finished)
        self.assertEqual(executor.frames, HIGH_HOLD + 5)

    def test_landing_segment_capped_without_ground_information(self):
        executor = MoveExecutor()
        executor.start(MOVES["short_jump_right"])
        applied = play(executor, 8 + LANDING_CAP + 1)
        self.assertEqual(applied[-1], (Action.NOOP, "waiting"))
        self.assertEqual(executor.frames, 8 + LANDING_CAP)

    def test_jump_cut_short_releases_a(self):
        executor = MoveExecutor()
        executor.start(MOVES["high_jump_right"])
        play(executor, 2, on_ground=True)  # take-off frames on the ground change nothing
        play(executor, 8, on_ground=False)
        executor.settle(True)  # a ceiling or a higher platform: back on the ground after 10 frames
        self.assertTrue(executor.finished)
        self.assertEqual(executor.current(), (Action.NOOP, "waiting"))
        self.assertEqual(executor.frames, 10)

    def test_double_jump_cut_short_releases_a_then_jumps_again(self):
        executor = MoveExecutor()
        executor.start(MOVES["double_jump_right"])
        play(executor, 6, on_ground=False)
        executor.settle(True)
        self.assertEqual(play(executor, 2, on_ground=True),
            [(Action.RIGHT_RUN, "release"), (Action.RIGHT_RUN_JUMP, "move")])
        self.assertEqual(executor.remaining, None)

    def test_unknown_ground_keeps_the_full_jump(self):
        executor = MoveExecutor()
        executor.start(MOVES["high_jump_right"])
        self.assertEqual(play(executor, HIGH_HOLD), [(Action.RIGHT_RUN_JUMP, "move")] * HIGH_HOLD)

    def test_double_jump_transitions_to_second_takeoff(self):
        executor = MoveExecutor()
        executor.start(MOVES["double_jump_right"])
        play(executor, HIGH_HOLD)
        self.assertEqual(play(executor, 10, on_ground=False), [(Action.RIGHT_RUN, "move")] * 10)
        executor.settle(True)
        # The landing frame presses A again after released frames: a new jump.
        self.assertEqual(executor.current(), (Action.RIGHT_RUN_JUMP, "move"))
        play(executor, HIGH_HOLD, on_ground=False)

    def test_remaining_frames(self):
        executor = MoveExecutor()
        self.assertEqual(executor.remaining, 0)
        executor.start(MOVES["walk_right"])
        play(executor, 5)
        self.assertEqual(executor.remaining, 11)
        executor.start(MOVES["high_jump_right"])
        self.assertIsNone(executor.remaining)  # ends at the landing, not at a known frame
        play(executor, HIGH_HOLD + LANDING_CAP)
        self.assertEqual(executor.remaining, 0)
        executor.start(MOVES["high_jump_up"])  # after right+B: no A held, no release frame

    def test_new_jump_after_a_releases_it_for_one_frame(self):
        executor = MoveExecutor()
        executor.start(MOVES["short_jump_right"])
        play(executor, 3)
        executor.start(MOVES["high_jump_up"])
        self.assertEqual(play(executor, 2), [(Action.NOOP, "release"), (Action.JUMP, "move")])
        executor.start(MOVES["walk_left"])
        self.assertEqual(executor.current(), (Action.LEFT, "move"))  # replacement releases A
        self.assertEqual(executor.jump_hold_left, 0)

class InterruptibleTests(unittest.TestCase):
    def test_every_move_can_replace_every_move_in_midair(self):
        for first in MOVES.values():
            for second in MOVES.values():
                with self.subTest(first=first.name, second=second.name):
                    executor = MoveExecutor()
                    executor.start(first)
                    play(executor, 3, on_ground=False)
                    previous = executor.last_action
                    executor.start(second)
                    action, source = executor.current()
                    release = second.jump and has_jump(previous)
                    self.assertEqual(source, "release" if release else "move")
                    self.assertEqual(action, without_jump(second.segments[0].action) if release
                        else second.segments[0].action)

    def test_interrupted_flight_unknown_until_grounded_takeoff(self):
        flight = Flight()
        flight.step(Action.JUMP, True, False, 0)
        self.assertIsNotNone(flight.landing_in(0, False, 27))
        flight.invalidate()
        flight.step(Action.NOOP, False, False, 0)
        self.assertIsNone(flight.landing_in(0, False))
        flight.step(Action.JUMP, False, False, 0)
        self.assertIsNone(flight.landing_in(0, False, 27))
        flight.step(Action.NOOP, False, True, 0)
        flight.step(Action.JUMP, True, False, 0)
        self.assertEqual(flight.landing_in(0, False, 27), 43)


if __name__ == "__main__":
    unittest.main()
