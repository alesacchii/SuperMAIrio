"""Model discovery, selection and adapter contracts."""

import io
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

from app.config import parse_config
from app.contracts import Observation
from app.models import get_model_class, load_model
from app.models.gpt_luna import MODEL_ID, Model
from app.openrouter import encode_png


class ModelTests(unittest.TestCase):
    def test_module_name_and_existing_router_identifier_select_same_adapter(self):
        self.assertIs(get_model_class("gpt_luna"), Model)
        self.assertIs(get_model_class(MODEL_ID), Model)
        self.assertIsInstance(load_model("gpt_luna", "test-key", 10), Model)
        self.assertEqual(parse_config(["--model", "gpt_luna"]).model, "gpt_luna")

    def test_adapter_binds_model_and_exposes_trace_without_wire_assumptions(self):
        obs = Observation(np.zeros((240, 256, 3), dtype=np.uint8), {"x_pos": 40})
        request = Model("test-key", 10).build_request(obs, encode_png(obs), frames=0)
        self.assertEqual(request.payload["model"], MODEL_ID)
        self.assertEqual(request.trace["context"]["progress"], {"x": 40})
        self.assertEqual(request.trace["questions"], request.payload["questions"])
        self.assertNotIn("test-key", repr(request))

    def test_new_file_is_discovered_without_registry_changes(self):
        code = ('from app.models.gpt_luna import Model as LunaModel\n'
                'class Model(LunaModel):\n'
                '    model_id = "test/new-model"\n')
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "new_model.py").write_text(code, encoding="utf-8")
            try:
                with patch("app.models.__path__", [directory]):
                    adapter = get_model_class("new_model")
                    self.assertIs(adapter, get_model_class("test/new-model"))
                    obs = Observation(np.zeros((240, 256, 3), dtype=np.uint8), {})
                    request = load_model("new_model", "key", 10).build_request(
                        obs, encode_png(obs), frames=0)
                    self.assertEqual(request.payload["model"], "test/new-model")
            finally:
                sys.modules.pop("app.models.new_model", None)

    def test_invalid_adapter_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "invalid_model.py").write_text("MODEL_ID = 'test/id'\n", encoding="utf-8")
            try:
                with patch("app.models.__path__", [directory]), self.assertRaisesRegex(ValueError, "deve esporre Model"):
                    get_model_class("invalid_model")
            finally:
                sys.modules.pop("app.models.invalid_model", None)

    def test_duplicate_identifiers_are_rejected(self):
        code = ('from app.models.gpt_luna import Model as LunaModel\n'
                'class Model(LunaModel):\n'
                '    model_id = "test/duplicate"\n')
        with tempfile.TemporaryDirectory() as directory:
            for name in ("first_model", "second_model"):
                Path(directory, name + ".py").write_text(code, encoding="utf-8")
            try:
                with patch("app.models.__path__", [directory]), self.assertRaisesRegex(ValueError, "duplicato"):
                    get_model_class("first_model")
            finally:
                for name in ("first_model", "second_model"):
                    sys.modules.pop("app.models." + name, None)

    def test_unknown_model_is_reported_before_start(self):
        with self.assertRaisesRegex(ValueError, "Modello non configurato"):
            get_model_class("not_configured")
        with patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit) as caught:
            parse_config(["--model", "not_configured"])
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(parse_config(["--mode", "demo", "--model", "not_configured"]).mode, "demo")


if __name__ == "__main__":
    unittest.main()
