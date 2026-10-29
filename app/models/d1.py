"""Liquid d1.1 using the shared multimodal Choice protocol.

https://openrouter.ai/liquid/d1.1
"""

from app.models._choice import ChoiceModel

MODEL_ID = "liquid/d1.1"


class Model(ChoiceModel):
    model_id = MODEL_ID
