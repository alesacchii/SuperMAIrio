import asyncio
import base64
from concurrent.futures import CancelledError, Future
from dataclasses import asdict
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx
import numpy as np
from PIL import Image

from app.config import Config, DEFAULT_MODEL, openrouter_key, parse_config
from app.contracts import Action, Decision, Observation, StepResult
from app.models.gpt_luna import Model, build_payload
from app.moves import CHOICES
from app.openrouter import (DecisionError, DecisionRequestHandle, DecisionWorker, OpenRouterClient,
    encode_png, parse_decision)
from app.runner import main, run
from app.session import SessionLog


def observation(x=40):
    rgb = np.zeros((240, 256, 3), dtype=np.uint8)
    rgb[0, 0] = [255, 12, 34]
    return Observation(rgb, {"x_pos": x, "y_pos": 20, "life": 2, "time": 400, "status": "small"})


SCENE = {"mario": {"size": "small", "on_ground": True, "vertical": "none", "speed": 1.5, "screen_x": 40},
    "enemies": [{"type": "goomba", "dx": 64, "dy": 0, "moving": "left", "speed": -0.62}],
    "obstacle_ahead": {"type": "pipe", "dx": 96, "height_tiles": 2}, "pit_ahead": None,
    "blocks": [{"type": "question_block", "dx": 0, "dy": 48}], "items": [],
    "progress": {"x": 40, "flag_x": 3160, "percent": 1}}


def response(action="high_jump_right"):
    return {"model": DEFAULT_MODEL, "answers": {"next_action": {
        "type": "choice", "choice": action, "confidence": 0.8,
        "probabilities": {action: 1.0}}}, "id": "request-1", "provider": "OpenAI",
        "usage": {"input_tokens": 100, "output_tokens": 0, "cost": 0.00001}}


class ProtocolTests(unittest.TestCase):
    def test_response_estimate_is_not_inferred_from_latency_or_jump_duration(self):
        obs = observation()
        obs.info["scene"] = SCENE
        control = {"execution_mode": "realtime", "recent_latency_seconds": 0.25,
            "current_move": "high_jump_right", "move_finished": False,
            "move_remaining_frames": None, "tail_action": "right_run"}
        def state():
            return json.loads(build_payload(DEFAULT_MODEL, obs, b"png", frames=0,
                control_context=control)["state"][0]["text"])
        initial = state()
        self.assertIsNone(initial["move"]["response_in_frames"])
        self.assertNotIn("dx_at_response", initial["nearby"]["enemies"][0])
        self.assertIn("currently", initial["warnings"][0])
        control["recent_response_frames"] = 4
        forecast = state()
        self.assertEqual(forecast["move"]["response_in_frames"], 4)
        self.assertEqual(forecast["move"]["ends"], "at landing")
        self.assertEqual(forecast["nearby"]["enemies"][0]["dx_at_response"], 56)
        self.assertIn("estimated at response receipt", forecast["warnings"][0])

    def test_prompt_describes_control_constraints_without_conflicting_guidance(self):
        payload = build_payload(DEFAULT_MODEL, observation(), b"png", frames=0,
            control_context={"execution_mode": "realtime"})
        question = payload["questions"]["next_action"]
        instructions = question["instructions"]
        for phrase in ("Harmful enemy contact", "landing on top defeats it", "does not stop Mario immediately",
                "one frame", "move.landing estimates", "all buttons are released", "Every new move replaces",
                "nearest enemy, wall or pit", "where Mario will land",
                "Steering opposite the current horizontal motion", "cannot rescue a fall", "not queued for landing"):
            self.assertIn(phrase, instructions)
        for obsolete in ("any enemy contact", "about one decision", "about three decisions",
                "your_move_starts_in_frames", "dx_at_move_start", "no further request", "landing time is not known",
                "A new move waits until the committed portion ends"):
            self.assertNotIn(obsolete, instructions)
        criteria = question["criteria"]
        self.assertNotIn("continue", criteria)
        self.assertIn("Interruptible at any point", criteria["double_jump_right"])

    def test_png_scene_state_and_all_choices(self):
        obs = observation()
        obs.info.update(scene=SCENE, time=400)
        payload = build_payload(DEFAULT_MODEL, obs, encode_png(obs), frames=12,
            previous_move="walk_right", previous_position=35)
        self.assertEqual(set(payload["questions"]["next_action"]["criteria"]), set(CHOICES) - {"continue"})
        self.assertIn("continue", CHOICES)
        self.assertEqual(payload["questions"]["next_action"]["type"], "choice")
        state = json.loads(payload["state"][0]["text"])
        self.assertEqual(set(state), {"mario", "progress", "nearby", "move", "recent_moves", "warnings"})
        self.assertEqual(state["warnings"], ["Attention: goomba close, dx 64 px currently."])
        self.assertEqual(state["mario"]["jump_reach_px"], {"short_jump": 48, "high_jump": 80})
        self.assertEqual(state["nearby"]["enemies"], SCENE["enemies"])
        self.assertEqual(state["nearby"]["obstacle_ahead"]["height_tiles"], 2)
        self.assertEqual(state["move"], {"current": None, "phase": "none", "response_in_frames": 0})
        instructions = payload["questions"]["next_action"]["instructions"]
        for topic in ("Goomba", "Koopa", "Pits", "Question blocks", "mushroom", "dx =", "nearby lists"):
            self.assertIn(topic, instructions)
        # Running has a cost the model must know: less time to react to what appears ahead.
        self.assertIn("Running, an enemy appearing at the right edge reaches Mario in about 35 frames", instructions)
        self.assertNotIn("faster", instructions)
        criteria = payload["questions"]["next_action"]["criteria"]
        self.assertIn("more time to react", criteria["walk_right"])
        self.assertIn("little time to react", criteria["run_right"])
        url = payload["state"][1]["image_url"]["url"]
        png = base64.b64decode(url.split(",", 1)[1])
        with Image.open(BytesIO(png)) as picture:
            self.assertEqual(picture.format, "PNG")
            np.testing.assert_array_equal(np.asarray(picture), obs.rgb)

    def test_realtime_predicts_distances_and_what_follows_the_move(self):
        obs = observation()
        obs.info.update(scene=SCENE)
        control = {"execution_mode": "realtime", "game_fps": 60, "recent_latency_seconds": 0.25, "recent_response_frames": 15,
            "current_move": "high_jump_right", "move_finished": False,
            "move_remaining_frames": None, "tail_action": "right_run"}
        state = json.loads(build_payload(DEFAULT_MODEL, obs, encode_png(obs), frames=0,
            control_context=control)["state"][0]["text"])
        # 15 frames: Mario at 1.5 px/frame closes 22.5 px on the pipe and 31.8 px on a goomba walking left.
        self.assertEqual(state["nearby"]["enemies"][0]["dx_at_response"], 32)
        self.assertEqual(state["nearby"]["obstacle_ahead"]["dx_at_response"], 74)
        self.assertNotIn("dx_at_response", state["nearby"]["blocks"][0])
        self.assertEqual(SCENE["enemies"][0]["dx"], 64)  # the observation is not modified
        self.assertEqual(state["move"], {"current": "high_jump_right", "phase": "running", "ends": "at landing",
            "then": "no buttons", "response_in_frames": 15, "frames_executed": 0,
            "starting": True})
        paused = json.loads(build_payload(DEFAULT_MODEL, obs, encode_png(obs), frames=0,
            control_context={**control, "execution_mode": "paused"})["state"][0]["text"])
        self.assertNotIn("dx_at_response", paused["nearby"]["enemies"][0])
        self.assertEqual(paused["move"]["response_in_frames"], 0)

    def test_landing_estimate_with_and_without_scene(self):
        control = {"execution_mode": "realtime", "current_move": "high_jump_right", "move_finished": False,
            "move_remaining_frames": None, "tail_action": "right_run", "landing_in_frames": 20}
        def state(obs, **changes):
            payload = build_payload(DEFAULT_MODEL, obs, b"png", frames=0, control_context={**control, **changes})
            return json.loads(payload["state"][0]["text"]), payload["questions"]["next_action"]["instructions"]
        obs = observation()
        obs.info["scene"] = SCENE
        scene_state, instructions = state(obs)
        self.assertEqual(scene_state["move"]["landing"], {"in_frames": 20, "travel_px": 30})  # 1.5 px/frame
        self.assertIn("move.landing estimates", instructions)
        self.assertEqual(state(observation())[0]["move"]["landing"], {"in_frames": 20})
        self.assertNotIn("landing", state(obs, landing_in_frames=None)[0]["move"])
        self.assertIn("move.landing estimates", state(obs, execution_mode="paused")[1])

    def test_attention_warning_only_for_close_enemies_on_marios_level(self):
        control = {"execution_mode": "realtime", "game_fps": 60, "recent_latency_seconds": 0.25, "recent_response_frames": 15}
        cases = (  # dx, dy, speed -> warned; Mario runs at 1.5 px/frame, the move starts in 15 frames
            ((80, 0, -0.62), True),   # 80 + (-0.62 - 1.5) * 15 = 48 px at move start
            ((150, 0, -0.62), False),  # still 118 px away
            ((-40, 0, -0.62), False),  # already behind
            ((60, 64, -0.62), False),  # on a higher platform
        )
        for (dx, dy, speed), warned in cases:
            with self.subTest(dx=dx, dy=dy):
                obs = observation()
                obs.info.update(scene={**SCENE, "enemies": [{"type": "goomba", "dx": dx, "dy": dy,
                    "moving": "left", "speed": speed}]})
                state = json.loads(build_payload(DEFAULT_MODEL, obs, encode_png(obs), frames=0,
                    control_context=control)["state"][0]["text"])
                warnings = state.get("warnings", [])
                self.assertEqual(bool(warnings), warned)
                for text in warnings:
                    self.assertIn("dx 48 px", text)
                    self.assertFalse(any(name in text for name in CHOICES))  # never suggests a move

    def test_without_scene_the_screenshot_is_the_only_perception(self):
        obs = Observation(observation().rgb, {"x_pos": 0, "time": 80})
        payload = build_payload(DEFAULT_MODEL, obs, encode_png(obs), frames=0, previous_position=0)
        state = json.loads(payload["state"][0]["text"])
        self.assertNotIn("nearby", state)
        self.assertNotIn("jump_reach_px", state["mario"])
        self.assertEqual(state["progress"], {"x": 0})
        self.assertEqual(state["mario"], {"size": "unknown", "on_ground": "unknown"})
        self.assertEqual(state["warnings"], ["Only 80 time units left."])
        instructions = payload["questions"]["next_action"]["instructions"]
        self.assertIn("from the screenshot", instructions)
        self.assertNotIn("nearby lists", instructions)

    def test_all_moves_and_optional_metadata(self):
        for move in CHOICES:
            self.assertEqual(parse_decision(response(move)).move, move)
        body = {"model": DEFAULT_MODEL, "answers": {"next_action": {"type": "choice", "choice": "continue"}}}
        self.assertIsNone(parse_decision(body).confidence)

    def test_invalid_responses(self):
        invalid = [None, [], {}, {"answers": {}}, response("fly"), response("right_jump")]
        refusal = response()
        refusal["answers"]["next_action"]["type"] = "refusal"
        invalid.append(refusal)
        unknown = response()
        unknown["answers"]["next_action"]["probabilities"] = {"right_jump": 1.0}
        listed = response()
        listed["answers"]["next_action"]["choice"] = ["wait"]
        invalid += [unknown, listed]
        for value in (-0.1, 1.1, True, float("nan"), "0.8"):
            body = response()
            body["answers"]["next_action"]["confidence"] = value
            invalid.append(body)
        for body in invalid:
            with self.subTest(body=body), self.assertRaises(DecisionError):
                parse_decision(body)

    @patch.dict("app.config.os.environ", {"OPENROUTER_MODEL": Config().model})
    def test_config_and_timeout_validation(self):
        self.assertEqual(parse_config([]).mode, "model")
        self.assertEqual(parse_config([]).model, DEFAULT_MODEL)
        self.assertEqual(parse_config(["--mode", "demo", "--headless"]).mode, "demo")
        for value in ("0", "-1", "nan", "inf", "abc"):
            with patch("sys.stderr", StringIO()), self.assertRaises(SystemExit):
                parse_config(["--request-timeout", value])
        with patch("sys.stderr", StringIO()), self.assertRaises(SystemExit):
            parse_config(["--mode", "manual", "--headless"])

    def test_env_overrides_dotenv_and_missing_key(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, ".env").write_text("OPENROUTER_API_KEY=from-file\n", encoding="utf-8")
            with patch("app.config.PROJECT_ROOT", Path(directory)), patch.dict(os.environ, {"OPENROUTER_API_KEY": "from-env"}):
                self.assertEqual(openrouter_key(), "from-env")
            with patch("app.config.PROJECT_ROOT", Path(directory)), patch.dict(os.environ, {}, clear=True):
                self.assertEqual(openrouter_key(), "from-file")
            with patch("app.config.PROJECT_ROOT", Path(directory)), patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
                with self.assertRaises(ValueError):
                    openrouter_key()

    def test_missing_key_prevents_emulator_and_logging(self):
        with patch("app.runner.openrouter_key", side_effect=ValueError("missing key")), \
             patch("app.runner.MarioGame") as game, patch("sys.stdout", StringIO()):
            self.assertEqual(main([]), 1)
        game.assert_not_called()


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_preparation_has_total_timeout_and_reports_outcome(self):
        async def slow(request):
            await asyncio.sleep(0.1)
            return httpx.Response(405)
        client = OpenRouterClient("secret", 0.01, transport=httpx.MockTransport(slow))
        try:
            self.assertEqual(await client.prepare(), "timeout")
        finally:
            await client.aclose()
        client = OpenRouterClient("secret", 1,
            transport=httpx.MockTransport(lambda request: httpx.Response(405)))
        try:
            self.assertEqual(await client.prepare(), "ready")
        finally:
            await client.aclose()

    async def test_request_endpoint_and_authorization(self):
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(200, json=response())
        client = OpenRouterClient("secret-test", 1, transport=httpx.MockTransport(handler))
        result = await client.decide(build_payload(DEFAULT_MODEL, observation(), b"png", frames=0))
        self.assertEqual(result.move, "high_jump_right")
        self.assertEqual(str(calls[0].url), "https://openrouter.ai/api/alpha/decisions")
        self.assertEqual(calls[0].headers["authorization"], "Bearer secret-test")

    async def test_choice_is_validated_against_this_request(self):
        for offered in (False, True):
            client = OpenRouterClient("secret", 1, transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=response("continue"))))
            context = {"execution_mode": "realtime", "current_move": "walk_right", "move_finished": not offered}
            payload = build_payload(DEFAULT_MODEL, observation(), b"png", frames=1, control_context=context)
            try:
                if offered:
                    self.assertEqual((await client.decide(payload)).move, "continue")
                else:
                    with self.assertRaises(DecisionError):
                        await client.decide(payload)
            finally:
                await client.aclose()

    async def test_http_failures_no_retry_or_secret(self):
        for status in (400, 401, 402, 429, 500):
            calls = []
            def handler(request):
                calls.append(request)
                return httpx.Response(status, json={"error": "secret-test"})
            client = OpenRouterClient("secret-test", 1, transport=httpx.MockTransport(handler))
            with self.assertRaises(DecisionError) as caught:
                await client.decide(build_payload(DEFAULT_MODEL, observation(), b"png", frames=0))
            self.assertEqual(len(calls), 1)
            self.assertNotIn("secret-test", str(caught.exception))
            # Only server errors are worth a second request from the runner.
            self.assertEqual(caught.exception.transient, status >= 500)

    async def test_total_deadline(self):
        async def handler(request):
            await asyncio.sleep(5)
            return httpx.Response(200, json=response())
        client = OpenRouterClient("secret", 0.02, transport=httpx.MockTransport(handler))
        with self.assertRaisesRegex(DecisionError, "timeout") as caught:
            await client.decide(build_payload(DEFAULT_MODEL, observation(), b"png", frames=0))
        self.assertTrue(caught.exception.transient)

    async def test_connection_reused_across_requests_and_closed(self):
        client = OpenRouterClient("secret-test", 1, transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response())))
        await client.decide(build_payload(DEFAULT_MODEL, observation(), b"png", frames=0))
        http = client._http
        await client.decide(build_payload(DEFAULT_MODEL, observation(), b"png", frames=0))
        self.assertIs(client._http, http)
        await client.aclose()
        self.assertIsNone(client._http)
        self.assertTrue(http.is_closed)

    async def test_prepare_opens_connections_and_ignores_failures(self):
        calls = []
        def handler(request):
            calls.append(request)
            raise httpx.ConnectError("offline", request=request)
        client = OpenRouterClient("secret-test", 1, transport=httpx.MockTransport(handler))
        await client.prepare(3)
        self.assertEqual([request.method for request in calls], ["HEAD"] * 3)
        self.assertNotIn("authorization", calls[0].headers)
        await client.aclose()
        calls.clear()
        await FakeClient().prepare(2)
        self.assertEqual(calls, [])

    async def test_connection_and_bad_json(self):
        def connection(request):
            raise httpx.ConnectError("secret", request=request)
        for handler in (connection, lambda request: httpx.Response(200, content="not-json")):
            client = OpenRouterClient("secret", 1, transport=httpx.MockTransport(handler))
            with self.assertRaises(DecisionError) as caught:
                await client.decide(build_payload(DEFAULT_MODEL, observation(), b"png", frames=0))
            self.assertNotIn("secret", str(caught.exception))


class FakeGame:
    def __init__(self, limit=7, *, completed=False, death=False):
        self.limit = limit
        self.completed = completed
        self.death = death
        self.frames = 0
        self.steps = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def reset(self, seed):
        self.frames = 0
        return observation()

    def step(self, action, duration):
        self.assert_main_thread = threading.current_thread() is threading.main_thread()
        count = min(duration, self.limit - self.frames)
        self.steps.append((action, count))
        self.frames += count
        obs = observation(40 + self.frames)
        done = self.frames == self.limit
        obs.info.update(flag_get=done and self.completed, death=done and self.death)
        return StepResult(obs, count, count, done and (self.completed or self.death), done and not (self.completed or self.death))


class FakeClient(Model):
    def __init__(self, *, wait=False, error=False):
        self.calls = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.cancelled = threading.Event()
        self.wait = wait
        self.error = error

    async def decide(self, payload):
        self.calls.append(payload)
        self.started.set()
        try:
            while self.wait and not self.release.is_set():
                await asyncio.sleep(0.005)
            if self.error:
                raise DecisionError("simulated failure")
            return Decision("walk_right", DEFAULT_MODEL)
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


class ModelRunnerTests(unittest.TestCase):
    def test_worker_cancel_waits_for_cleanup_and_can_reuse_client(self):
        cleaning, release = threading.Event(), threading.Event()
        class Client(FakeClient):
            async def decide(self, payload):
                if payload:
                    return Decision("walk_left", DEFAULT_MODEL)
                self.started.set()
                try:
                    await asyncio.sleep(60)
                finally:
                    cleaning.set()
                    while not release.is_set():
                        await asyncio.sleep(0.001)
        client = Client()
        worker = DecisionWorker(client)
        try:
            first = worker.submit({})
            self.assertTrue(client.started.wait(1))
            first.cancel()
            self.assertTrue(cleaning.wait(1))
            first.cancel()  # Must not interrupt the first cancellation's cleanup.
            self.assertFalse(first.wait(0.02))
            self.assertFalse(first.done())
            self.assertIsNone(first.completed_at)
            release.set()
            self.assertTrue(first.wait(1))
            with self.assertRaises(CancelledError):
                first.result()
            second = worker.submit({"next": True})
            self.assertTrue(second.wait(1))
            self.assertEqual(second.result().move, "walk_left")
            self.assertGreaterEqual(second.started_at, first.completed_at)
        finally:
            release.set()
            worker.close()

    def test_worker_preserves_response_returned_during_cancellation(self):
        class Client(FakeClient):
            async def decide(self, payload):
                self.started.set()
                try:
                    await asyncio.sleep(60)
                except asyncio.CancelledError:
                    return Decision("run_left", DEFAULT_MODEL, usage={"cost": 0.03})
        client = Client()
        worker = DecisionWorker(client)
        try:
            handle = worker.submit({})
            self.assertTrue(client.started.wait(1))
            handle.cancel()
            self.assertTrue(handle.wait(1))
            self.assertEqual(handle.result().usage, {"cost": 0.03})
            self.assertIsNotNone(handle.completed_at)
        finally:
            worker.close()

    def test_worker_close_waits_for_existing_cancellation_cleanup(self):
        cleaning, release, interrupted = threading.Event(), threading.Event(), threading.Event()
        class Client(FakeClient):
            async def decide(self, payload):
                self.started.set()
                try:
                    await asyncio.sleep(60)
                finally:
                    cleaning.set()
                    try:
                        while not release.is_set():
                            await asyncio.sleep(0.001)
                    except asyncio.CancelledError:
                        interrupted.set()
                        raise
        client = Client()
        worker = DecisionWorker(client)
        closer = threading.Thread(target=worker.close)
        try:
            handle = worker.submit({})
            self.assertTrue(client.started.wait(1))
            handle.cancel()
            self.assertTrue(cleaning.wait(1))
            closer.start()
            self.assertFalse(interrupted.wait(0.02))
            self.assertFalse(handle.done())
        finally:
            release.set()
            if closer.ident is not None:
                closer.join(1)
            else:
                worker.close()
        self.assertFalse(closer.is_alive())
        self.assertTrue(handle.done())

    def test_handle_wait_wakes_for_results_errors_and_cancellation(self):
        for outcome in ("success", "error", "cancel"):
            with self.subTest(outcome=outcome):
                handle = DecisionRequestHandle()
                future = Future()
                handle.bind(future)
                self.assertFalse(handle.wait(0))
                if outcome == "success":
                    future.set_result("ready")
                    expected = None
                elif outcome == "error":
                    future.set_exception(DecisionError("failed"))
                    expected = DecisionError
                else:
                    future.cancel()
                    expected = CancelledError
                self.assertTrue(handle.wait(0))
                if expected:
                    with self.assertRaises(expected):
                        handle.result()
                else:
                    self.assertEqual(handle.result(), "ready")

    def test_worker_preparation_is_bounded_and_precedes_direct_submission(self):
        class Client(FakeClient):
            async def prepare(self, connections=1):
                await asyncio.sleep(1)
            async def decide(self, payload):
                return await super().decide(payload)
        worker = DecisionWorker(Client(), timeout=0.01)
        try:
            handle = worker.submit({})
            self.assertTrue(handle.wait(1))
            self.assertEqual(worker.ready.result(), "timeout")
            self.assertGreaterEqual(handle.started_at, worker.ready.completed_at)
            self.assertEqual(handle.result().move, "walk_right")
        finally:
            worker.close()

    def test_worker_close_cancels_preparation_and_wakes_waiters(self):
        entered = threading.Event()
        cancelled = threading.Event()
        class Client(FakeClient):
            async def prepare(self, connections=1):
                entered.set()
                try:
                    await asyncio.sleep(60)
                finally:
                    cancelled.set()
        worker = DecisionWorker(Client(), timeout=60)
        try:
            self.assertTrue(entered.wait(1))
        finally:
            worker.close()
        self.assertTrue(cancelled.is_set())
        self.assertTrue(worker.ready.wait(0))
        with self.assertRaises(CancelledError):
            worker.ready.result()

    def test_cancelling_one_request_does_not_cancel_shared_preparation(self):
        entered = threading.Event()
        release = threading.Event()
        class Client(FakeClient):
            async def prepare(self, connections=1):
                entered.set()
                while not release.is_set():
                    await asyncio.sleep(0.001)
        worker = DecisionWorker(Client(), timeout=1)
        try:
            first = worker.submit({})
            second = worker.submit({})
            self.assertTrue(entered.wait(1))
            first.future.cancel()
            self.assertTrue(first.wait(0.1))
            release.set()
            self.assertTrue(second.wait(1))
            self.assertEqual(worker.ready.result(), "ready")
            self.assertEqual(second.result().move, "walk_right")
        finally:
            release.set()
            worker.close()

    def test_preparation_exception_is_nonfatal_and_recorded_without_details(self):
        class Client(FakeClient):
            async def prepare(self, connections=1):
                raise RuntimeError("secret-test")
        worker = DecisionWorker(Client(), timeout=1)
        try:
            self.assertTrue(worker.ready.wait(1))
            self.assertEqual(worker.ready.result(), "failed")
            handle = worker.submit({})
            self.assertTrue(handle.wait(1))
            self.assertEqual(handle.result().move, "walk_right")
        finally:
            worker.close()

    def invoke(self, config, game, client, directory, window=None):
        factory = lambda config: SessionLog(config, root=directory)
        with patch("app.runner.openrouter_key", return_value="secret-test"), \
             patch("app.runner.MarioGame", return_value=game), \
             patch("app.models.load_model", return_value=client), \
             patch("app.session.SessionLog", side_effect=factory), \
             patch.dict("sys.modules", {"app.viewer": SimpleNamespace(GameWindow=lambda: window)}), \
             patch("sys.stdout", StringIO()):
            run(config)

    def test_duration_terminal_conditions_and_session_trace(self):
        for completed, death in ((False, False), (True, False), (False, True)):
            with tempfile.TemporaryDirectory() as directory:
                game, client = FakeGame(completed=completed, death=death), FakeClient()
                self.invoke(Config(control_mode="moves", headless=True, execution_mode="paused", save_screenshots=True), game, client, directory)
                # walk_right lasts 16 frames: the episode ends during the first move.
                self.assertEqual(game.steps, [(Action.RIGHT, 1)] * 7)
                self.assertEqual(len(client.calls), 1)
                self.assertTrue(game.closed and game.assert_main_thread)
                session = next(Path(directory).iterdir())
                summary = json.loads((session / "summary.json").read_text())
                self.assertEqual(summary["status"], "finished")
                self.assertEqual((summary["decisions"], summary["moves"]), (1, 1))
                self.assertEqual(len(list((session / "screenshots").iterdir())), 1)
                trace = (session / "events.jsonl").read_text()
                self.assertNotIn("secret-test", trace)
                self.assertIn('"frames_executed": 1', (session / "frames.jsonl").read_text())

    def test_multiple_episodes_reset_history(self):
        with tempfile.TemporaryDirectory() as directory:
            game, client = FakeGame(limit=1), FakeClient()
            self.invoke(Config(control_mode="moves", headless=True, episodes=2, execution_mode="paused"), game, client, directory)
            self.assertEqual(len(client.calls), 2)
            for payload in client.calls:
                state = json.loads(payload["state"][0]["text"])
                self.assertEqual((state["recent_moves"], state["move"]["current"]), ([], None))

    def test_error_stops_and_writes_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            game, client = FakeGame(), FakeClient(error=True)
            with self.assertRaises(DecisionError):
                self.invoke(Config(control_mode="moves", headless=True, execution_mode="paused", save_screenshots=True), game, client, directory)
            self.assertEqual(len(client.calls), 1)
            self.assertEqual(game.steps, [])
            summary = json.loads(next(Path(directory).glob("*/summary.json")).read_text())
            self.assertEqual(summary["status"], "error")
            self.assertTrue(game.closed)

    def test_window_exit_cancels_request_without_advancing(self):
        game, client = FakeGame(), FakeClient(wait=True)
        class Window:
            open = True
            closed = False
            def poll(self):
                if client.started.is_set():
                    self.open = False
            def consume_reset(self):
                return False
            def show(self, *args):
                pass
            def close(self):
                self.closed = True
        window = Window()
        with tempfile.TemporaryDirectory() as directory:
            self.invoke(Config(control_mode="moves", execution_mode="paused"), game, client, directory, window)
            self.assertEqual(game.steps, [])
            self.assertTrue(window.closed and game.closed and client.cancelled.is_set())
            trace = next(Path(directory).glob("*/events.jsonl")).read_text()
            self.assertIn("request_cancelled", trace)
            self.assertNotIn('"event": "decision"', trace)

    def test_window_remains_responsive_until_request_finishes(self):
        game, client = FakeGame(limit=1), FakeClient(wait=True)
        class Window:
            open = True
            closed = False
            polls = 0
            def poll(self):
                if client.started.is_set() and not client.release.is_set():
                    self.polls += 1
                    if game.steps:
                        raise AssertionError("Game advanced during request")
                    if self.polls == 3:
                        client.release.set()
            def consume_reset(self):
                return False
            def show(self, *args):
                pass
            def close(self):
                self.closed = True
        window = Window()
        with tempfile.TemporaryDirectory() as directory:
            self.invoke(Config(control_mode="moves", execution_mode="paused"), game, client, directory, window)
        self.assertEqual(window.polls, 3)
        self.assertEqual(game.steps, [(Action.RIGHT, 1)])

    def test_worker_runs_concurrent_requests_and_close_cancels_all(self):
        client = FakeClient(wait=True)
        worker = DecisionWorker(client)
        try:
            handles = [worker.submit({}), worker.submit({})]
            deadline = time.monotonic() + 1
            while len(client.calls) < 2 and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertEqual(len(client.calls), 2)
            self.assertTrue(all(handle.started_at is not None and not handle.done() for handle in handles))
        finally:
            worker.close()
        self.assertTrue(client.cancelled.is_set())
        for handle in handles:
            self.assertIsNotNone(handle.completed_at)
            with self.assertRaises(CancelledError):
                handle.result()
        with self.assertRaises(RuntimeError):
            worker.submit({})
        worker.close()

    def test_worker_delivers_results_with_own_timestamps(self):
        worker = DecisionWorker(FakeClient())
        try:
            handle = worker.submit({})
            self.assertEqual(handle.future.result(1).move, "walk_right")
            self.assertLessEqual(handle.started_at, handle.completed_at)
        finally:
            worker.close()


if __name__ == "__main__":
    unittest.main()
