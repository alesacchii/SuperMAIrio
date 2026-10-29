"""Discover model adapters from their modules, without a manual registry."""

from importlib import import_module
from pkgutil import iter_modules
from typing import Protocol

from app.contracts import Decision, DecisionRequest, Observation


class ModelController(Protocol):
    model_id: str

    def build_request(self, observation: Observation, png: bytes | None, *, frames: int,
                      previous_move=None, previous_position=None, control_context=None) -> DecisionRequest: ...

    async def decide(self, payload: dict) -> Decision: ...


def model_classes() -> dict[str, type[ModelController]]:
    """Public .py modules each export Model with a unique OpenRouter model_id."""
    models = {}
    for module_info in sorted(iter_modules(__path__), key=lambda item: item.name):
        if module_info.ispkg or module_info.name.startswith("_"):
            continue
        module = import_module(f"{__name__}.{module_info.name}")
        adapter = getattr(module, "Model", None)
        if not isinstance(adapter, type) or not isinstance(getattr(adapter, "model_id", None), str) or not adapter.model_id.strip():
            raise ValueError(f"Il modulo models/{module_info.name}.py deve esporre Model con model_id")
        if not callable(getattr(adapter, "build_request", None)) or not callable(getattr(adapter, "decide", None)):
            raise ValueError(f"Model in models/{module_info.name}.py deve implementare build_request e decide")
        for identifier in (module_info.name, adapter.model_id):
            if identifier in models and models[identifier] is not adapter:
                raise ValueError(f"Identificativo del modello duplicato: {identifier}")
            models[identifier] = adapter
    return models


def get_model_class(identifier: str) -> type[ModelController]:
    models = model_classes()
    try:
        return models[identifier]
    except KeyError as exc:
        available = ", ".join(sorted(models))
        raise ValueError(f"Modello non configurato: {identifier}. Disponibili: {available}") from exc


def load_model(identifier: str, api_key: str, timeout: float) -> ModelController:
    return get_model_class(identifier)(api_key, timeout)
