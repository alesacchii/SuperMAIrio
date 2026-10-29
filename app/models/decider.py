"""Perplexity Decider V1.2 using the shared multimodal Choice protocol.

https://openrouter.ai/perplexity/pplx-decider-v1.2/
"""

from app.models._choice import ChoiceModel

MODEL_ID = "perplexity/pplx-decider-v1.2"


class Model(ChoiceModel):
    model_id = MODEL_ID
