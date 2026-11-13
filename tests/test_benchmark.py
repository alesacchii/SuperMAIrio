import asyncio
from dataclasses import replace
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import httpx

from supermairio.benchmark.edition import MODES, collect, edition_metadata, read_participants, session_progress
from supermairio.benchmark.report import make_report, verify_edition, wilson
from supermairio.config import Config, decisions_key, parse_config, validate_endpoint
from supermairio.contracts import Action, Decision
from supermairio.game.control import TIMED_MOVES, offered_choices
from supermairio.game.emulator import MarioGame
from supermairio.agent import load_model
from supermairio.agent.prompt import ChoiceModel
from supermairio.agent.client import DecisionError
from supermairio.runtime.predictive import InsufficientThroughput, run_predictive
from supermairio.runtime.session import SessionLog
from helpers import ENDPOINT


class EndpointTests(unittest.TestCase):
    def test_environment_precedence_and_key_isolation(self):
        with TemporaryDirectory() as directory, patch("supermairio.config.PROJECT_ROOT", Path(directory)), \
                patch.dict("os.environ", {"SUPERMAIRIO_MODEL": "from-env"}, clear=True):
            (Path(directory) / ".env").write_text("SUPERMAIRIO_MODEL=from-file\n"
                "SUPERMAIRIO_ENDPOINT=http://127.0.0.1:8000/decisions\n", encoding="utf-8")
            config = parse_config([])
            self.assertEqual((config.model, config.endpoint), ("from-env", "http://127.0.0.1:8000/decisions"))
            self.assertEqual(parse_config(["--model", "override"]).model, "override")
            self.assertIsNone(decisions_key(config.endpoint))
            self.assertIsNone(decisions_key(ENDPOINT))
            with patch.dict("os.environ", {"SUPERMAIRIO_API_KEY": "local"}):
                self.assertEqual(decisions_key(config.endpoint), "local")
                self.assertIsNone(decisions_key(ENDPOINT))
        for url in ("localhost/decisions", "ftp://host/decisions", "http://user:password@host/path",
                "http://host/path?token=secret", "http://host/path#token", "http://host\\other/path"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_endpoint(url)

    def test_participants_use_their_own_transport_and_timed_questions(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "participants.toml"
            path.write_text('[[participants]]\nname="remote"\nmodel="vendor/new"\n'
                '[[participants]]\nname="local"\nenv_prefix="LOCAL"\n', encoding="utf-8")
            settings = {"SUPERMAIRIO_ENDPOINT": ENDPOINT, "SUPERMAIRIO_API_KEY": "remote-token",
                "LOCAL_ENDPOINT": "http://localhost:8000/decisions", "LOCAL_MODEL": "local-id"}
            participants = read_participants(path, settings)
            self.assertEqual([entry.key for entry in participants], ["remote-token", None])
            with_local_key = read_participants(path, {**settings, "LOCAL_API_KEY": "local-token"})
            with self.assertRaisesRegex(ValueError, "SUPERMAIRIO_ENDPOINT"):
                read_participants(path, {**settings, "SUPERMAIRIO_ENDPOINT": ""})
        with MarioGame(10) as game:
            observation = game.reset(123)
        context = {"execution_mode": "paused", "control_mode": "timed",
            "choices": offered_choices(TIMED_MOVES, scripted=False, active=False)}

        async def check(participant):
            questions = []

            def answer(request):
                self.assertEqual(str(request.url), participant.endpoint)
                if request.method == "HEAD":
                    self.assertNotIn("authorization", request.headers)
                    return httpx.Response(405)
                expected = f"Bearer {participant.key}" if participant.key else None
                self.assertEqual(request.headers.get("authorization"), expected)
                payload = json.loads(request.content)
                self.assertEqual(payload["model"], participant.model)
                (question,) = payload["questions"]
                questions.append(question)
                choice = "right" if question == "buttons" else "2"
                if question == "frames":
                    self.assertEqual(json.loads(payload["state"][0]["text"])["chosen_buttons"], "right")
                return httpx.Response(200, json={"model": participant.model,
                    "answers": {question: {"type": "choice", "choice": choice}}})

            client = load_model(participant.model, participant.key, 10, endpoint=participant.endpoint)
            self.assertIs(type(client), ChoiceModel)
            with patch.object(client, "_transport", httpx.MockTransport(answer)):
                try:
                    self.assertEqual(await client.prepare(), "ready")
                    payload = client.build_request(observation, None, frames=0, control_context=context).payload
                    self.assertEqual((await client.decide(payload)).move, "right_2")
                finally:
                    await client.aclose()
            self.assertEqual(questions, ["buttons", "frames"])

        for participant in (*participants, with_local_key[1]):
            asyncio.run(check(participant))
        self.assertNotIn("remote-token", repr(participants))
        self.assertNotIn("local-token", repr(with_local_key))
        self.assertIs(type(load_model("test/model", None, 10, endpoint=ENDPOINT)), ChoiceModel)


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(TemporaryDirectory()))
        self.path = self.directory / "participants.toml"
        self.path.write_text('[[participants]]\nname="remote"\nmodel="test/remote"\n'
            '[[participants]]\nname="local"\nenv_prefix="LOCAL"\n', encoding="utf-8")
        self.participants = read_participants(self.path, {"SUPERMAIRIO_ENDPOINT": ENDPOINT,
            "LOCAL_ENDPOINT": "http://localhost/decisions", "LOCAL_MODEL": "local"})
        self.metadata = edition_metadata(self.participants)
        self.edition = self.directory / "edition"

    def test_cumulative_caps_resume_and_incomplete_result(self):
        called = []

        def runner(config, participant, path):
            called.append((participant.name, config.endpoint, config.execution_mode, path.name[0]))
            log = SessionLog(config, path=path)
            try:
                for episode in range(1, config.episodes + 1):
                    log.event("episode_started", episode=episode)
                    if participant.name == "local":
                        log.event("error", episode=episode, provider_error=True)
                        log.event("episode_end", episode=episode, reason="error")
                        raise DecisionError("HTTP 502")
                    log.event("episode_end", episode=episode, reason=("completed", "death", "frame_limit")[(episode - 1) % 3])
            finally:
                log.close()

        collect(self.edition, self.participants, self.metadata, through_block=1, run_session=runner)
        self.assertEqual({block for _, _, _, block in called}, {"1"})
        first_block_calls = len(called)
        collect(self.edition, self.participants, self.metadata, run_session=runner)
        self.assertNotIn("1", {block for _, _, _, block in called[first_block_calls:]})
        self.assertEqual({url for _, url, _, _ in called}, {ENDPOINT, "http://localhost/decisions"})
        for mode in MODES:
            for index, expected in enumerate((30, 40)):
                paths = (self.edition / "sessions" / f"{index:03d}-{mode}").iterdir()
                self.assertEqual(sum(len(session_progress(path)[0]) for path in paths), expected)
        collect(self.edition, self.participants, self.metadata, run_session=lambda *_: self.fail("duplicate attempt"))
        self.assertAlmostEqual(wilson(8, 10)[0], 0.490, places=3)

    def test_report_is_reproducible_and_replay_detects_tampering(self):
        metadata = {**self.metadata, "created_at": "2026-11-13T12:00:00+00:00"}
        path = self.edition / "sessions" / "000-paused" / "1-001"
        config = replace(MODES["paused"], model=self.participants[0].model, endpoint=ENDPOINT, max_frames=10)
        metadata["modes"]["paused"]["max_frames"] = config.max_frames
        log = SessionLog(config, path=path)
        (self.edition / "edition.json").write_text(json.dumps(metadata), encoding="utf-8")
        with MarioGame(config.max_frames) as game:
            initial = game.reset(config.seed).info["x_pos"]
            log.event("episode_started", episode=1)
            log.event("decision", episode=1, request_seconds=0.5, provider="simulated", usage={"cost": 0.01})
            for number in range(1, config.max_frames + 1):
                result = game.step(Action.RIGHT_RUN, 1)
                position = result.observation.info["x_pos"]
                log.frame(episode=1, frames=number, frames_executed=1, action="right_run", x_pos=position,
                    terminated=result.terminated, truncated=result.truncated, reward=result.reward)
            log.event("episode_end", episode=1, reason="frame_limit", frames=number, max_x_pos=position,
                initial_x_pos=initial, x_pos=position, completed=False, death=False)
        log.close()
        first, second = self.directory / "a", self.directory / "b"
        make_report(self.edition, first)
        make_report(first / "edition.zip", second)
        self.assertEqual(len(list(first.iterdir())), 7)
        for file in first.iterdir():
            self.assertEqual(file.read_bytes(), (second / file.name).read_bytes())
        self.assertIn("Unranked", (first / "README.md").read_text(encoding="utf-8"))
        self.assertEqual(verify_edition(first / "edition.zip"), 1)
        frames = path / "frames.jsonl"
        original = frames.read_text(encoding="utf-8")
        frames.write_text(original.replace('"right_run"', '"left_run"'), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "replay diverges"):
            verify_edition(self.edition)
        frames.write_text(original, encoding="utf-8")
        events = path / "events.jsonl"
        events.write_text(events.read_text(encoding="utf-8").replace('"frame_limit"', '"wall_limit"'), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "outcome differs"):
            verify_edition(self.edition)

    def test_predictive_records_partial_episode_after_provider_retry(self):
        class Client(ChoiceModel):
            model_id = "test/partial"
            calls = 0

            async def decide(self, payload):
                self.calls += 1
                if self.calls > 1:
                    raise DecisionError("HTTP 502", transient=True)
                return Decision("right_run", self.model_id, usage={"cost": 0.01})

        path = self.directory / "partial"
        client = Client(None, 1, endpoint=ENDPOINT)
        config = Config(headless=True, execution_mode="predictive", image=False, max_episode_seconds=5)
        with patch("supermairio.agent.load_model", return_value=client), patch("sys.stdout", StringIO()), \
                self.assertRaisesRegex(DecisionError, "HTTP 502"):
            run_predictive(config, game_factory=MarioGame, key_provider=lambda: None,
                log_factory=lambda settings: SessionLog(settings, path=path))
        summary = json.loads((path / "summary.json").read_text(encoding="utf-8"))
        (episode,) = summary["episodes"]
        self.assertEqual(client.calls, 3)
        self.assertEqual((episode["reason"], episode["decisions"], episode["retried_requests"]), ("error", 1, 1))
        self.assertEqual(summary["known_cost"], 0.01)
        self.assertGreater(episode["frames"], 0)

    def test_low_throughput_stops_before_provider_requests(self):
        path = self.directory / "slow"
        with patch("supermairio.runtime.predictive.ShadowPool.throughput", return_value=1999), \
                patch("supermairio.runtime.predictive.DecisionWorker") as worker, patch("sys.stdout", StringIO()), \
                self.assertRaises(InsufficientThroughput):
            run_predictive(replace(MODES["predictive"], model="test/model", endpoint=ENDPOINT), game_factory=MarioGame, key_provider=lambda: None,
                log_factory=lambda settings: SessionLog(settings, path=path), minimum_throughput=2000)
        worker.assert_not_called()
        self.assertEqual(session_progress(path)[0], set())
