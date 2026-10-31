"""Explicit opt-in: real paid calls, first image interpretation then game loop."""

import asyncio
import os
import unittest

import numpy as np

from app.config import openrouter_key, parse_config
from app.contracts import Observation
from app.models import load_model
from app.openrouter import encode_png
from app.runner import run


@unittest.skipUnless(os.environ.get("SUPERMAIRIO_TEST_OPENROUTER") == "1", "requires explicit opt-in and OpenRouter credit")
class OpenRouterLiveTests(unittest.TestCase):
    def test_image_interpretation_then_short_game_session(self):
        config = parse_config(["--execution-mode", "paused", "--headless", "--max-frames", "12", "--save-screenshots"])
        asyncio.run(self.check_images(config))
        run(config)

    async def check_images(self, config):
        client = load_model(config.model, openrouter_key(), config.request_timeout)
        try:
            await self.classify_colors(client)
        finally:
            await client.aclose()

    async def classify_colors(self, client):
        for color, expected in (([255, 0, 0], "walk_left"), ([0, 0, 255], "walk_right")):
            rgb = np.full((240, 256, 3), color, dtype=np.uint8)
            obs = Observation(rgb, {})
            payload = client.build_request(obs, encode_png(obs), frames=0).payload
            # No text identifying the color: the answer must depend on the pixels.
            payload["state"][0]["text"] = "Inspect the attached image. Which color fills it?"
            payload["questions"]["next_action"] = {
                "type": "choice", "instructions": "Select the dominant color visible in the image.",
                "criteria": {"walk_left": "Red", "walk_right": "Blue", "wait": "Green"},
            }
            decision = await client.decide(payload)
            self.assertEqual(decision.move, expected, "Provider did not interpret the embedded image correctly")


if __name__ == "__main__":
    unittest.main()
