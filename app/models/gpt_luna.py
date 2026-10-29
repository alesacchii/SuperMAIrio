"""GPT Luna adapter using the shared game protocol."""

from app.models._choice import ChoiceModel, build_payload

MODEL_ID = "openai/gpt-6-luna-decisions"


class Model(ChoiceModel):
    model_id = MODEL_ID
