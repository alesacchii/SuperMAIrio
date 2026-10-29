"""Jev 1.14 multimodal Choice controller, served by OpenRouter Decisions."""

from io import BytesIO

from PIL import Image, ImageOps

from app.models._choice import ChoiceModel

MODEL_ID = "typesafe/jev-1.14"
# Jev requires sides >=256 and area >=78,400 pixels (280 squared).
# https://docs.typesafe.ai/images#limits
MIN_IMAGE_SIDE = 280


class Model(ChoiceModel):
    """Use the shared game prompt; pad NES screenshots to Jev's minimum dimensions."""

    model_id = MODEL_ID

    def build_request(self, observation, png, *, frames, previous_move=None, previous_position=None, control_context=None):
        if png is None:
            return super().build_request(observation, png, frames=frames,
                previous_move=previous_move, previous_position=previous_position, control_context=control_context)
        with Image.open(BytesIO(png)) as image:
            source_size = image.size
            right = max(0, MIN_IMAGE_SIDE - image.width)
            bottom = max(0, MIN_IMAGE_SIDE - image.height)
            if right or bottom:
                output = BytesIO()
                ImageOps.expand(image, border=(0, 0, right, bottom), fill=0).save(output, format="PNG")
                png = output.getvalue()
        request = super().build_request(observation, png, frames=frames,
            previous_move=previous_move, previous_position=previous_position, control_context=control_context)
        request.trace["image_preprocessing"] = {
            "source_size": list(source_size), "sent_size": [source_size[0] + right, source_size[1] + bottom],
            "padding_right": right, "padding_bottom": bottom,
        }
        if right or bottom:
            for question in request.payload["questions"].values():
                question["instructions"] += (f" The screenshot has {right} black padding columns on the right and "
                    f"{bottom} black padding rows at the bottom. Ignore this padding; game pixels and coordinates are unchanged.")
        return request
