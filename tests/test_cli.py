"""The single command line: subcommands, benchmark tracks and the dry-run schedule."""

from dataclasses import replace
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from helpers import ENDPOINT, MODEL_ENV, MODEL_ID

from supermairio.benchmark.edition import MODES
from supermairio.cli import main
from supermairio.config import TRACKS, Config, parse_config


class CliTests(unittest.TestCase):
    def test_help_and_version_exit_cleanly(self):
        for argv in (["--help"], ["--version"], ["play", "--help"], ["bench", "--help"], ["bench", "run", "--help"],
                     ["replay", "--help"]):
            with self.subTest(argv=argv), patch("sys.stdout", io.StringIO()), self.assertRaises(SystemExit) as done:
                main(argv)
            self.assertEqual(done.exception.code, 0)

    def test_a_subcommand_is_required(self):
        with patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit) as done:
            main([])
        self.assertEqual(done.exception.code, 2)

    @patch.dict("supermairio.config.os.environ", MODEL_ENV)
    def test_play_defaults_are_the_realtime_track(self):
        self.assertEqual(parse_config([]), replace(TRACKS["realtime"], model=MODEL_ID, endpoint=ENDPOINT))

    @patch.dict("supermairio.config.os.environ", MODEL_ENV)
    def test_tracks_match_the_benchmark_sessions(self):
        for track, mode in (("realtime", "predictive"), ("turn-based", "paused")):
            with self.subTest(track=track):
                config = parse_config(["--track", track, "--headless", "--episodes", "3"])
                self.assertEqual(config, replace(MODES[mode], model=MODEL_ID, endpoint=ENDPOINT, episodes=3))
        self.assertEqual(parse_config(["--track", "turn-based", "--model", "other"]).model, "other")

    @patch.dict("supermairio.config.os.environ", MODEL_ENV)
    def test_track_rejects_protocol_options(self):
        for option in (["--seed", "7"], ["--image"], ["--control-mode", "moves"], ["--request-timeout", "5"],
                       ["--choice-preview", "10"], ["--save-screenshots"]):
            with self.subTest(option=option), patch("sys.stderr", io.StringIO()) as error, \
                    self.assertRaises(SystemExit):
                parse_config(["--track", "realtime", *option])
            self.assertIn("fixes the protocol", error.getvalue())

    def test_play_returns_the_session_exit_code(self):
        with patch.dict("supermairio.config.os.environ", MODEL_ENV), \
                patch("supermairio.runtime.play.run") as run, patch("sys.stdout", io.StringIO()):
            self.assertEqual(main(["play", "--mode", "demo", "--headless"]), 0)
        self.assertEqual(run.call_args.args[0], Config(mode="demo", headless=True, model=MODEL_ID, execution_mode="predictive",
            image=False, choice_preview=30, parallel_requests=2))

    def test_bench_run_prints_the_schedule_without_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            participants = Path(directory, "participants.toml")
            participants.write_text('[[participants]]\nname = "first"\nmodel = "vendor/first"\n', encoding="utf-8")
            with patch("supermairio.benchmark.edition.environment", return_value={"SUPERMAIRIO_ENDPOINT": ENDPOINT}), \
                    patch("supermairio.benchmark.edition.collect") as collect, \
                    patch("sys.stdout", io.StringIO()) as output:
                self.assertEqual(main(["bench", "run", "--participants", str(participants)]), 0)
        collect.assert_not_called()
        lines = output.getvalue().splitlines()
        self.assertEqual(sum(line.startswith("Block ") for line in lines), 2)
        self.assertIn("Dry run", lines[-1])

    def test_bench_errors_are_reported_without_traceback(self):
        with patch("supermairio.benchmark.edition.environment", return_value={}), \
                patch("sys.stderr", io.StringIO()) as error:
            self.assertEqual(main(["bench", "run", "--participants", "missing.toml"]), 1)
        self.assertTrue(error.getvalue().startswith("Benchmark: "))


if __name__ == "__main__":
    unittest.main()
