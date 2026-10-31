"""Jev 1.14 multimodal Choice controller, served by OpenRouter Decisions.

Its minimum image size is applied to every model by the shared adapter.
"""

from app.models._choice import ChoiceModel

MODEL_ID = "typesafe/jev-1.14"


class Model(ChoiceModel):
    model_id = MODEL_ID
