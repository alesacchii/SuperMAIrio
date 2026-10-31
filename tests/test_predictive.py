"""Predictive control: shadow emulation, model-chosen inputs, parallel requests and the shared context."""

import asyncio
from io import StringIO
import json
from pathlib import Path
import tempfile
from time import sleep
import unittest
from unittest.mock import patch

import numpy as np

from app.config import Config, DEFAULT_MODEL, parse_config
from app.contracts import Action, Decision
from app.control import HOP_FRAMES, PREDICTIVE_MOVES, RUN_UP_FRAMES, choice_frames, offered_choices
from app.game import MarioGame
from app.models._choice import ChoiceModel
from app.models.decider import Model as Decider
from app.models.jev import Model as Jev
from app.openrouter import DecisionError, DecisionWorker, encode_png
from app.predictive import run_predictive
from app.session import SessionLog
from test_decisions import observation


class ShadowEmulationTests(unittest.TestCase):
    def test_simulation_from_a_snapshot_equals_the_real_frames(self):
        plan = [Action.RIGHT_RUN] * 5 + [Action.RIGHT_RUN_JUMP] * 20 + [Action.RIGHT] * 10
        with MarioGame(600) as game, MarioGame(600) as shadow:
            game.reset(123)
            shadow.reset(123)
            for _ in range(40):
                game.step(Action.RIGHT_RUN, 1)
            predicted, frames, _ = shadow.simulate(game.snapshot(), plan)
            for action in plan:
                result = game.step(action, 1)
            real = result.observation
            self.assertEqual(len(frames), len(plan))
            np.testing.assert_array_equal(predicted.rgb, real.rgb)
            self.assertEqual(predicted.info["scene"], real.info["scene"])
            self.assertEqual((predicted.info["x_pos"], predicted.info["on_ground"]),
                (real.info["x_pos"], real.info["on_ground"]))
            self.assertEqual(frames[-1]["on_ground"], real.info["on_ground"])

    def test_snapshot_requires_a_reset_game(self):
        with MarioGame(10) as game, self.assertRaises(RuntimeError):
            game.snapshot()


class PredictiveChoiceTests(unittest.TestCase):
    def test_a_jump_on_the_ground_with_a_held_starts_with_a_press_edge(self):
        self.assertEqual(choice_frames("right_run_jump", Action.RIGHT_RUN_JUMP, True),
            ([Action.RIGHT_RUN], Action.RIGHT_RUN_JUMP))
        # In the air A stays held: releasing it would cut the jump.
        self.assertEqual(choice_frames("right_run_jump", Action.RIGHT_RUN_JUMP, False), ([], Action.RIGHT_RUN_JUMP))
        self.assertEqual(choice_frames("right_run_jump", Action.RIGHT_RUN, True), ([], Action.RIGHT_RUN_JUMP))
        self.assertEqual(choice_frames("right_run", Action.RIGHT_RUN_JUMP, True), ([], Action.RIGHT_RUN))

    def test_short_jump_and_run_up_are_fixed_sequences_chosen_by_the_model(self):
        first, rest = choice_frames("right_run_hop", Action.RIGHT_RUN, True)
        self.assertEqual((first, rest), ([Action.RIGHT_RUN_JUMP] * HOP_FRAMES, Action.NOOP))
        first, _ = choice_frames("right_hop", Action.RIGHT_JUMP, True)
        self.assertEqual(first, [Action.RIGHT] + [Action.RIGHT_JUMP] * HOP_FRAMES)
        self.assertEqual(choice_frames("right_run_then_jump", Action.RIGHT_RUN_JUMP, True),
            ([Action.RIGHT_RUN] * RUN_UP_FRAMES, Action.RIGHT_RUN_JUMP))
        self.assertTrue(all("until your next choice" in move.description for move in PREDICTIVE_MOVES.values()))


class ParallelRequestTests(unittest.TestCase):
    def test_first_valid_copy_wins_and_losing_copies_are_kept_for_their_cost(self):
        class Client:
            timeout = 5
            calls = 0

            async def decide(self, payload):
                Client.calls += 1
                number = Client.calls
                if number == 1:
                    raise DecisionError("OpenRouter: errore HTTP 502", transient=True)
                await asyncio.sleep(0.01 if number == 2 else 0.05)
                return Decision(f"copy{number}", "test", usage={"cost": 0.1})

        worker = DecisionWorker(Client())
        try:
            handle = worker.submit({}, copies=3)
            self.assertTrue(handle.wait(2))
            self.assertEqual(handle.result().move, "copy2")
            self.assertEqual(handle.hedge_losers, 1)
            for _ in range(200):
                if worker.extra_decisions:
                    break
                sleep(0.01)
        finally:
            worker.close()
        self.assertEqual([decision.move for decision in worker.extra_decisions], ["copy3"])

    def test_all_failed_copies_raise_the_error(self):
        class Client:
            timeout = 5

            async def decide(self, payload):
                raise DecisionError("OpenRouter: errore HTTP 503", transient=True)

        worker = DecisionWorker(Client())
        try:
            handle = worker.submit({}, copies=2)
            handle.wait(2)
            with self.assertRaises(DecisionError):
                handle.result()
        finally:
            worker.close()


class PredictiveConfigTests(unittest.TestCase):
    @patch.dict("app.config.os.environ", {"OPENROUTER_MODEL": DEFAULT_MODEL})
    def test_defaults_are_the_winning_configuration(self):
        config = parse_config([])
        self.assertEqual((config.model, config.execution_mode, config.control_mode, config.choice_preview,
            config.parallel_requests, config.image, config.scene, config.game_fps),
            ("perplexity/pplx-decider-v1.2", "predictive", "buttons", 30, 2, False, True, 60))
        # Each other mode keeps its own defaults instead of being rejected for the predictive ones.
        for argv in (["--execution-mode", "paused"], ["--execution-mode", "realtime"],
                ["--control-mode", "timed"], ["--control-mode", "moves"]):
            with self.subTest(argv=argv):
                other = parse_config(argv)
                self.assertNotEqual(other.execution_mode, "predictive")
                self.assertEqual((other.choice_preview, other.parallel_requests, other.image), (0, 1, True))
        self.assertTrue(parse_config(["--no-scene"]).image)
        self.assertTrue(parse_config(["--image"]).image)
        self.assertTrue(parse_config(["--save-screenshots"]).image)

    def test_predictive_options_and_their_requirements(self):
        config = parse_config(["--execution-mode", "predictive", "--choice-preview", "30",
            "--parallel-requests", "2", "--speculative-width", "3", "--decision-frames", "16"])
        self.assertEqual((config.execution_mode, config.choice_preview, config.parallel_requests,
            config.speculative_width, config.decision_frames), ("predictive", 30, 2, 3, 16))
        for argv in (["--execution-mode", "predictive", "--control-mode", "timed"],
                ["--execution-mode", "paused", "--choice-preview", "30"],
                ["--execution-mode", "realtime", "--speculative-width", "2"],
                ["--execution-mode", "predictive", "--speculative-width", "11"],
                ["--parallel-requests", "0"], ["--execution-mode", "paused", "--parallel-requests", "2"]):
            with self.subTest(argv=argv), patch("sys.stderr", StringIO()), self.assertRaises(SystemExit):
                parse_config(argv)


def predictive_context(**changes):
    return {"execution_mode": "predictive", "control_mode": "buttons", "game_fps": 60, "decision_frames": 33,
        "choices": offered_choices(PREDICTIVE_MOVES, scripted=False, active=True),
        "input": {"buttons": ["right", "B"], "held_frames": {"right": 40, "B": 40}}, "jump_observation": None,
        "current_move": "right_run", "move_frames": 40, "move_finished": False, "move_remaining_frames": None,
        "stuck": False, "recent_moves": [], **changes}


class PredictivePayloadTests(unittest.TestCase):
    def test_every_model_receives_the_same_context_and_image(self):
        obs = observation()
        context = predictive_context(preview={name: {"outcome": "alive", "frames": 43, "dx": 20, "dy": 0,
            "on_ground": True} for name in PREDICTIVE_MOVES}, preview_frames=43)
        requests = [model("key", 10).build_request(obs, encode_png(obs), frames=0, control_context=context)
            for model in (Decider, Jev)]
        first, second = (request.payload for request in requests)
        self.assertNotEqual(first["model"], second["model"])
        self.assertEqual(first["state"], second["state"])
        self.assertEqual(first["questions"], second["questions"])
        self.assertEqual(requests[0].trace["image_preprocessing"], requests[1].trace["image_preprocessing"])

    def test_predicted_instant_hold_and_previews_reach_the_model(self):
        preview = {name: {"outcome": "alive", "frames": 43, "dx": 20, "dy": 0, "on_ground": True}
            for name in PREDICTIVE_MOVES}
        preview["right_run"] = {"outcome": "dies", "frames": 21, "dx": 40, "dy": 0, "on_ground": False}
        context = predictive_context(preview=preview, preview_frames=43, frames_without_progress=120)
        payload = Decider("key", 10).build_request(observation(), None, frames=0, control_context=context).payload
        question = payload["questions"]["next_action"]
        state = json.loads(payload["state"][0]["text"])
        self.assertEqual(set(question["criteria"]), set(PREDICTIVE_MOVES))
        self.assertTrue(question["criteria"]["right_run"].endswith("Preview: Mario dies after 21 frames."))
        self.assertIn("Preview: alive after 43 frames, 20 px right, on the ground.", question["criteria"]["noop"])
        self.assertIn("show the instant your choice takes effect", question["instructions"])
        self.assertIn("about 33 game frames later", question["instructions"])
        self.assertNotIn("dx_at_response", payload["state"][0]["text"])
        self.assertEqual(state["move"]["hold_frames"], 33)
        self.assertNotIn("preview", state)
        self.assertIn("No forward progress for 120 frames: Mario is not getting closer to the flag.",
            state["warnings"])


class ScriptedModel(ChoiceModel):
    """Runs right and jumps when the predicted state shows a hazard close ahead; parallel copies of a
    request answer after 30 or 60 ms."""

    model_id = "test/predictive"
    requests = []
    calls = 0

    async def decide(self, payload):
        ScriptedModel.calls += 1
        await asyncio.sleep(0.03 * (1 + ScriptedModel.calls % 2))
        state = json.loads(payload["state"][0]["text"])
        ScriptedModel.requests.append(payload)
        nearby = state["nearby"]
        close = any(0 < item["dx"] < 60 for item in nearby["enemies"]) or any(
            item and 0 < item["dx"] < 40 for item in (nearby["obstacle_ahead"], nearby["pit_ahead"]))
        move = "right_run_jump" if state["mario"]["on_ground"] and close else "right_run"
        return Decision(move, self.model_id, usage={"cost": 0.001})


class PredictiveRunnerTests(unittest.TestCase):
    def test_choices_apply_at_the_predicted_frame_and_the_game_never_waits(self):
        ScriptedModel.requests = []
        config = Config(headless=True, execution_mode="predictive", choice_preview=20, parallel_requests=2,
            image=False, max_episode_seconds=5, decision_frames=30)
        with tempfile.TemporaryDirectory() as directory:
            with patch("app.models.load_model", return_value=ScriptedModel("key", 10)), \
                    patch("app.session.SessionLog", side_effect=lambda config: SessionLog(config, root=directory)), \
                    patch("sys.stdout", StringIO()):
                run_predictive(config, game_factory=MarioGame, key_provider=lambda: "key")
            (path,) = Path(directory).iterdir()
            events = [json.loads(line) for line in (path / "events.jsonl").read_text(encoding="utf-8").splitlines()]
            frames = [json.loads(line) for line in (path / "frames.jsonl").read_text(encoding="utf-8").splitlines()]
            summary = json.loads((path / "summary.json").read_text(encoding="utf-8"))
            settings = json.loads((path / "config.json").read_text(encoding="utf-8"))
        applied = [event for event in events if event["event"] == "choice_applied"]
        self.assertGreaterEqual(len(applied), 2)
        on_time = [event for event in applied if not event["late_frames"]]
        self.assertTrue(on_time)
        self.assertTrue(all(event["frame"] == event["target_frame"] for event in on_time))
        self.assertFalse(any(event["prediction_mismatch"] for event in on_time))
        # Before the first choice Mario stands still; afterwards every frame belongs to a model choice.
        first = next(index for index, frame in enumerate(frames) if frame["index"] is not None)
        self.assertTrue(all(frame["action"] == "noop" and frame["source"] == "waiting" for frame in frames[:first]))
        self.assertTrue(all(frame["source"] == "move" and frame["move"] in PREDICTIVE_MOVES for frame in frames[first:]))
        requests = [event for event in events if event["event"] == "request"]
        self.assertTrue(all("Preview: " in text for request in requests
            for text in request["questions"]["next_action"]["criteria"].values() if request["complete_prediction"]))
        episode = summary["episodes"][0]
        self.assertEqual(episode["moves"], len(applied))
        self.assertEqual(episode["frames"], len(frames))
        self.assertGreater(episode["hedge_losers"], 0)
        self.assertEqual(settings["protocol"], "choice-buttons-predictive-v1")
        self.assertEqual(set(settings["moves"]), set(PREDICTIVE_MOVES))


if __name__ == "__main__":
    unittest.main()
