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
from app.openrouter import DecisionError, encode_png
from app.runner import run
from app.session import SessionLog
from test_decisions import SCENE, FakeClient, FakeGame, observation


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

    def __init__(self, clock, delay, choice, cancel_delay=0, cancel_returns=False):
        self.clock = clock
        self.started_at = clock()
        self.completed_at = None
        self.ready_at = clock() + delay
        self.choice = choice
        self.cancelled = False
        self.cancel_delay = cancel_delay
        self.cancel_returns = cancel_returns
        self.cancel_at = None

    def done(self):
        return self.clock() >= self.ready_at

    def cancel(self):
        if self.done() or self.cancel_at is not None:
            return
        self.cancel_at = self.clock()
        self.ready_at = self.clock() + self.cancel_delay
        self.cancelled = not self.cancel_returns

    def wait(self, timeout):
        if not self.done():
            self.clock.sleep(min(timeout, self.ready_at - self.clock()))
        return self.done()

    def result(self):
        if not self.done():
            raise AssertionError("Read a pending result")
        self.completed_at = self.ready_at
        if self.cancelled:
            raise asyncio.CancelledError()
        if isinstance(self.choice, Exception):
            raise self.choice
        return Decision(self.choice, "test/model", usage={"cost": 0.01})


class Preparation(Future):
    def result(self):
        super().result()
        return self.choice


class Worker:
    def __init__(self, clock, script, limit=1, setup_delay=0, setup_outcome="ready",
            cancel_delay=0, cancel_returns=False):
        self.clock = clock
        self.script = script
        self.limit = limit
        self.requests = []
        self.closed = False
        self.calls = []
        self.ready = Preparation(clock, setup_delay, setup_outcome)
        self.cancel_delay, self.cancel_returns = cancel_delay, cancel_returns

    def submit(self, payload):
        if not self.ready.done():
            raise AssertionError("Request submitted before preparation")
        if self.closed or sum(not request.done() for request in self.requests) >= self.limit:
            raise AssertionError("Too many concurrent requests or closed worker")
        self.calls.append((self.clock(), payload))
        delay, action = self.script.pop(0) if self.script else (10, "walk_right")
        self.requests.append(Future(self.clock, delay, action, self.cancel_delay, self.cancel_returns))
        return self.requests[-1]

    def close(self):
        self.closed = True
        for request in [self.ready, *self.requests]:
            if not request.done():
                request.cancel()
                request.wait(max(0, request.ready_at - self.clock()))
                request.completed_at = request.ready_at


class TimedGame(FakeGame):
    def __init__(self, clock, limit=100, **kwargs):
        super().__init__(limit, **kwargs)
        self.clock = clock
        self.step_times = []
        self.step_delay = 0.0
        self.reset_times = []

    def reset(self, seed):
        self.reset_times.append(self.clock())
        return super().reset(seed)

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
    def invoke(self, *, script=(), config=None, game=None, clock=None, window=None, preparation_delay=0,
            decision_logging_delay=0, setup_delay=0, setup_outcome="ready", cancel_delay=0, cancel_returns=False):
        config = config or Config(control_mode="moves", headless=True, max_frames=12)
        clock = clock or Clock()
        game = game or TimedGame(clock, config.max_frames)
        workers = []
        script = list(script)
        class Client(Model):
            def build_request(self, *args, **kwargs):
                clock.now += preparation_delay
                return super().build_request(*args, **kwargs)
        client = Client("secret-test", 10)
        def worker_factory(client, connections=1, timeout=None):
            worker = Worker(clock, script, connections, setup_delay, setup_outcome, cancel_delay, cancel_returns)
            workers.append(worker)
            return worker
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            stack.enter_context(patch("app.model_runner.perf_counter", clock))
            stack.enter_context(patch("app.model_runner.sleep", clock.sleep))
            stack.enter_context(patch("app.model_runner.DecisionWorker", side_effect=worker_factory))
            stack.enter_context(patch("app.runner.openrouter_key", return_value="secret-test"))
            stack.enter_context(patch("app.models.load_model", return_value=client))
            stack.enter_context(patch("app.runner.MarioGame", return_value=game))
            timeline = []
            class Log(SessionLog):
                def event(self, kind, **data):
                    super().event(kind, **data)
                    timeline.append({"event": kind, **data})
                    if kind == "decision":
                        clock.now += decision_logging_delay
                def frame(self, **data):
                    super().frame(**data)
                    timeline.append({"event": "frame", **data})
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
            frames = [json.loads(line) for line in (session / "frames.jsonl").read_text().splitlines()]
            self.assertFalse(any(e["event"] == "frame" for e in events))
            self.assertEqual(len(events) + len(frames), len(timeline))
            events = timeline
            persisted = json.loads((session / "config.json").read_text())
            pictures = list((session / "screenshots").glob("*.png"))
            return summary, events, workers, game, clock, persisted, len(pictures), caught

    @staticmethod
    def kinds(events, kind):
        return [event for event in events if event["event"] == kind]

    def test_setup_precedes_reset_and_is_accounted_separately(self):
        for outcome in ("ready", "failed", "timeout"):
            with self.subTest(outcome=outcome):
                summary, events, _, game, _, _, _, caught = self.invoke(
                    script=[(0.005, "walk_right")], config=Config(control_mode="moves", headless=True, max_frames=5),
                    setup_delay=0.45, setup_outcome=outcome)
                self.assertIsNone(caught)
                setup = summary["worker_preparations"][0]
                self.assertEqual(setup["outcome"], outcome)
                self.assertAlmostEqual(setup["seconds"], 0.45)
                self.assertGreaterEqual(game.reset_times[0], setup["ended_at"])
                self.assertEqual(summary["episodes"][0]["started_at"], game.reset_times[0])
                first = next(e for e in events if e["event"] == "frame" and e["source"] == "move")
                self.assertAlmostEqual(summary["controller_to_first_frame_seconds"], first["observation_at"] - 100)
                self.assertGreater(summary["controller_to_first_frame_seconds"], 0.45)
                self.assertLess(summary["wall_seconds"], 0.1)

    def test_closing_during_setup_cancels_without_reset(self):
        class ClosingWindow(CaptionWindow):
            def poll(self):
                self.open = False
        summary, events, workers, game, _, _, _, caught = self.invoke(
            config=Config(control_mode="moves", max_frames=5), window=ClosingWindow(), setup_delay=10)
        self.assertIsNone(caught)
        self.assertEqual((game.reset_times, game.steps, summary["episodes"]), ([], [], []))
        self.assertTrue(workers[0].closed)
        self.assertEqual(summary["worker_preparations"][0]["outcome"], "cancelled")
        self.assertIsNone(summary["controller_to_first_frame_seconds"])

    def test_response_between_frames_is_received_early_and_applied_on_tick(self):
        for fps in (30, 60):
            with self.subTest(fps=fps):
                summary, events, _, game, _, _, _, caught = self.invoke(
                    script=[(0.005, "walk_right")] * 20,
                    config=Config(control_mode="moves", headless=True, max_frames=10, game_fps=fps))
                self.assertIsNone(caught)
                response = self.kinds(events, "decision")[0]
                start = self.kinds(events, "move_start")[0]
                self.assertAlmostEqual(response["acquired_at"], response["response_at"])
                self.assertLess(response["acquired_at"], start["started_at"])
                self.assertAlmostEqual(start["started_at"], game.step_times[0] + 1 / fps)
                self.assertEqual(summary["timings"]["polling_seconds"]["median"], 0)
                self.assertTrue(all(b - a >= 1 / fps - 1e-10 for a, b in zip(game.step_times, game.step_times[1:])))

    def test_immediate_responses_never_burst_on_the_same_frame(self):
        for fps in (30, 60):
            summary, events, _, game, _, _, _, caught = self.invoke(
                script=[(0, "walk_right")] * 30, config=Config(control_mode="moves", headless=True, max_frames=12, game_fps=fps))
            self.assertIsNone(caught)
            frames = [r["frames"] for r in self.kinds(events, "request")]
            self.assertEqual(frames, [0, *range(2, 12)])
            self.assertTrue(all(e["frames_executed"] >= 1 for e in self.kinds(events, "move_end")))
            self.assertTrue(all(b - a >= 1 / fps - 1e-10 for a, b in zip(game.step_times, game.step_times[1:])))

    def test_response_during_step_is_received_after_step_without_catchup(self):
        clock = Clock()
        game = TimedGame(clock, 8)
        game.step_delay = 0.04
        summary, events, _, _, _, _, _, caught = self.invoke(clock=clock, game=game,
            script=[(0.005, "walk_right")] * 20, config=Config(control_mode="moves", headless=True, max_frames=8))
        self.assertIsNone(caught)
        response = self.kinds(events, "decision")[0]
        self.assertAlmostEqual(response["polling_seconds"], 0.035)
        self.assertAlmostEqual(response["acquired_at"], game.step_times[0] + game.step_delay)
        self.assertTrue(all(b - a >= game.step_delay - 1e-10 for a, b in zip(game.step_times, game.step_times[1:])))

    def test_response_forecast_uses_observed_frames_including_stale_replies(self):
        summary, events, _, _, _, _, _, caught = self.invoke(
            script=[(0.005, "walk_right"), (0.1, "run_right"), (0.005, "walk_right")],
            config=Config(control_mode="moves", headless=True, max_frames=15, max_decision_frames=2))
        self.assertIsNone(caught)
        requests = self.kinds(events, "request")
        self.assertIsNone(requests[0]["context"]["move"]["response_in_frames"])
        self.assertEqual(requests[1]["context"]["move"]["response_in_frames"], 1)
        discarded = self.kinds(events, "request_discarded")
        stale = next(e for e in discarded if e["reason"] == "stale")
        self.assertEqual(requests[2]["context"]["move"]["response_in_frames"],
            round((1 + stale["observation_age_frames"]) / 2))

    def test_response_forecast_keeps_only_five_samples(self):
        from statistics import median
        summary, events, _, _, _, _, _, caught = self.invoke(
            script=[(delay, "walk_right") for delay in (0.4, 0.005, 0.06, 0.1, 0.005, 0.02, 0.2)],
            config=Config(control_mode="moves", headless=True, max_frames=100))
        self.assertIsNone(caught)
        requests = {e["index"]: e for e in self.kinds(events, "request")}
        frames = 0
        recent = []
        for event in events:
            if event["event"] == "frame":
                frames = event["frames"]
            elif event["event"] == "decision":
                recent.append(frames - requests[event["index"]]["frames"])
            elif event["event"] == "request":
                expected = round(median(recent[-5:])) if recent else None
                self.assertEqual(event["context"]["move"]["response_in_frames"], expected)
        self.assertGreaterEqual(len(recent), 7)

    def test_received_choice_is_discarded_if_episode_ends_before_application(self):
        summary, events, _, _, _, _, _, caught = self.invoke(script=[(0.005, "walk_right")],
            config=Config(control_mode="moves", headless=True, max_episode_seconds=0.01))
        self.assertIsNone(caught)
        self.assertEqual((summary["moves"], summary["discarded_responses"]), (0, 1))
        self.assertEqual(self.kinds(events, "request_discarded")[0]["reason"], "wall_limit")


    def test_one_request_at_a_time_after_first_move_frame(self):
        summary, events, workers, game, _, _, _, caught = self.invoke(
            script=[(0.05, "walk_right"), (0.05, "run_right")], config=Config(control_mode="moves", headless=True, max_frames=20))
        self.assertIsNone(caught)
        self.assertEqual(len(workers), 1)
        self.assertEqual(workers[0].limit, 1)  # The fake worker refuses a second request in flight.
        steps = runs(game.steps)
        self.assertEqual([action for action, _ in steps], [Action.NOOP, Action.RIGHT, Action.RIGHT_RUN])
        starts, requests = self.kinds(events, "move_start"), self.kinds(events, "request")
        # The clock's step is instantaneous here, but the observed frame must have advanced.
        for start, request in zip(starts, requests[1:]):
            frame = next(e for e in self.kinds(events, "frame") if e["index"] == start["index"])
            self.assertEqual(request["frames"], frame["frames"])
            self.assertEqual(request["observation_at"], frame["observation_at"])
        order = [event["event"] for event in events if event["event"] in ("request", "decision")]
        self.assertEqual(order, ["request", "decision"] * 2 + ["request"])
        self.assertEqual(self.kinds(events, "move_end")[0]["outcome"], "replaced")
        self.assertEqual((summary["requests"], summary["decisions"], summary["moves"]), (3, 2, 2))
        self.assertEqual(summary["waiting_frames"], steps[0][1])
        self.assertEqual(summary["cancelled_requests"], 1)


    def test_landing_estimate_reaches_the_model_only_with_the_scene(self):
        class SceneJumpGame(JumpGame):
            def reset(self, seed):
                obs = super().reset(seed)
                obs.info["scene"] = SCENE  # Mario at 1.5 px/frame: high jumps land after 48 frames
                return obs
            def step(self, action, duration):
                result = super().step(action, duration)
                result.observation.info["scene"] = SCENE
                return result
        for scene in (True, False):
            with self.subTest(scene=scene):
                clock = Clock()
                _, events, _, _, _, _, _, caught = self.invoke(clock=clock, game=SceneJumpGame(clock, 30),
                    script=[(0.005, "high_jump_up"), (0.05, "continue")],
                    config=Config(control_mode="moves", headless=True, max_frames=30, scene=scene))
                self.assertIsNone(caught)
                requests = self.kinds(events, "request")
                landings = [request["context"]["move"].get("landing") for request in requests[:3]]
                if not scene:
                    self.assertEqual(landings, [None] * 3)
                    continue
                # The first follow-up already includes one executed frame of the jump.
                pressed = requests[1]["frames"]
                left = 47 - (requests[2]["frames"] - pressed)
                self.assertEqual(landings, [None, {"in_frames": 47, "travel_px": 70},
                    {"in_frames": left, "travel_px": round(1.5 * left)}])
                self.assertLess(left, 48)


    def test_stale_response_is_discarded_and_asked_again(self):
        summary, events, _, game, _, _, _, caught = self.invoke(
            script=[(0.8, "walk_right"), (0.05, "run_right")],
            config=Config(control_mode="moves", headless=True, max_frames=80, max_decision_frames=30))
        self.assertIsNone(caught)
        self.assertEqual([action for action, _ in runs(game.steps)], [Action.NOOP, Action.RIGHT_RUN, Action.NOOP])
        discarded = self.kinds(events, "request_discarded")
        self.assertEqual((discarded[0]["index"], discarded[0]["reason"]), (1, "stale"))
        self.assertGreater(discarded[0]["observation_age_frames"], discarded[0]["max_decision_frames"])
        self.assertEqual((summary["stale_responses"], summary["moves"], summary["requests"]), (1, 1, 3))

    def test_paused_stops_game_and_asks_when_move_ends(self):
        summary, events, workers, game, _, persisted, _, caught = self.invoke(
            script=[(0.3, "walk_right"), (0.3, "wait")], config=Config(control_mode="moves", headless=True, max_frames=30, execution_mode="paused"))
        self.assertIsNone(caught)
        self.assertTrue(persisted["game_paused_during_request"])
        self.assertEqual(runs(game.steps), [(Action.RIGHT, 16), (Action.NOOP, 10), (Action.RIGHT, 4)])
        self.assertEqual(summary["requests"], 3)
        # No frame between a request and its decision: the game waits for the model.
        waiting = False
        for event in events:
            waiting = event["event"] == "request" or (waiting and event["event"] != "decision")
            self.assertFalse(waiting and event["event"] == "frame")
        self.assertEqual(summary["waiting_frames"], 0)


    def test_staleness_counts_game_frames(self):
        # 2.7 s is 81 frames at 30 FPS (accepted) but 162 frames at 60 FPS (discarded).
        for fps, stale in ((30, 0), (60, 1)):
            with self.subTest(fps=fps):
                summary, events, _, _, _, _, _, caught = self.invoke(script=[(2.7, "walk_right")],
                    config=Config(control_mode="moves", headless=True, max_frames=200, game_fps=fps, max_episode_seconds=20))
                self.assertIsNone(caught)
                self.assertEqual((summary["stale_responses"], summary["moves"]), (stale, 1 - stale))

    def test_transient_error_is_retried_once_with_current_observation(self):
        transient = lambda: DecisionError("OpenRouter: errore HTTP 504", transient=True)
        summary, events, _, game, _, _, _, caught = self.invoke(
            script=[(0.05, transient()), (0.05, "walk_right"), (0.05, transient()), (0.05, "run_right")],
            config=Config(control_mode="moves", headless=True, max_frames=60))
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
            script=[(0.05, transient()), (0.05, transient())], config=Config(control_mode="moves", headless=True, max_frames=60))
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
                    config=Config(control_mode="moves", headless=True, max_frames=10, scene=enabled))
                self.assertIsNone(caught)
                self.assertEqual(persisted["scene"], enabled)
                state = self.kinds(events, "request")[1]["context"]
                self.assertEqual("nearby" in state, enabled)
                self.assertEqual("jump_reach_px" in state["mario"], enabled)

    def test_slow_provider_is_flagged(self):
        for delay, slow in ((0.8, True), (0.05, False)):
            with self.subTest(delay=delay):
                summary, _, _, _, clock, _, _, caught = self.invoke(
                    script=[(delay, "walk_right")] * 4, config=Config(control_mode="moves", headless=True, max_frames=150))
                self.assertIsNone(caught)
                self.assertEqual(summary["episodes"][0]["slow_provider"], slow)
                self.assertEqual("provider lento" in clock.output.getvalue(), slow)

    def test_error_stops_once_without_retry(self):
        summary, events, workers, game, _, _, _, caught = self.invoke(
            script=[(0.05, DecisionError("simulated failure"))], config=Config(control_mode="moves", headless=True, max_frames=60))
        self.assertIsInstance(caught, DecisionError)
        self.assertEqual((summary["status"], summary["errors"], summary["requests"]), ("error", 1, 1))
        self.assertEqual(len(self.kinds(events, "error")), 1)
        self.assertTrue(workers[0].closed)


    def test_wall_limit_cancels_request_in_flight(self):
        summary, events, _, _, _, _, _, caught = self.invoke(
            script=[(0.05, "walk_right")], config=Config(control_mode="moves", headless=True, max_episode_seconds=0.2))
        self.assertIsNone(caught)
        self.assertEqual(summary["episodes"][0]["reason"], "wall_limit")
        self.assertEqual(summary["cancelled_requests"], 1)
        self.assertEqual(self.kinds(events, "request_cancelled")[0]["reason"], "wall_limit")
        self.assertEqual(self.kinds(events, "move_end")[0]["outcome"], "interrupted")

    def test_session_files_and_screenshots(self):
        summary, events, _, _, _, persisted, pictures, caught = self.invoke(
            script=[(0.05, "walk_right")], config=Config(control_mode="moves", headless=True, max_frames=10, save_screenshots=True))
        self.assertIsNone(caught)
        self.assertEqual((summary["results_version"], persisted["results_version"]), (6, 6))
        self.assertEqual(persisted["protocol"], "openrouter-choice-scene-v5")
        self.assertEqual(persisted["prompt_revision"], 5)
        self.assertTrue(persisted["scene"])
        self.assertEqual(persisted["moves"]["high_jump_right"][0],
            {"action": "right_run_jump", "frames": HIGH_HOLD, "until_landed": False})
        self.assertEqual(pictures, summary["requests"])
        self.assertEqual([event["screenshot"] for event in self.kinds(events, "request")],
            ["screenshots/000001.png", "screenshots/000002.png"])
        state = self.kinds(events, "request")[1]["context"]
        self.assertEqual(state["move"], {"current": "walk_right", "phase": "running", "ends": "in 15 frames",
            "then": "no buttons", "response_in_frames": 3, "frames_executed": 1,
            "starting": False})
        self.assertEqual(state["recent_moves"], [])

    def test_caption_shows_move_and_source(self):
        window = CaptionWindow()
        _, _, _, _, _, _, _, caught = self.invoke(
            script=[(0.05, "walk_right")], config=Config(control_mode="moves", max_frames=10), window=window)
        self.assertIsNone(caught)
        self.assertIn("- (waiting)", window.captions[0])
        self.assertIn("walk_right (move)", window.captions[-1])

    def test_game_fps_paces_realtime(self):
        summary, _, _, game, _, persisted, _, caught = self.invoke(
            config=Config(control_mode="moves", headless=True, max_frames=5, game_fps=30))
        self.assertIsNone(caught)
        self.assertEqual(persisted["game_fps"], 30)
        self.assertTrue(all(b - a >= 1 / 30 - 1e-10 for a, b in zip(game.step_times, game.step_times[1:])))

    def test_real_backend_with_simulated_model(self):
        with tempfile.TemporaryDirectory() as directory:
            factory = lambda config: SessionLog(config, root=directory)
            with patch("app.runner.openrouter_key", return_value="test-key"), \
                 patch("app.models.load_model", return_value=FakeClient()), \
                 patch("app.session.SessionLog", side_effect=factory), patch("sys.stdout", StringIO()):
                run(Config(control_mode="moves", headless=True, max_frames=12))
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
                run(Config(control_mode="moves", headless=True, max_frames=150))
            session = next(Path(directory).iterdir())
            summary = json.loads((session / "summary.json").read_text())
            events = [json.loads(line) for name in ("events.jsonl", "frames.jsonl")
                for line in (session / name).read_text().splitlines()]
        self.assertEqual((summary["status"], summary["stale_responses"], summary["errors"]), ("finished", 0, 0))
        self.assertGreater(summary["x_pos"], summary["initial_x_pos"])
        self.assertEqual(summary["requests"], summary["decisions"] + summary["cancelled_requests"])
        grounds = [event["on_ground"] for event in events if event["event"] == "frame"]
        self.assertIn(False, grounds)
        self.assertIn(True, grounds)
        jumps = [event for event in events if event["event"] == "move_start" and event["move"] == "high_jump_right"]
        self.assertTrue(jumps)
        executions = [event for event in events if event["event"] == "frame" and event["source"] != "release"]
        # Every non-jump replacement releases A on its first actual frame.
        for start in self.kinds(events, "move_start"):
            if start["move"] == "run_right":
                following = [e for e in executions if e["index"] == start["index"]]
                if following:
                    self.assertEqual(following[0]["action"], "right_run")

    def test_cycle_observes_the_first_effect_before_requesting_again(self):
        for delay in (0, 0.005, 0.25):
            for fps in (30, 60):
                clock = Clock()
                game = TimedGame(clock, 70)
                game.step_delay = 0.002
                summary, events, workers, _, _, _, _, caught = self.invoke(clock=clock, game=game,
                    script=[(delay, "walk_right"), (delay, "walk_left")],
                    config=Config(control_mode="moves", headless=True, max_frames=70, game_fps=fps))
                self.assertIsNone(caught)
                for start in self.kinds(events, "execution_start"):
                    first = next(e for e in self.kinds(events, "frame") if e["index"] == start["index"])
                    request = next(e for e in self.kinds(events, "request") if e["index"] == start["index"] + 1)
                    self.assertEqual(request["frames"], first["frames"])
                    self.assertEqual(request["observation_at"], first["observation_at"])
                    self.assertGreater(request["submitted_at"], start["at"])
                    self.assertEqual(request["context"]["progress"]["x"], first["x_pos"])
                    self.assertEqual(request["context"]["move"]["frames_executed"], 1)
                    self.assertFalse(request["context"]["move"]["starting"])
                self.assertTrue(all(b - a >= 1/fps - 1e-10
                    for a, b in zip(game.step_times, game.step_times[1:])))

    def test_continue_owns_frames_without_restarting_and_can_expire(self):
        summary, events, _, game, _, _, _, caught = self.invoke(
            script=[(0.005, "walk_right"), (0.05, "continue"), (0.5, "continue")],
            config=Config(control_mode="moves", headless=True, max_frames=60))
        self.assertIsNone(caught)
        self.assertEqual((summary["moves"], summary["continues"], summary["not_applicable_decisions"]), (1, 2, 1))
        self.assertEqual(sum(n for action, n in game.steps if action == Action.RIGHT), 16)
        requests = self.kinds(events, "request")
        self.assertNotIn("continue", requests[0]["questions"]["next_action"]["criteria"])
        self.assertIn("continue", requests[1]["questions"]["next_action"]["criteria"])
        self.assertNotIn("continue", requests[3]["questions"]["next_action"]["criteria"])
        intervals = self.kinds(events, "execution")
        self.assertEqual([e["index"] for e in intervals], [1, 2, 3])
        self.assertEqual([e["applicable"] for e in intervals], [True, True, False])
        frames = self.kinds(events, "frame")
        for interval in intervals:
            owned = [e for e in frames if e["index"] == interval["index"]]
            self.assertEqual(sum(e["frames_executed"] for e in owned), interval["frames_executed"])
            self.assertEqual(interval["move_frames"] + interval["waiting_frames"], interval["frames_executed"])
            self.assertEqual(owned[0]["observation_at"], interval["first_frame_at"])
            self.assertEqual(owned[-1]["observation_at"], interval["last_frame_at"])
        self.assertEqual(intervals[1]["move_end"]["outcome"], "completed")
        self.assertEqual(intervals[2]["move_frames"], 0)

    def test_unoffered_continue_is_invalid_in_both_modes(self):
        for mode in ("realtime", "paused"):
            summary, events, _, _, _, _, _, caught = self.invoke(script=[(0.005, "continue")],
                config=Config(control_mode="moves", headless=True, max_frames=10, execution_mode=mode))
            self.assertIsInstance(caught, DecisionError)
            self.assertEqual(summary["status"], "error")
            self.assertEqual(summary["moves"], 0)

    def test_jump_and_double_jump_are_replaced_in_midair(self):
        for first in ("high_jump_right", "double_jump_right"):
            clock = Clock()
            summary, events, _, _, _, _, _, caught = self.invoke(clock=clock, game=JumpGame(clock, 40),
                script=[(0.005, first), (0.05, "walk_left"), (0.05, "high_jump_up")],
                config=Config(control_mode="moves", headless=True, max_frames=40))
            self.assertIsNone(caught)
            starts = self.kinds(events, "move_start")
            self.assertEqual([e["index"] for e in starts], [1, 2, 3])
            frames = self.kinds(events, "frame")
            left = next(e for e in frames if e["index"] == 2)
            self.assertFalse(left["on_ground"])
            self.assertEqual(left["action"], "left")
            self.assertLess(starts[2]["observation_age_frames"], 10)
            self.assertEqual(self.kinds(events, "move_deferred"), [])
            self.assertEqual(self.kinds(events, "request_superseded"), [])
            request = next(e for e in self.kinds(events, "request") if e["index"] == 3)
            self.assertNotIn("landing", request["context"]["move"])

    def test_release_frame_precedes_next_observation(self):
        clock = Clock()
        _, events, _, _, _, _, _, caught = self.invoke(clock=clock, game=JumpGame(clock, 20),
            script=[(0.005, "high_jump_right"), (0.005, "high_jump_left")],
            config=Config(control_mode="moves", headless=True, max_frames=20))
        self.assertIsNone(caught)
        first = next(e for e in self.kinds(events, "frame") if e["index"] == 2)
        request = self.kinds(events, "request")[2]
        self.assertEqual(first["source"], "release")
        self.assertEqual(request["frames"], first["frames"])

    def test_fatal_error_flushes_partial_execution_and_frames(self):
        summary, events, _, _, _, _, _, caught = self.invoke(
            script=[(0.005, "walk_right"), (0.05, DecisionError("invalid"))],
            config=Config(control_mode="moves", headless=True, max_frames=60))
        self.assertIsInstance(caught, DecisionError)
        interval = self.kinds(events, "execution")[0]
        self.assertEqual(interval["outcome"], "error")
        self.assertEqual(interval["move_end"]["outcome"], "interrupted")
        self.assertEqual(interval["frames_executed"],
            sum(e["frames_executed"] for e in self.kinds(events, "frame") if e["index"] == 1))
        self.assertEqual(interval["ended_at"], summary["episodes"][0]["ended_at"])

    def test_reset_closes_intervals_and_cancels_old_request(self):
        summary, events, workers, _, _, _, _, caught = self.invoke(
            script=[(0.005, "walk_right"), (10, "walk_left"), (0.005, "wait")],
            config=Config(control_mode="moves", headless=True, max_frames=8, episodes=2))
        self.assertIsNone(caught)
        self.assertTrue(all(w.closed for w in workers))
        self.assertEqual(len(summary["episodes"]), 2)
        self.assertEqual([e["choice"] for e in self.kinds(events, "execution")], ["walk_right", "wait"])
        self.assertEqual([e["episode"] for e in self.kinds(events, "execution")], [1, 2])


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
            "recent_latency_seconds": 0.29, "recent_response_frames": 9}
        for index in range(5):
            control.record(index, "run_right", 16, 40, 40)
        context.update(control.context("realtime"), move_finished=True,
            move_remaining_frames=0, tail_action="noop")
        payload = Model("key", 10).build_request(observation(), encode_png(observation()), frames=120,
            previous_move="run_right", control_context=context).payload
        instructions = payload["questions"]["next_action"]["instructions"]
        self.assertIn("30 FPS", instructions)
        self.assertIn("one frame", instructions)
        self.assertIn("not queued for landing", instructions)
        self.assertNotIn("paused", instructions)
        state = json.loads(payload["state"][0]["text"])
        self.assertEqual(state["move"], {"current": "run_right", "phase": "ended", "ends": "ended",
            "then": "no buttons", "response_in_frames": 9, "frames_executed": 0,
            "starting": False})
        self.assertNotIn("continue", payload["questions"]["next_action"]["criteria"])
        self.assertEqual(state["recent_moves"], [{"move": "run_right", "delta_x": 0}] * 3)
        self.assertEqual(state["warnings"], ["No horizontal progress despite directional input."])
        self.assertNotIn("continue", payload["questions"]["next_action"]["criteria"])

    def test_adapter_paused_prompt(self):
        payload = Model("key", 10).build_request(observation(), encode_png(observation()), frames=0).payload
        instructions = payload["questions"]["next_action"]["instructions"]
        self.assertIn("paused while you decide", instructions)
        self.assertNotIn("continue", payload["questions"]["next_action"]["criteria"])
        self.assertNotIn("FPS", instructions)

    @patch.dict("app.config.os.environ", {"OPENROUTER_MODEL": Config().model})
    def test_cli_defaults_and_removed_options(self):
        config = parse_config([])
        self.assertEqual((config.execution_mode, config.max_decision_frames, config.game_fps), ("predictive", 120, 60))
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
