"""Explicit opt-in: real paid calls, first image interpretation then game loop."""

import asyncio
import os
import unittest

import numpy as np

from supermairio.config import decisions_key, parse_config
from supermairio.contracts import Observation
from supermairio.agent import load_model
from supermairio.agent.client import encode_png
from supermairio.runtime.play import run


@unittest.skipUnless(os.environ.get("SUPERMAIRIO_TEST_LIVE") == "1", "requires explicit opt-in and may incur provider charges")
class DecisionsLiveTests(unittest.TestCase):
    def test_image_interpretation_then_short_game_session(self):
        config = parse_config(["--execution-mode", "paused", "--headless", "--max-frames", "12", "--save-screenshots"])
        asyncio.run(self.check_images(config))
        run(config)

    async def check_images(self, config):
        client = load_model(config.model, decisions_key(config.endpoint), config.request_timeout, endpoint=config.endpoint)
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
