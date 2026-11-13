"""Model selection and the shared adapter contract."""

import asyncio
import base64
import io
import os
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx
import numpy as np
from PIL import Image

from supermairio.config import parse_config
from supermairio.contracts import Decision, Observation
from supermairio.agent import load_model
from supermairio.agent.prompt import ChoiceModel
from supermairio.agent.client import DecisionsClient, encode_png
from helpers import ENDPOINT, MODEL_ENV, MODEL_ID

class ModelTests(unittest.TestCase):
    def test_model_ids_pass_through(self):
        for identifier in ("first-model", "vendor/second-model:variant"):
            with self.subTest(model=identifier):
                client = load_model(identifier, "test-key", 10, endpoint=ENDPOINT)
                self.assertIs(type(client), ChoiceModel)
                self.assertEqual(client.model_id, identifier)

    def test_adapter_can_decode_other_questions_using_shared_http(self):
        class Client(DecisionsClient):
            def parse_response(self, body, payload):
                self.payload_seen = payload
                return Decision(body["control"], "test/custom", usage=body["usage"])

        async def check():
            client = Client("test-key", 10, endpoint=ENDPOINT, transport=httpx.MockTransport(lambda request:
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

    def test_adapter_binds_model_and_exposes_trace_without_wire_assumptions(self):
        obs = Observation(np.zeros((240, 256, 3), dtype=np.uint8), {"x_pos": 40})
        request = load_model(MODEL_ID, "test-key", 10, endpoint=ENDPOINT).build_request(obs, encode_png(obs), frames=0)
        self.assertEqual(request.payload["model"], MODEL_ID)
        self.assertEqual(request.trace["context"]["progress"], {"x": 40})
        self.assertEqual(request.trace["questions"], request.payload["questions"])
        self.assertNotIn("test-key", repr(request))

    def test_models_share_multimodal_prompt_and_transport(self):
        obs = Observation(np.full((240, 256, 3), [123, 45, 67], dtype=np.uint8), {"x_pos": 40})
        for context in (None, {"execution_mode": "realtime", "recent_response_frames": 15},
                {"execution_mode": "realtime", "control_mode": "buttons", "recent_response_frames": 15}):
            with self.subTest(context=context):
                request = load_model("test/second", "test-key", 10, endpoint=ENDPOINT).build_request(obs, encode_png(obs), frames=0,
                    control_context=context)
                baseline = load_model(MODEL_ID, "test-key", 10, endpoint=ENDPOINT).build_request(obs, encode_png(obs), frames=0,
                    control_context=context)
                self.assertEqual(request.payload["model"], "test/second")
                self.assertEqual(request.payload["state"][0], baseline.payload["state"][0])
                self.assertEqual(request.trace["context"], baseline.trace["context"])
                question = request.payload["questions"]["next_action"]
                self.assertEqual(question["criteria"], baseline.payload["questions"]["next_action"]["criteria"])
                self.assertTrue(question["instructions"].startswith(baseline.payload["questions"]["next_action"]["instructions"]))
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
                return httpx.Response(200, json={"model": "test/second",
                    "answers": {"next_action": {"type": "choice", "choice": "right"}}})
            client = ChoiceModel("test-key", 10, model_id="test/second", endpoint=ENDPOINT, transport=httpx.MockTransport(respond))
            try:
                decision = await client.decide(request.payload)
                self.assertEqual(decision.move, "right")
                self.assertEqual(decision.model, "test/second")
            finally:
                await client.aclose()

        asyncio.run(check_transport())

    def test_model_selection_precedence_and_required_fields(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch("supermairio.config.PROJECT_ROOT", Path(directory)), patch.dict(os.environ, {}, clear=True):
            self.assertEqual(parse_config(["--mode", "demo"]).mode, "demo")
            self.assertEqual(parse_config(["--mode", "manual"]).mode, "manual")
            with patch("sys.stdout", io.StringIO()), self.assertRaises(SystemExit) as help_exit:
                parse_config(["--help"])
            self.assertEqual(help_exit.exception.code, 0)
            for env in ({}, {"SUPERMAIRIO_MODEL": MODEL_ID}, {"SUPERMAIRIO_ENDPOINT": ENDPOINT}):
                with patch.dict(os.environ, env, clear=True), patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
                    parse_config([])
            envfile = Path(directory, ".env")
            envfile.write_text(f"SUPERMAIRIO_MODEL={MODEL_ID}\nSUPERMAIRIO_ENDPOINT={ENDPOINT}\n", encoding="utf-8")
            self.assertEqual(parse_config([]).model, MODEL_ID)
            self.assertNotIn("SUPERMAIRIO_MODEL", os.environ)
            with patch.dict(os.environ, {"SUPERMAIRIO_MODEL": "test/env"}):
                self.assertEqual(parse_config([]).model, "test/env")
                self.assertEqual(parse_config(["--model", "test/cli"]).model, "test/cli")

    @patch.dict("supermairio.config.os.environ", MODEL_ENV)
    def test_any_model_id_uses_the_shared_adapter(self):
        self.assertEqual(parse_config(["--model", "not_configured"]).model, "not_configured")
        client = load_model("vendor/unlisted:variant", "test-key", 10, endpoint=ENDPOINT)
        self.assertIs(type(client), ChoiceModel)
        self.assertEqual(client.model_id, "vendor/unlisted:variant")
        self.assertEqual(parse_config(["--mode", "demo", "--model", "not_configured"]).mode, "demo")

if __name__ == "__main__":
    unittest.main()
