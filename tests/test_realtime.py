"""Deterministic move-loop timelines, aggregation and real emulator smoke tests."""

import asyncio
from contextlib import ExitStack
from io import StringIO
from itertools import groupby
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.config import Config, parse_config
from app.contracts import Action, Decision, has_jump
from app.metrics import ControlHistory, Metrics, distribution
from app.moves import HIGH_HOLD, LANDING_CAP
from app.models.gpt_luna import Model
from app.openrouter import DecisionError
from app.runner import run
from app.session import SessionLog
from test_decisions import FakeClient, FakeGame, observation


def runs(steps):
    """Consecutive applied actions as (action, frames)."""
    return [(action, sum(frames for _, frames in group)) for action, group in groupby(steps, key=lambda step: step[0])]


class Clock:
    def __init__(self):
        self.now = 100.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class Future:
    """Request handle with its own timestamps, like DecisionRequestHandle."""

    def __init__(self, clock, delay, choice):
        self.clock = clock
        self.started_at = clock()
        self.completed_at = None
        self.ready_at = clock() + delay
        self.choice = choice
        self.cancelled = False

    def done(self):
        return self.cancelled or self.clock() >= self.ready_at

    def result(self):
        if self.cancelled:
            raise asyncio.CancelledError()
        if not self.done():
            raise AssertionError("Read a pending result")
        self.completed_at = self.ready_at
        if isinstance(self.choice, Exception):
            raise self.choice
        return Decision(self.choice, "test/model", usage={"cost": 0.01})


class Worker:
    def __init__(self, clock, script, limit=1):
        self.clock = clock
        self.script = script
        self.limit = limit
        self.requests = []
        self.closed = False
        self.calls = []

    def submit(self, payload):
        if self.closed or sum(not request.done() for request in self.requests) >= self.limit:
            raise AssertionError("Too many concurrent requests or closed worker")
        self.calls.append((self.clock(), payload))
        delay, action = self.script.pop(0) if self.script else (10, "walk_right")
        self.requests.append(Future(self.clock, delay, action))
        return self.requests[-1]

    def close(self):
        self.closed = True
        for request in self.requests:
            if not request.done():
                request.cancelled = True
                request.completed_at = self.clock()


class TimedGame(FakeGame):
    def __init__(self, clock, limit=100, **kwargs):
        super().__init__(limit, **kwargs)
        self.clock = clock
        self.step_times = []
        self.step_delay = 0.0

    def step(self, action, duration):
        self.step_times.append(self.clock())
        self.clock.now += self.step_delay
        return super().step(action, duration)


class JumpGame(TimedGame):
    """Mario leaves the ground when A is pressed on it and lands AIRTIME frames later."""

    AIRTIME = 40
    air = 0

    def reset(self, seed):
        self.air = 0
        obs = super().reset(seed)
        obs.info["on_ground"] = True
        return obs

    def step(self, action, duration):
        if self.air:
            self.air -= 1
        elif has_jump(action):
            self.air = self.AIRTIME
        result = super().step(action, duration)
        result.observation.info["on_ground"] = self.air == 0
        return result


class CaptionWindow:
    open = True

    def __init__(self):
        self.captions = []

    def poll(self):
        pass

    def consume_reset(self):
        return False

    def show(self, observation, caption):
        self.captions.append(caption)

    def close(self):
        self.open = False


class RealtimeTests(unittest.TestCase):
    def invoke(self, *, script=(), config=None, game=None, clock=None, window=None, preparation_delay=0, decision_logging_delay=0):
        config = config or Config(headless=True, max_frames=12)
        clock = clock or Clock()
        game = game or TimedGame(clock, config.max_frames)
        workers = []
        script = list(script)
        class Client(Model):
            def build_request(self, *args, **kwargs):
                clock.now += preparation_delay
                return super().build_request(*args, **kwargs)
        client = Client("secret-test", 10)
        def worker_factory(client, connections=1):
            worker = Worker(clock, script, connections)
            workers.append(worker)
            return worker
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            stack.enter_context(patch("app.model_runner.perf_counter", clock))
            stack.enter_context(patch("app.model_runner.sleep", clock.sleep))
            stack.enter_context(patch("app.model_runner.DecisionWorker", side_effect=worker_factory))
            stack.enter_context(patch("app.runner.openrouter_key", return_value="secret-test"))
            stack.enter_context(patch("app.models.load_model", return_value=client))
            stack.enter_context(patch("app.runner.MarioGame", return_value=game))
            class Log(SessionLog):
                def event(self, kind, **data):
                    super().event(kind, **data)
                    if kind == "decision":
                        clock.now += decision_logging_delay
            factory = lambda config: Log(config, root=directory)
            stack.enter_context(patch("app.session.SessionLog", side_effect=factory))
            clock.output = StringIO()
            stack.enter_context(patch("sys.stdout", clock.output))
            if window is not None:
                from types import SimpleNamespace
                stack.enter_context(patch.dict("sys.modules", {"app.viewer": SimpleNamespace(GameWindow=lambda: window)}))
            caught = None
            try:
                run(config)
            except (Exception, KeyboardInterrupt) as exc:
                caught = exc
            session = next(Path(directory).iterdir())
            summary = json.loads((session / "summary.json").read_text())
            events = [json.loads(line) for line in (session / "events.jsonl").read_text().splitlines()]
            persisted = json.loads((session / "config.json").read_text())
            pictures = list((session / "screenshots").glob("*.png"))
            return summary, events, workers, game, clock, persisted, len(pictures), caught

    @staticmethod
    def kinds(events, kind):
        return [event for event in events if event["event"] == kind]

    def test_one_request_at_a_time_called_again_when_move_starts(self):
        summary, events, workers, game, _, _, _, caught = self.invoke(
            script=[(0.05, "walk_right"), (0.05, "run_right")], config=Config(headless=True, max_frames=20))
        self.assertIsNone(caught)
        self.assertEqual(len(workers), 1)
        self.assertEqual(workers[0].limit, 1)  # The fake worker refuses a second request in flight.
        steps = runs(game.steps)
        self.assertEqual([action for action, _ in steps], [Action.NOOP, Action.RIGHT, Action.RIGHT_RUN])
        starts, requests = self.kinds(events, "move_start"), self.kinds(events, "request")
        # Chiamo → Decisione → Azione → Chiamo: the next request leaves when the move starts.
        self.assertEqual(requests[1]["submitted_at"], starts[0]["started_at"])
        self.assertEqual(requests[2]["submitted_at"], starts[1]["started_at"])
        order = [event["event"] for event in events if event["event"] in ("request", "decision")]
        self.assertEqual(order, ["request", "decision"] * 2 + ["request"])
        self.assertEqual(self.kinds(events, "move_end")[0]["outcome"], "replaced")
        self.assertEqual((summary["requests"], summary["decisions"], summary["moves"]), (3, 2, 2))
        self.assertEqual(summary["waiting_frames"], steps[0][1])
        self.assertEqual(summary["cancelled_requests"], 1)

    def test_continue_keeps_running_move_and_repeats_an_ended_one(self):
        summary, events, _, game, _, _, _, caught = self.invoke(
            script=[(0.05, "walk_right"), (0.05, "continue"), (0.5, "continue")],
            config=Config(headless=True, max_frames=60))
        self.assertIsNone(caught)
        self.assertEqual(len(self.kinds(events, "move_continued")), 1)
        starts = self.kinds(events, "move_start")
        self.assertEqual([(start["move"], start["repeated"]) for start in starts],
            [("walk_right", False), ("walk_right", True)])
        self.assertEqual(self.kinds(events, "move_end")[0]["outcome"], "completed")
        self.assertEqual(self.kinds(events, "move_end")[0]["frames_executed"], 16)
        self.assertEqual((summary["continues"], summary["moves"]), (2, 2))
        self.assertGreater(summary["tail_frames"], 0)
        self.assertEqual({action for action, _ in game.steps}, {Action.NOOP, Action.RIGHT})

    def test_move_chosen_during_committed_jump_waits_for_it(self):
        summary, events, _, game, _, _, _, caught = self.invoke(
            script=[(0.05, "high_jump_right"), (0.05, "walk_left")], config=Config(headless=True, max_frames=60))
        self.assertIsNone(caught)
        steps = runs(game.steps)
        self.assertEqual(steps[1], (Action.RIGHT_RUN_JUMP, HIGH_HOLD))
        self.assertEqual(steps[2][0], Action.LEFT)
        deferred = self.kinds(events, "move_deferred")
        self.assertEqual([(event["move"], event["reason"]) for event in deferred], [("walk_left", "committed")])
        # No new call while the decision waits: the next one leaves when walk_left starts.
        start = self.kinds(events, "move_start")[1]
        waiting = [event for event in events if deferred[0]["at"] <= event["at"] < start["started_at"]]
        self.assertFalse(any(event["event"] == "request" for event in waiting))
        self.assertEqual(self.kinds(events, "move_end")[0]["outcome"], "replaced")
        self.assertEqual((summary["deferred_moves"], summary["timings"]["deferred_seconds"]["samples"]), (1, 1))

    def test_new_jump_waits_for_landing(self):
        for delay, reason in ((0.05, "committed"), (0.6, "airborne")):
            with self.subTest(reason=reason):
                clock = Clock()
                summary, events, _, game, _, _, _, caught = self.invoke(
                    script=[(0.05, "high_jump_up"), (delay, "short_jump_right")], clock=clock,
                    game=JumpGame(clock, 90), config=Config(headless=True, max_frames=90))
                self.assertIsNone(caught)
                steps = runs(game.steps)
                # 40 airborne frames after take-off: 28 with A, then 12 falling and the landing frame.
                self.assertEqual(steps[1:4], [(Action.JUMP, HIGH_HOLD), (Action.NOOP, 41 - HIGH_HOLD),
                    (Action.RIGHT_RUN_JUMP, 8)])
                self.assertEqual(self.kinds(events, "move_deferred")[0]["reason"], reason)
                self.assertEqual(summary["jump_release_frames"], 0)

    def test_jump_cut_short_by_a_ceiling_frees_the_deferred_move(self):
        class CeilingGame(JumpGame):
            AIRTIME = 12  # a block above Mario ends the jump long before the 28 committed frames
        clock = Clock()
        summary, events, _, game, _, _, _, caught = self.invoke(
            script=[(0.05, "high_jump_right"), (0.05, "walk_left")], clock=clock,
            game=CeilingGame(clock, 60), config=Config(headless=True, max_frames=60))
        self.assertIsNone(caught)
        steps = runs(game.steps)
        # Take-off frame plus 12 airborne frames, then walk_left starts at the landing.
        self.assertEqual(steps[1:3], [(Action.RIGHT_RUN_JUMP, 13), (Action.LEFT, steps[2][1])])
        end = self.kinds(events, "move_end")[0]
        self.assertEqual((end["move"], end["outcome"], end["frames_executed"]), ("high_jump_right", "completed", 13))
        self.assertEqual(self.kinds(events, "move_deferred")[0]["reason"], "committed")

    def test_stale_response_is_discarded_and_asked_again(self):
        summary, events, _, game, _, _, _, caught = self.invoke(
            script=[(0.8, "walk_right"), (0.05, "run_right")],
            config=Config(headless=True, max_frames=80, max_decision_frames=30))
        self.assertIsNone(caught)
        self.assertEqual([action for action, _ in runs(game.steps)], [Action.NOOP, Action.RIGHT_RUN])
        discarded = self.kinds(events, "request_discarded")
        self.assertEqual((discarded[0]["index"], discarded[0]["reason"]), (1, "stale"))
        self.assertGreater(discarded[0]["observation_age_frames"], discarded[0]["max_decision_frames"])
        self.assertEqual((summary["stale_responses"], summary["moves"], summary["requests"]), (1, 1, 3))

    def test_paused_stops_game_and_asks_when_move_ends(self):
        summary, events, workers, game, _, persisted, _, caught = self.invoke(
            script=[(0.3, "walk_right"), (0.3, "wait")], config=Config(headless=True, max_frames=30, execution_mode="paused"))
        self.assertIsNone(caught)
        self.assertTrue(persisted["game_paused_during_request"])
        self.assertEqual(runs(game.steps), [(Action.RIGHT, 16), (Action.NOOP, 10), (Action.RIGHT, 4)])
        self.assertEqual(summary["requests"], 3)
        # No frame between a request and its decision: the game waits for the model.
        waiting = False
        for event in events:
            waiting = event["event"] == "request" or (waiting and event["event"] != "decision")
            self.assertFalse(waiting and event["event"] == "execution")
        self.assertEqual((summary["waiting_frames"], summary["tail_frames"]), (0, 0))

    def test_ended_move_keeps_direction_without_a_until_next_decision(self):
        summary, events, _, game, _, _, _, caught = self.invoke(
            script=[(0.05, "high_jump_right")], config=Config(headless=True, max_frames=110))
        self.assertIsNone(caught)
        steps = runs(game.steps)
        self.assertEqual([action for action, _ in steps], [Action.NOOP, Action.RIGHT_RUN_JUMP, Action.RIGHT_RUN])
        end = self.kinds(events, "move_end")[0]
        self.assertEqual((end["outcome"], end["frames_executed"]), ("completed", HIGH_HOLD + LANDING_CAP))
        self.assertEqual(summary["tail_frames"], steps[2][1] - LANDING_CAP)
        self.assertEqual({event["source"] for event in self.kinds(events, "execution")}, {"waiting", "move", "tail"})

    def test_staleness_counts_game_frames(self):
        # 2.7 s is 81 frames at 30 FPS (accepted) but 162 frames at 60 FPS (discarded).
        for fps, stale in ((30, 0), (60, 1)):
            with self.subTest(fps=fps):
                summary, events, _, _, _, _, _, caught = self.invoke(script=[(2.7, "walk_right")],
                    config=Config(headless=True, max_frames=200, game_fps=fps, max_episode_seconds=20))
                self.assertIsNone(caught)
                self.assertEqual((summary["stale_responses"], summary["moves"]), (stale, 1 - stale))

    def test_transient_error_is_retried_once_with_current_observation(self):
        transient = lambda: DecisionError("OpenRouter: errore HTTP 504", transient=True)
        summary, events, _, game, _, _, _, caught = self.invoke(
            script=[(0.05, transient()), (0.05, "walk_right"), (0.05, transient()), (0.05, "run_right")],
            config=Config(headless=True, max_frames=60))
        self.assertIsNone(caught)
        self.assertEqual((summary["status"], summary["retried_requests"], summary["errors"]), ("finished", 2, 0))
        failed = self.kinds(events, "request_failed")
        self.assertEqual([(event["index"], event["retrying"]) for event in failed], [(1, True), (3, True)])
        requests = self.kinds(events, "request")
        self.assertGreater(requests[1]["observation_at"], requests[0]["observation_at"])
        self.assertEqual([start["move"] for start in self.kinds(events, "move_start")], ["walk_right", "run_right"])

    def test_second_consecutive_transient_error_stops(self):
        transient = lambda: DecisionError("OpenRouter: timeout dopo 10 secondi", transient=True)
        summary, events, _, _, _, _, _, caught = self.invoke(
            script=[(0.05, transient()), (0.05, transient())], config=Config(headless=True, max_frames=60))
        self.assertIsInstance(caught, DecisionError)
        self.assertEqual((summary["status"], summary["retried_requests"], summary["requests"]), ("error", 1, 2))
        self.assertEqual(len(self.kinds(events, "error")), 1)

    def test_no_scene_hides_ram_perception_from_the_model(self):
        from test_decisions import SCENE
        class SceneGame(TimedGame):
            def step(self, action, duration):
                result = super().step(action, duration)
                result.observation.info["scene"] = SCENE
                return result
        for enabled in (True, False):
            with self.subTest(scene=enabled):
                clock = Clock()
                _, events, workers, _, _, persisted, _, caught = self.invoke(
                    script=[(0.05, "walk_right")], clock=clock, game=SceneGame(clock, 10),
                    config=Config(headless=True, max_frames=10, scene=enabled))
                self.assertIsNone(caught)
                self.assertEqual(persisted["scene"], enabled)
                state = self.kinds(events, "request")[1]["context"]
                self.assertEqual("nearby" in state, enabled)
                self.assertEqual("jump_reach_px" in state["mario"], enabled)

    def test_slow_provider_is_flagged(self):
        for delay, slow in ((0.8, True), (0.05, False)):
            with self.subTest(delay=delay):
                summary, _, _, _, clock, _, _, caught = self.invoke(
                    script=[(delay, "walk_right")] * 4, config=Config(headless=True, max_frames=150))
                self.assertIsNone(caught)
                self.assertEqual(summary["episodes"][0]["slow_provider"], slow)
                self.assertEqual("provider lento" in clock.output.getvalue(), slow)

    def test_error_stops_once_without_retry(self):
        summary, events, workers, game, _, _, _, caught = self.invoke(
            script=[(0.05, DecisionError("simulated failure"))], config=Config(headless=True, max_frames=60))
        self.assertIsInstance(caught, DecisionError)
        self.assertEqual((summary["status"], summary["errors"], summary["requests"]), ("error", 1, 1))
        self.assertEqual(len(self.kinds(events, "error")), 1)
        self.assertTrue(workers[0].closed)

    def test_episode_end_discards_deferred_move_and_resets(self):
        summary, events, workers, _, _, _, _, caught = self.invoke(
            script=[(0.05, "high_jump_right"), (0.05, "walk_left"), (0.05, "walk_right")],
            config=Config(headless=True, max_frames=20, episodes=2))
        self.assertIsNone(caught)
        self.assertEqual(len(workers), 2)
        self.assertTrue(all(worker.closed for worker in workers))
        first = [event for event in events if event.get("episode") == 1]
        discarded = self.kinds(first, "request_discarded")
        self.assertEqual([(event["index"], event["reason"]) for event in discarded], [(2, "frame_limit")])
        self.assertEqual(self.kinds(first, "move_end")[0]["outcome"], "interrupted")
        second = self.kinds([event for event in events if event.get("episode") == 2], "move_start")
        self.assertEqual([start["move"] for start in second], ["walk_right"])
        self.assertEqual(summary["episodes"][0]["discarded_responses"], 1)

    def test_wall_limit_cancels_request_in_flight(self):
        summary, events, _, _, _, _, _, caught = self.invoke(
            script=[(0.05, "walk_right")], config=Config(headless=True, max_episode_seconds=0.2))
        self.assertIsNone(caught)
        self.assertEqual(summary["episodes"][0]["reason"], "wall_limit")
        self.assertEqual(summary["cancelled_requests"], 1)
        self.assertEqual(self.kinds(events, "request_cancelled")[0]["reason"], "wall_limit")
        self.assertEqual(self.kinds(events, "move_end")[0]["outcome"], "interrupted")

    def test_session_files_and_screenshots(self):
        summary, events, _, _, _, persisted, pictures, caught = self.invoke(
            script=[(0.05, "walk_right")], config=Config(headless=True, max_frames=10, save_screenshots=True))
        self.assertIsNone(caught)
        self.assertEqual((summary["results_version"], persisted["results_version"]), (4, 4))
        self.assertEqual(persisted["protocol"], "openrouter-choice-scene-v4")
        self.assertTrue(persisted["scene"])
        self.assertEqual(persisted["moves"]["high_jump_right"][0],
            {"action": "right_run_jump", "frames": HIGH_HOLD, "committed": True, "until_landed": False})
        self.assertEqual(pictures, summary["requests"])
        self.assertEqual([event["screenshot"] for event in self.kinds(events, "request")],
            ["screenshots/000001.png", "screenshots/000002.png"])
        state = self.kinds(events, "request")[1]["context"]
        self.assertEqual(state["move"], {"current": "walk_right", "phase": "running", "ends": "in 16 frames",
            "then": "holds right", "your_move_starts_in_frames": 3})
        self.assertEqual(state["recent_moves"], [])

    def test_caption_shows_move_and_source(self):
        window = CaptionWindow()
        _, _, _, _, _, _, _, caught = self.invoke(
            script=[(0.05, "walk_right")], config=Config(max_frames=10), window=window)
        self.assertIsNone(caught)
        self.assertIn("- (waiting)", window.captions[0])
        self.assertIn("walk_right (move)", window.captions[-1])

    def test_game_fps_paces_realtime(self):
        summary, _, _, game, _, persisted, _, caught = self.invoke(
            config=Config(headless=True, max_frames=5, game_fps=30))
        self.assertIsNone(caught)
        self.assertEqual(persisted["game_fps"], 30)
        self.assertTrue(all(b - a >= 1 / 30 - 1e-10 for a, b in zip(game.step_times, game.step_times[1:])))

    def test_real_backend_with_simulated_model(self):
        with tempfile.TemporaryDirectory() as directory:
            factory = lambda config: SessionLog(config, root=directory)
            with patch("app.runner.openrouter_key", return_value="test-key"), \
                 patch("app.models.load_model", return_value=FakeClient()), \
                 patch("app.session.SessionLog", side_effect=factory), patch("sys.stdout", StringIO()):
                run(Config(headless=True, max_frames=12))
            summary = json.loads(next(Path(directory).glob("*/summary.json")).read_text())
            self.assertEqual(summary["frames"], 12)
            self.assertGreaterEqual(summary["moves"], 1)
            self.assertEqual(summary["status"], "finished")
            self.assertGreater(summary["wall_seconds"], 0.15)
            self.assertIsNone(summary["known_cost"])

    def test_real_backend_jumps_land_with_300ms_model(self):
        class DelayedClient(Model):
            moves = iter(["run_right", "high_jump_right"] * 20)
            async def decide(self, payload):
                await asyncio.sleep(0.3)
                return Decision(next(self.moves), "test/delayed")
        with tempfile.TemporaryDirectory() as directory:
            factory = lambda config: SessionLog(config, root=directory)
            with patch("app.runner.openrouter_key", return_value="test-key"), \
                 patch("app.models.load_model", return_value=DelayedClient("test-key", 10)), \
                 patch("app.session.SessionLog", side_effect=factory), patch("sys.stdout", StringIO()):
                run(Config(headless=True, max_frames=150))
            session = next(Path(directory).iterdir())
            summary = json.loads((session / "summary.json").read_text())
            events = [json.loads(line) for line in (session / "events.jsonl").read_text().splitlines()]
        self.assertEqual((summary["status"], summary["stale_responses"], summary["errors"]), ("finished", 0, 0))
        self.assertGreater(summary["x_pos"], summary["initial_x_pos"])
        self.assertLessEqual(summary["requests"] - summary["decisions"], 1)
        grounds = [event["on_ground"] for event in events if event["event"] == "execution"]
        self.assertIn(False, grounds)
        self.assertIn(True, grounds)
        jumps = [event for event in events if event["event"] == "move_end" and event["move"] == "high_jump_right"
            and event["outcome"] != "interrupted"]
        self.assertTrue(jumps)
        self.assertTrue(all(event["frames_executed"] >= HIGH_HOLD for event in jumps))


class MeasurementTests(unittest.TestCase):
    def test_percentiles_rates_and_partial_cost(self):
        self.assertEqual(distribution([]), {"samples": 0, "median": None, "p95": None})
        self.assertEqual(distribution(list(range(1, 21))), {"samples": 20, "median": 10.5, "p95": 19})
        metrics = Metrics()
        for usage in (None, {"cost": 0.0}, {"cost": 0.1}, {"cost": True}, {"cost": "0.2"}):
            metrics.decision(Decision("wait", "test", usage=usage))
        metrics.counts.update(moves=2, frames=120)
        summary = metrics.summary(2)
        self.assertEqual(summary["cost_known_requests"], 2)
        self.assertEqual(summary["cost_missing_received_requests"], 3)
        self.assertEqual(summary["known_cost"], 0.1)
        self.assertEqual(summary["decisions_per_second"], 2.5)
        self.assertEqual(summary["moves_per_second"], 1)
        self.assertEqual(summary["effective_fps"], 60)
        combined = Metrics()
        combined.merge(metrics)
        self.assertEqual(combined.summary(2), summary)

    def test_stuck_window_requires_directional_attempts(self):
        for action, expected in ((Action.NOOP, False), (Action.JUMP, False), (Action.RIGHT, True)):
            history = ControlHistory(40)
            for _ in range(119):
                history.step(action, 40)
            self.assertFalse(history.context("realtime")["stuck"])
            history.step(action, 40)
            self.assertEqual(history.context("realtime")["stuck"], expected)
        history.step(Action.RIGHT, 43)
        self.assertFalse(history.context("realtime")["stuck"])

    def test_stuck_coordinates_unknown_and_history_bounded(self):
        history = ControlHistory(None)
        self.assertIsNone(history.context("realtime")["stuck"])
        for index in range(9):
            history.record(index, "walk_right", 16, 40, 42)
        moves = history.context("realtime")["recent_moves"]
        self.assertEqual(len(moves), 8)
        self.assertEqual(moves[0], {"index": 1, "move": "walk_right", "frames": 16, "delta_x": 2})
        for _ in range(121):
            history.step(Action.RIGHT, 40)
        self.assertTrue(history.context("realtime")["stuck"])
        history.step(Action.RIGHT, None)
        self.assertIsNone(history.context("realtime")["stuck"])

    def test_adapter_realtime_prompt_and_stuck_warning(self):
        control = ControlHistory(40)
        for _ in range(120):
            control.step(Action.RIGHT, 40)
        context = {**control.context("realtime"), "current_move": "run_right", "game_fps": 30,
            "recent_latency_seconds": 0.29}
        for index in range(5):
            control.record(index, "run_right", 16, 40, 40)
        context.update(control.context("realtime"), move_committed=False, move_finished=True,
            move_remaining_frames=0, tail_action="right_run")
        payload = Model("key", 10).build_request(observation(), b"png", frames=120,
            previous_move="run_right", control_context=context).payload
        instructions = payload["questions"]["next_action"]["instructions"]
        self.assertIn("30 FPS", instructions)
        self.assertIn("asked again as soon as your move starts", instructions)
        self.assertIn("Jumps are never cut short", instructions)
        self.assertNotIn("paused", instructions)
        state = json.loads(payload["state"][0]["text"])
        self.assertEqual(state["move"], {"current": "run_right", "phase": "ended", "ends": "ended",
            "then": "holds right+B", "your_move_starts_in_frames": 9})
        self.assertIn("continue plans nothing", instructions)
        self.assertEqual(state["recent_moves"], [{"move": "run_right", "delta_x": 0}] * 3)
        self.assertIn("change strategy", state["warnings"][0])
        self.assertIn("continue", payload["questions"]["next_action"]["criteria"])

    def test_adapter_paused_prompt(self):
        payload = Model("key", 10).build_request(observation(), b"png", frames=0).payload
        instructions = payload["questions"]["next_action"]["instructions"]
        self.assertIn("paused while you decide", instructions)
        self.assertIn("continue repeats the previous move", instructions)
        self.assertNotIn("FPS", instructions)

    def test_cli_defaults_and_removed_options(self):
        config = parse_config([])
        self.assertEqual(config, Config())
        self.assertEqual((config.execution_mode, config.max_decision_frames, config.game_fps), ("realtime", 120, 60))
        self.assertTrue(config.scene)
        self.assertFalse(parse_config(["--no-scene"]).scene)
        self.assertEqual(parse_config(["--max-decision-frames", "90"]).max_decision_frames, 90)
        self.assertEqual(config.max_episode_seconds, 60)
        self.assertFalse(config.save_screenshots)
        self.assertEqual(parse_config(["--game-fps", "20"]).game_fps, 20)
        for flag in ("--max-decision-frames", "--max-episode-seconds"):
            for value in ("0", "-1", "abc"):
                with patch("sys.stderr", StringIO()), self.assertRaises(SystemExit):
                    parse_config([flag, value])
        for argv in (["--game-fps", "61"], ["--game-fps", "0"], ["--waiting-policy", "hold"],
                ["--max-in-flight", "1"], ["--decision-interval", "0.1"], ["--max-hold-frames", "120"],
                ["--frames-per-action", "6"], ["--max-decision-age", "2"]):
            with patch("sys.stderr", StringIO()), self.assertRaises(SystemExit):
                parse_config(argv)


if __name__ == "__main__":
    unittest.main()
