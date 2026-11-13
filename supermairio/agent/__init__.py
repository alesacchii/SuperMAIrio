"""The model side of the loop: one shared adapter for every Decisions-compatible model."""

from typing import Protocol

from supermairio.contracts import Decision, DecisionRequest, Observation


class ModelController(Protocol):
    """What the runners need from a model. `ChoiceModel` is the implementation every model uses."""

    model_id: str

    def build_request(self, observation: Observation, png: bytes | None, *, frames: int,
                      previous_move=None, previous_position=None, control_context=None) -> DecisionRequest: ...

    async def decide(self, payload: dict) -> Decision: ...


def load_model(model: str | None, api_key: str | None, timeout: float, *, endpoint: str | None) -> ModelController:
    """Same instructions, state, options and image for every model: only the ID changes."""
    from supermairio.agent.prompt import ChoiceModel
    from supermairio.config import validate_model_connection

    endpoint = validate_model_connection(model, endpoint)
    return ChoiceModel(api_key, timeout, model_id=model, endpoint=endpoint)
