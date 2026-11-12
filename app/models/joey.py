"""Baseten Joey 1 using the shared Choice protocol.

https://openrouter.ai/baseten/joey-1
"""

from app.models._choice import ChoiceModel

MODEL_ID = "baseten/joey-1"


class Model(ChoiceModel):
    model_id = MODEL_ID
