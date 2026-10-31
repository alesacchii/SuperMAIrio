"""Timed direct control: the model chooses buttons and their duration; nothing is added for it."""

import asyncio
from copy import deepcopy
from io import StringIO
import json
import unittest
from unittest.mock import patch

from app.config import Config, parse_config
from app.contracts import Action, has_jump
from app.control import BUTTON_MOVES, TIMED_FRAMES, TIMED_MOVES, UNJUMPED_FRAMES, TimedExecutor
from app.control import offered_choices
from app.models._choice import ChoiceModel
from app.models.decider import Model as Decider
from app.models.jev import Model as Jev
from app.openrouter import DecisionError, encode_png
import test_realtime
from test_decisions import SCENE, observation


class TimedControlTests(unittest.TestCase):
    invoke = test_realtime.RealtimeTests.invoke
    kinds = staticmethod(test_realtime.RealtimeTests.kinds)

    def test_catalog_pairs_every_button_combination_with_every_duration(self):
        jumps = sum(has_jump(action) for action in Action)
        self.assertEqual(len(TIMED_MOVES), jumps * len(TIMED_FRAMES) + (len(BUTTON_MOVES) - jumps) * len(UNJUMPED_FRAMES))
        self.assertNotIn("right_run_16", TIMED_MOVES)
        move = TIMED_MOVES["right_run_jump_28"]
        self.assertEqual([(s.action, s.frames, s.until_landed) for s in move.segments],
            [(Action.RIGHT_RUN_JUMP, 28, False)])
        self.assertIn("28 game frames", move.description)

    def test_executor_holds_exact_frames_then_releases_without_edges(self):
        executor = TimedExecutor(paused=True)
        executor.start(TIMED_MOVES["right_run_jump_8"])
        for on_ground in [True, False] * 4:
            executor.settle(on_ground)
            self.assertEqual(executor.current(), (Action.RIGHT_RUN_JUMP, "move"))
            executor.advance(1)
        self.assertTrue(executor.finished)
        self.assertEqual(executor.remaining, 0)
        # A repeated A choice continues the press: no release frame is inserted.
        executor.start(TIMED_MOVES["right_run_jump_4"])
        self.assertEqual(executor.current(), (Action.RIGHT_RUN_JUMP, "move"))
        executor.advance(1)
        self.assertEqual(executor.input_context()["held_frames"]["A"], 9)
        self.assertEqual(executor.remaining, 3)
        executor.advance(3)
        self.assertEqual(executor.current(), (Action.NOOP, "waiting"))

    def test_paused_plays_each_choice_for_its_duration_with_no_gap(self):
        summary, events, _, _, _, persisted, _, caught = self.invoke(
            script=[(0.1, "right_run_4"), (0.1, "right_run_jump_8"), (0.1, "noop_2")],
            config=Config(headless=True, max_frames=14, execution_mode="paused", control_mode="timed"))
        self.assertIsNone(caught)
        self.assertEqual([f["action"] for f in self.kinds(events, "frame")],
            ["right_run"] * 4 + ["right_run_jump"] * 8 + ["noop"] * 2)
        requests = self.kinds(events, "request")
        self.assertEqual([r["frames"] for r in requests], [0, 4, 12])
        self.assertEqual(requests[1]["context"]["move"]["then"], "game pauses for your next choice")
        questions = requests[0]["questions"]
        self.assertEqual(set(questions), {"buttons", "frames"})
        self.assertEqual(set(questions["buttons"]["criteria"]), {action.value for action in Action})
        self.assertEqual(list(questions["frames"]["options"]["right_run_jump"]), [str(n) for n in TIMED_FRAMES])
        self.assertEqual(list(questions["frames"]["options"]["noop"]), [str(n) for n in UNJUMPED_FRAMES])
        self.assertIn("full-height jump", questions["frames"]["options"]["jump"]["28"])
        self.assertIn("right_run_jump for 28 frames holds", questions["buttons"]["instructions"])
        self.assertEqual(summary["waiting_frames"], 0)
        self.assertEqual(persisted["protocol"], "choice-timed-buttons-v1")
        self.assertEqual(persisted["moves"]["left_8"], [{"action": "left", "frames": 8, "until_landed": False}])

    def test_realtime_replaces_choice_and_releases_only_after_duration(self):
        _, events, _, _, _, _, _, caught = self.invoke(
            script=[(0.005, "right_4"), (10, "right_4")],
            config=Config(headless=True, max_frames=12, control_mode="timed"))
        self.assertIsNone(caught)
        actions = [(f["action"], f["source"]) for f in self.kinds(events, "frame") if f["index"] == 1]
        self.assertEqual(actions[:4], [("right", "move")] * 4)
        self.assertTrue(actions[4:] and all(action == ("noop", "waiting") for action in actions[4:]))

    def test_untimed_choices_are_rejected(self):
        for choice in ("right_run", "continue", "high_jump_right"):
            summary, _, _, _, _, _, _, caught = self.invoke(script=[(0.005, choice)],
                config=Config(headless=True, max_frames=5, control_mode="timed", execution_mode="paused"))
            self.assertIsNotNone(caught)
            self.assertEqual(summary["moves"], 0)

    def test_adapter_asks_duration_after_buttons_and_joins_the_answers(self):
        obs = observation()
        obs.info["scene"] = deepcopy(SCENE)
        context = {"execution_mode": "paused", "control_mode": "timed",
            "choices": offered_choices(TIMED_MOVES, scripted=False, active=False)}
        answers = {
            "buttons": {"type": "choice", "choice": "right_run_jump", "confidence": 0.5,
                "probabilities": {"right_run_jump": 0.5, "right_run": 0.5}},
            "frames": {"type": "choice", "choice": "28", "confidence": 0.8, "probabilities": {"28": 0.8, "8": 0.2}}}

        class Client(ChoiceModel):
            model_id = "test/timed"
            sent = []

            async def post(self, payload):
                self.sent.append(payload)
                (question,) = payload["questions"]
                return {"model": self.model_id, "answers": {question: answers[question]},
                    "usage": {"cost": 0.25, "input_tokens": 10}}

        client = Client("key", 10)
        payload = client.build_request(obs, encode_png(obs), frames=0, control_context=context).payload
        decision = asyncio.run(client.decide(payload))
        self.assertEqual([list(sent["questions"]) for sent in client.sent], [["buttons"], ["frames"]])
        self.assertEqual(set(client.sent[1]["questions"]["frames"]), {"type", "instructions", "criteria"})
        self.assertEqual(list(client.sent[1]["questions"]["frames"]["criteria"]), [str(n) for n in TIMED_FRAMES])
        self.assertIn("You already selected the buttons: state.chosen_buttons.",
            client.sent[1]["questions"]["frames"]["instructions"])
        self.assertEqual(json.loads(client.sent[1]["state"][0]["text"])["chosen_buttons"], "right_run_jump")
        self.assertNotIn("chosen_buttons", client.sent[0]["state"][0]["text"])
        self.assertEqual(client.sent[1]["state"][1], client.sent[0]["state"][1])
        self.assertEqual(decision.move, "right_run_jump_28")
        self.assertAlmostEqual(decision.confidence, 0.4)
        self.assertEqual(decision.probabilities, {"right_run_jump_28": 0.4, "right_run_jump_8": 0.1})
        self.assertEqual(decision.usage, {"cost": 0.5, "input_tokens": 20})
        answers["frames"] = {"type": "choice", "choice": "3"}
        with self.assertRaises(DecisionError):
            asyncio.run(client.decide(payload))

    def test_jev_padding_note_reaches_both_questions(self):
        obs = observation()
        context = {"execution_mode": "paused", "control_mode": "timed",
            "choices": offered_choices(TIMED_MOVES, scripted=False, active=False)}
        payload = Jev("key", 10).build_request(obs, encode_png(obs), frames=0, control_context=context).payload
        self.assertTrue(all("black padding" in q["instructions"] for q in payload["questions"].values()))

    def test_realtime_asks_one_question_with_every_offered_duration(self):
        _, events, _, _, _, _, _, caught = self.invoke(script=[(0.005, "right_run_jump_28")],
            config=Config(headless=True, max_frames=5, control_mode="timed"))
        self.assertIsNone(caught)
        (question,) = self.kinds(events, "request")[0]["questions"].values()
        self.assertEqual(set(question["criteria"]), set(TIMED_MOVES))
        self.assertIn("full-height jump", question["criteria"]["right_run_jump_28"])

    def test_no_image_sends_only_the_state_to_every_adapter(self):
        _, events, _, _, _, persisted, _, caught = self.invoke(script=[(0.005, "right_run_jump_28")],
            config=Config(headless=True, max_frames=5, control_mode="timed", image=False, save_screenshots=True))
        self.assertIsNone(caught)
        request = self.kinds(events, "request")[0]
        self.assertIsNone(request["screenshot"])
        self.assertIn("No screenshot is supplied", request["questions"]["next_action"]["instructions"])
        self.assertFalse(persisted["image"])
        obs = observation()
        context = {"execution_mode": "paused", "control_mode": "timed",
            "choices": offered_choices(TIMED_MOVES, scripted=False, active=False)}
        for client in (Decider("key", 10), Jev("key", 10)):
            request = client.build_request(obs, None, frames=0, control_context=context)
            self.assertEqual([part["type"] for part in request.payload["state"]], ["text"])
            self.assertNotIn("image_preprocessing", request.trace)
            self.assertTrue(all("black padding" not in q["instructions"] for q in request.payload["questions"].values()))

    def test_cli_rejects_a_request_without_observations(self):
        self.assertFalse(parse_config(["--no-image"]).image)
        with patch("sys.stderr", StringIO()), self.assertRaises(SystemExit):
            parse_config(["--no-image", "--no-scene"])

    def test_cli_accepts_timed(self):
        self.assertEqual(parse_config(["--control-mode", "timed"]).control_mode, "timed")


if __name__ == "__main__":
    unittest.main()
