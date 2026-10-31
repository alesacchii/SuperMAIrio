"""Model discovery, selection and adapter contracts."""

import asyncio
import base64
import io
import os
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx
import numpy as np
from PIL import Image

from app.config import parse_config
from app.contracts import Decision, Observation
from app.models import get_model_class, load_model
from app.models.gpt_luna import MODEL_ID, Model
from app.models.jev import MODEL_ID as JEV_MODEL_ID, Model as JevModel
from app.models.decider import MODEL_ID as DECIDER_MODEL_ID, Model as DeciderModel
from app.models.d1 import MODEL_ID as D1_MODEL_ID, Model as D1Model
from app.openrouter import ENDPOINT, OpenRouterClient, encode_png


class ModelTests(unittest.TestCase):
    def test_decider_uses_shared_protocol_without_model_specific_controls(self):
        self.assertIs(get_model_class("decider"), DeciderModel)
        self.assertIs(get_model_class(DECIDER_MODEL_ID), DeciderModel)
        obs = Observation(np.zeros((240, 256, 3), dtype=np.uint8), {"x_pos": 40})
        context = {"execution_mode": "realtime", "control_mode": "buttons"}
        decider = DeciderModel("test-key", 10).build_request(obs, encode_png(obs), frames=0, control_context=context)
        luna = Model("test-key", 10).build_request(obs, encode_png(obs), frames=0, control_context=context)
        self.assertEqual(decider.payload, {**luna.payload, "model": DECIDER_MODEL_ID})
        self.assertEqual(decider.trace, luna.trace)

    def test_d1_uses_shared_protocol_without_model_specific_controls(self):
        self.assertEqual(D1_MODEL_ID, "liquid/d1.1")
        self.assertIs(get_model_class("d1"), D1Model)
        self.assertIs(get_model_class(D1_MODEL_ID), D1Model)
        obs = Observation(np.zeros((240, 256, 3), dtype=np.uint8), {"x_pos": 40})
        context = {"execution_mode": "realtime", "control_mode": "buttons"}
        d1 = D1Model("test-key", 10).build_request(obs, encode_png(obs), frames=0, control_context=context)
        luna = Model("test-key", 10).build_request(obs, encode_png(obs), frames=0, control_context=context)
        self.assertEqual(d1.payload, {**luna.payload, "model": D1_MODEL_ID})
        self.assertEqual(d1.trace, luna.trace)

    def test_adapter_can_decode_other_questions_using_shared_http(self):
        class Client(OpenRouterClient):
            def parse_response(self, body, payload):
                self.payload_seen = payload
                return Decision(body["control"], "test/custom", usage=body["usage"])

        async def check():
            client = Client("test-key", 10, transport=httpx.MockTransport(lambda request:
                httpx.Response(200, json={"control": "right_jump", "usage": {"cost": 0.01}})))
            payload = {"questions": {"horizontal": {}, "jump": {}}}
            try:
                decision = await client.decide(payload)
                self.assertEqual(decision.move, "right_jump")
                self.assertEqual(decision.usage, {"cost": 0.01})
                self.assertIs(client.payload_seen, payload)
            finally:
                await client.aclose()
        asyncio.run(check())

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

    def test_jev_uses_same_multimodal_prompt_and_openrouter_transport(self):
        self.assertIs(get_model_class("jev"), JevModel)
        self.assertIs(get_model_class(JEV_MODEL_ID), JevModel)
        obs = Observation(np.full((240, 256, 3), [123, 45, 67], dtype=np.uint8), {"x_pos": 40})
        for context in (None, {"execution_mode": "realtime", "recent_response_frames": 15},
                {"execution_mode": "realtime", "control_mode": "buttons", "recent_response_frames": 15}):
            with self.subTest(context=context):
                request = JevModel("test-key", 10).build_request(obs, encode_png(obs), frames=0,
                    control_context=context)
                luna = Model("test-key", 10).build_request(obs, encode_png(obs), frames=0,
                    control_context=context)
                self.assertEqual(request.payload["model"], JEV_MODEL_ID)
                self.assertEqual(request.payload["state"][0], luna.payload["state"][0])
                self.assertEqual(request.trace["context"], luna.trace["context"])
                question = request.payload["questions"]["next_action"]
                self.assertEqual(question["criteria"], luna.payload["questions"]["next_action"]["criteria"])
                self.assertTrue(question["instructions"].startswith(luna.payload["questions"]["next_action"]["instructions"]))
                image_url = request.payload["state"][1]["image_url"]["url"]
                with Image.open(io.BytesIO(base64.b64decode(image_url.split(",", 1)[1]))) as image:
                    self.assertEqual(image.size, (280, 280))
                    np.testing.assert_array_equal(np.asarray(image)[:240, :256], obs.rgb)
                    self.assertFalse(np.asarray(image)[240:].any())
                    self.assertFalse(np.asarray(image)[:, 256:].any())
                self.assertEqual(request.trace["image_preprocessing"]["padding_bottom"], 40)

        async def check_transport():
            def respond(request):
                self.assertEqual(str(request.url), ENDPOINT)
                return httpx.Response(200, json={"model": JEV_MODEL_ID,
                    "answers": {"next_action": {"type": "choice", "choice": "right"}}})
            client = JevModel("test-key", 10, transport=httpx.MockTransport(respond))
            try:
                decision = await client.decide(request.payload)
                self.assertEqual(decision.move, "right")
                self.assertEqual(decision.model, JEV_MODEL_ID)
            finally:
                await client.aclose()

        asyncio.run(check_transport())

    def test_model_selection_precedence_and_fallback(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch("app.config.PROJECT_ROOT", Path(directory)), patch.dict(os.environ, {}, clear=True):
            self.assertEqual(parse_config([]).model, DECIDER_MODEL_ID)
            envfile = Path(directory, ".env")
            envfile.write_text("OPENROUTER_MODEL=typesafe/jev-1.14\n", encoding="utf-8")
            self.assertEqual(parse_config([]).model, JEV_MODEL_ID)
            self.assertNotIn("OPENROUTER_MODEL", os.environ)
            with patch.dict(os.environ, {"OPENROUTER_MODEL": "gpt_luna"}):
                self.assertEqual(parse_config([]).model, "gpt_luna")
                self.assertEqual(parse_config(["--model", "jev"]).model, "jev")
            envfile.write_text("OPENROUTER_MODEL=\n", encoding="utf-8")
            self.assertEqual(parse_config([]).model, DECIDER_MODEL_ID)
            for value in ("unknown/model", "   "):
                with patch.dict(os.environ, {"OPENROUTER_MODEL": value}), \
                        patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
                    parse_config([])

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
