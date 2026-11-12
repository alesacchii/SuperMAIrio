"""Google Gemini Decision 1 using the shared multimodal Choice protocol.

https://openrouter.ai/google/gemini-decision-1
"""

from app.models._choice import ChoiceModel

MODEL_ID = "google/gemini-decision-1"


class Model(ChoiceModel):
    model_id = MODEL_ID
