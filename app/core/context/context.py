from contextvars import ContextVar
from typing import Any, Dict

# Generic context dictionary to store any key-value pairs (trace id, …)
context_vars: Dict[str, ContextVar[Any]] = {}


def get_context_value(key: str, default: Any = None) -> Any:
    if key not in context_vars:
        return default
    return context_vars[key].get(default)


def set_context_value(key: str, value: Any) -> None:
    if key not in context_vars:
        context_vars[key] = ContextVar(key, default=None)
    context_vars[key].set(value)
