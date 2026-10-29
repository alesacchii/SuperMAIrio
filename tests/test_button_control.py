"""Direct model choices stay continuous across request latency and never gain A edges."""

import asyncio
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.config import Config, parse_config
from app.contracts import Action, Decision
from app.control import BUTTON_MOVES, ButtonExecutor
from app.moves import Flight
from app.openrouter import DecisionError
from app.models._choice import ChoiceModel, build_payload
from app.runner import run
from app.session import SessionLog
import test_realtime
from test_decisions import SCENE, observation


class ButtonControlTests(unittest.TestCase):
    invoke = test_realtime.RealtimeTests.invoke
    kinds = staticmethod(test_realtime.RealtimeTests.kinds)

    def test_latency_does_not_release_and_repeat_does_not_retrigger_jump(self):
        summary, events, workers, game, _, persisted, _, caught = self.invoke(
            script=[(0.005, "right_run_jump"), (0.6, "right_run_jump"), (0.1, "left"), (0.1, "noop")],
            config=Config(headless=True, max_frames=65, control_mode="buttons"))
        self.assertIsNone(caught)
        frames = self.kinds(events, "frame")
        held = [f for f in frames if f["index"] in (1, 2)]
        self.assertGreater(len(held), 40)
        self.assertTrue(all(f["action"] == "right_run_jump" and f["source"] == "move" for f in held))
        self.assertEqual(summary["jump_release_frames"], 0)
        for index, action in ((3, "left"), (4, "noop")):
            self.assertTrue(all(f["action"] == action for f in frames if f["index"] == index))
            self.assertTrue(any(f["index"] == index for f in frames))
        requests = self.kinds(events, "request")
        self.assertEqual(requests[1]["frames"], held[0]["frames"])
        self.assertEqual(requests[1]["context"]["move"]["ends"], "at next choice")
        for request in requests:
            self.assertEqual(set(request["questions"]["next_action"]["criteria"]), set(BUTTON_MOVES))
            self.assertNotIn("landing", request["context"]["move"])
        self.assertEqual(persisted["protocol"], "choice-buttons-v1")
        self.assertEqual(persisted["moves"]["right"]["duration"], "until_next_choice")
        self.assertTrue(all(w.closed for w in workers))

    def test_paused_executes_one_frame_per_choice(self):
        _, events, _, _, _, _, _, caught = self.invoke(
            script=[(0.1, "right_run_jump"), (0.1, "right_run_jump"), (0.1, "noop")],
            config=Config(headless=True, max_frames=3, execution_mode="paused", control_mode="buttons"))
        self.assertIsNone(caught)
        self.assertEqual([f["action"] for f in self.kinds(events, "frame")],
            ["right_run_jump", "right_run_jump", "noop"])

    def test_same_latency_exposes_fixed_move_gaps_only(self):
        waiting = {}
        for mode, choice in (("moves", "run_right"), ("buttons", "right_run")):
            summary, events, _, _, _, _, _, caught = self.invoke(
                script=[(0.005, choice), (0.6, choice)],
                config=Config(headless=True, max_frames=65, control_mode=mode))
            self.assertIsNone(caught)
            waiting[mode] = sum(f["source"] == "waiting" for f in self.kinds(events, "frame")
                if f["index"] is not None)
        self.assertGreater(waiting["moves"], 20)
        self.assertEqual(waiting["buttons"], 0)

    def test_landing_never_changes_buttons(self):
        executor = ButtonExecutor()
        executor.start(BUTTON_MOVES["right_run_jump"])
        for on_ground in [True, False, False, True] * 100:
            executor.settle(on_ground)
            self.assertEqual(executor.current(), (Action.RIGHT_RUN_JUMP, "move"))
            executor.advance(1)
        self.assertFalse(executor.finished)
        executor.start(BUTTON_MOVES["right_run_jump"])
        self.assertEqual(executor.current(), (Action.RIGHT_RUN_JUMP, "move"))

    def test_input_context_preserves_actual_hold_across_repeated_choices(self):
        executor = ButtonExecutor()
        executor.start(BUTTON_MOVES["right_run_jump"])
        executor.advance(20)
        snapshot = executor.input_context()
        executor.start(BUTTON_MOVES["right_run_jump"])
        executor.advance(1)
        self.assertEqual(executor.input_context()["held_frames"]["A"], 21)
        executor.start(BUTTON_MOVES["right"])
        executor.advance(1)
        self.assertEqual(executor.input_context(), {"buttons": ["right"], "held_frames": {"right": 22}})
        self.assertEqual(snapshot["held_frames"]["A"], 20)
        executor.start(BUTTON_MOVES["right_jump"])
        executor.advance(1)
        self.assertEqual(executor.input_context()["held_frames"], {"right": 23, "A": 1})

    def test_retry_holds_buttons_and_reset_forgets_them(self):
        _, events, _, _, _, _, _, caught = self.invoke(
            script=[(0.005, "left"), (0.05, DecisionError("temporary", transient=True)),
                (10, "right"), (10, "right")],
            config=Config(headless=True, max_frames=20, episodes=2, control_mode="buttons"))
        self.assertIsNone(caught)
        frames = self.kinds(events, "frame")
        self.assertTrue(all(f["action"] == "left" for f in frames if f["episode"] == 1 and f["index"] == 1))
        self.assertTrue(all(f["action"] == "noop" for f in frames if f["episode"] == 2))
        self.assertEqual(len(self.kinds(events, "request_failed")), 1)

    def test_scripted_choices_are_rejected_in_direct_mode(self):
        for choice in ("continue", "high_jump_right"):
            summary, _, _, _, _, _, _, caught = self.invoke(script=[(0.005, choice)],
                config=Config(headless=True, max_frames=5, control_mode="buttons"))
            self.assertIsInstance(caught, DecisionError)
            self.assertEqual(summary["moves"], 0)

    def test_cli_selects_protocol(self):
        self.assertEqual(parse_config(["--control-mode", "buttons"]).control_mode, "buttons")
        self.assertEqual(parse_config([]).control_mode, "buttons")
        self.assertEqual(parse_config(["--control-mode", "moves"]).control_mode, "moves")

    def test_direct_context_projects_overhead_blocks_without_selecting_an_action(self):
        obs = observation()
        obs.info["scene"] = deepcopy(SCENE)
        obs.info["scene"]["mario"]["speed"] = 2
        obs.info["scene"]["blocks"] = [{"type": "question_block", "dx": 40, "dy": 48}]
        payload = build_payload("test", obs, b"png", frames=0, control_context={
            "execution_mode": "realtime", "control_mode": "buttons", "recent_response_frames": 10})
        state = json.loads(payload["state"][0]["text"])
        self.assertEqual(state["nearby"]["blocks"][0], {
            "type": "question_block", "dx": 40, "dy": 48, "dx_at_response": 20})
        self.assertNotIn("recent_moves", state)
        self.assertEqual(set(payload["questions"]["next_action"]["criteria"]), set(BUTTON_MOVES))
        self.assertIn("NEXT button input", payload["questions"]["next_action"]["instructions"])
        self.assertIn("8 game frames for a short jump, 28 for full height",
            payload["questions"]["next_action"]["instructions"])

    def test_airborne_context_keeps_press_speed_instead_of_hypothetical_new_jump(self):
        flight = Flight()
        flight.step(Action.RIGHT_RUN_JUMP, True, False, 0)
        flight.step(Action.RIGHT_RUN_JUMP, False, False, 3)
        flight.invalidate()
        history = flight.observed()
        self.assertEqual(history["speed_at_A_press"], 0)
        self.assertEqual(history["frames_since_A_press"], 2)
        self.assertEqual(history["flat_ground_reach_at_press"]["high_jump"], 53)
        self.assertIsNone(flight.landing_in(3, False, 28))
        obs = observation()
        obs.info["scene"] = deepcopy(SCENE)
        obs.info["scene"]["mario"].update(on_ground=False, speed=3)
        payload = build_payload("test", obs, b"png", frames=2, control_context={
            "execution_mode": "realtime", "control_mode": "buttons", "jump_observation": history})
        state = json.loads(payload["state"][0]["text"])
        self.assertNotIn("jump_reach_px", state["mario"])
        self.assertEqual(state["jump_observation"], history)
        flight.step(Action.RIGHT_RUN, False, True, 3)
        self.assertIsNone(flight.observed())

    def test_no_scene_withholds_jump_observation(self):
        _, events, _, _, _, _, _, caught = self.invoke(
            script=[(0.005, "right_run_jump"), (0.05, "right_run_jump")],
            config=Config(headless=True, max_frames=10, scene=False))
        self.assertIsNone(caught)
        self.assertTrue(all("jump_observation" not in r["context"] for r in self.kinds(events, "request")))

    def test_session_records_actual_target_fps(self):
        _, _, _, _, _, persisted, _, caught = self.invoke(script=[(0.005, "right")],
            config=Config(headless=True, max_frames=5, game_fps=30))
        self.assertIsNone(caught)
        self.assertEqual(persisted["fps_target"], 30)

    def test_real_emulator_holds_model_buttons_during_request(self):
        class Client(ChoiceModel):
            model_id = "test/buttons"
            calls = 0

            async def decide(self, payload):
                self.calls += 1
                await asyncio.sleep(0.005 if self.calls == 1 else 10)
                return Decision("right_run", self.model_id)

        with tempfile.TemporaryDirectory() as directory:
            with patch("app.runner.openrouter_key", return_value="test-key"), \
                    patch("app.models.load_model", return_value=Client("test-key", 10)), \
                    patch("app.session.SessionLog", side_effect=lambda config: SessionLog(config, root=directory)), \
                    patch("sys.stdout", StringIO()):
                run(Config(headless=True, max_frames=50, control_mode="buttons"))
            session = next(Path(directory).iterdir())
            summary = json.loads((session / "summary.json").read_text())
            frames = [json.loads(line) for line in (session / "frames.jsonl").read_text().splitlines()]
        held = [frame for frame in frames if frame["index"] == 1]
        self.assertGreater(len(held), 16)
        self.assertTrue(all(frame["action"] == "right_run" and frame["source"] == "move" for frame in held))
        self.assertEqual(summary["status"], "finished")
        self.assertGreater(summary["x_pos"], summary["initial_x_pos"])
        self.assertEqual(summary["cancelled_requests"], 1)


if __name__ == "__main__":
    unittest.main()
