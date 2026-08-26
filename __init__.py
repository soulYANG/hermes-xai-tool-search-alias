"""Collision-safe xAI wire aliases for Hermes' deferred tool-search bridge.

Hermes keeps ``tool_search`` as its canonical internal name. xAI reserves that
function name at the API boundary, so this plugin rewrites only xAI request
payloads and restores the name on the raw response before Hermes normalizes or
dispatches the tool call.

The plugin deliberately has no mutable module or transport state. Every
request/response pair derives its alias plan from ``original_request``.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import logging
from typing import Any, Dict, Iterable, Mapping, Optional
from urllib.parse import urlparse


logger = logging.getLogger(__name__)

PLUGIN_NAME = "xai-tool-search-alias"
CANONICAL_TOOL_NAME = "tool_search"
PREFERRED_WIRE_NAME = "hermes_tool_search"
SUPPORTED_API_MODES = frozenset({"codex_responses", "chat_completions"})
XAI_PROVIDERS = frozenset({"xai", "xai-oauth"})


@dataclass(frozen=True)
class AliasPlan:
    """Request-scoped forward and reverse alias maps."""

    internal_to_wire: Dict[str, str]
    wire_to_internal: Dict[str, str]

    def __bool__(self) -> bool:
        return bool(self.internal_to_wire)


def _deepcopy(value: Any) -> Any:
    """Copy JSON-shaped request/response data without sharing nested dicts."""
    try:
        return deepcopy(value)
    except Exception:
        if isinstance(value, dict):
            return {key: _deepcopy(item) for key, item in value.items()}
        if isinstance(value, list):
            return [_deepcopy(item) for item in value]
        if isinstance(value, tuple):
            return tuple(_deepcopy(item) for item in value)
        return value


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _set(value: Any, key: str, new_value: Any) -> bool:
    if isinstance(value, dict):
        value[key] = new_value
        return True
    try:
        setattr(value, key, new_value)
        return True
    except Exception:
        return False


def _items(value: Any) -> Iterable[Any]:
    if isinstance(value, (list, tuple)):
        return value
    return ()


def _tool_name(tool: Any) -> Optional[str]:
    """Read Chat Completions and Responses function-tool shapes."""
    function = _get(tool, "function")
    nested_name = _get(function, "name")
    if isinstance(nested_name, str):
        return nested_name
    direct_name = _get(tool, "name")
    return direct_name if isinstance(direct_name, str) else None


def _set_tool_name(tool: Any, name: str) -> bool:
    function = _get(tool, "function")
    if isinstance(_get(function, "name"), str):
        return _set(function, "name", name)
    if isinstance(_get(tool, "name"), str):
        return _set(tool, "name", name)
    return False


def _declared_tool_names(request: Any) -> list[str]:
    return [
        name
        for tool in _items(_get(request, "tools"))
        if isinstance(name := _tool_name(tool), str)
    ]


def _build_alias_plan(request: Any) -> AliasPlan:
    """Build a collision-safe alias map from one original request."""
    declared_names = _declared_tool_names(request)
    if CANONICAL_TOOL_NAME not in declared_names:
        return AliasPlan({}, {})

    occupied = set(declared_names)
    wire_name = PREFERRED_WIRE_NAME
    suffix = 1
    while wire_name in occupied:
        wire_name = f"{PREFERRED_WIRE_NAME}__{suffix}"
        suffix += 1

    return AliasPlan(
        internal_to_wire={CANONICAL_TOOL_NAME: wire_name},
        wire_to_internal={wire_name: CANONICAL_TOOL_NAME},
    )


def _is_xai_request(*, provider: Any, base_url: Any, api_mode: Any) -> bool:
    mode = str(api_mode or "").strip().lower()
    if mode not in SUPPORTED_API_MODES:
        return False

    provider_name = str(provider or "").strip().lower().replace("_", "-")
    if provider_name in XAI_PROVIDERS:
        return True

    raw_base_url = str(base_url or "").strip()
    if not raw_base_url:
        return False
    parsed = urlparse(raw_base_url if "://" in raw_base_url else f"//{raw_base_url}")
    host = (parsed.hostname or "").lower().rstrip(".")
    return host == "api.x.ai" or host.endswith(".x.ai")


def _rewrite_chat_messages(messages: Any, plan: AliasPlan) -> None:
    for message in _items(messages):
        for tool_call in _items(_get(message, "tool_calls")):
            function = _get(tool_call, "function")
            name = _get(function, "name")
            if isinstance(name, str) and name in plan.internal_to_wire:
                _set(function, "name", plan.internal_to_wire[name])

        # Some Chat Completions histories carry the function name directly on
        # a tool message. Restrict this to assistant/tool roles so arbitrary
        # user-message metadata named "name" is never rewritten.
        role = _get(message, "role")
        if role in {"assistant", "tool"}:
            name = _get(message, "name")
            if isinstance(name, str) and name in plan.internal_to_wire:
                _set(message, "name", plan.internal_to_wire[name])


def _rewrite_responses_input(items: Any, plan: AliasPlan) -> None:
    for item in _items(items):
        item_type = _get(item, "type")
        if item_type not in {"function_call", "tool_call"}:
            continue
        name = _get(item, "name")
        if isinstance(name, str) and name in plan.internal_to_wire:
            _set(item, "name", plan.internal_to_wire[name])


def _rewrite_request(request: Any, plan: AliasPlan) -> Any:
    rewritten = _deepcopy(request)

    for tool in _items(_get(rewritten, "tools")):
        name = _tool_name(tool)
        if isinstance(name, str) and name in plan.internal_to_wire:
            _set_tool_name(tool, plan.internal_to_wire[name])

    _rewrite_chat_messages(_get(rewritten, "messages"), plan)
    _rewrite_responses_input(_get(rewritten, "input"), plan)
    return rewritten


def _restore_function_name(container: Any, plan: AliasPlan) -> None:
    function = _get(container, "function")
    nested_name = _get(function, "name")
    if isinstance(nested_name, str) and nested_name in plan.wire_to_internal:
        _set(function, "name", plan.wire_to_internal[nested_name])

    item_type = _get(container, "type")
    direct_name = _get(container, "name")
    if (
        item_type in {"function_call", "tool_call"}
        and isinstance(direct_name, str)
        and direct_name in plan.wire_to_internal
    ):
        _set(container, "name", plan.wire_to_internal[direct_name])


def _restore_response(response: Any, plan: AliasPlan) -> Any:
    """Restore aliases in Responses and Chat Completions response shapes."""
    for item in _items(_get(response, "output")):
        _restore_function_name(item, plan)

    for choice in _items(_get(response, "choices")):
        message = _get(choice, "message")
        for tool_call in _items(_get(message, "tool_calls")):
            _restore_function_name(tool_call, plan)

        # Streaming chunks use delta.tool_calls. Hermes normally aggregates
        # them first, but handling the shape here keeps the middleware safe for
        # callers that invoke it directly.
        delta = _get(choice, "delta")
        for tool_call in _items(_get(delta, "tool_calls")):
            _restore_function_name(tool_call, plan)

    return response


def _on_llm_request(
    *,
    request: Any,
    original_request: Any,
    provider: Any = "",
    base_url: Any = "",
    api_mode: Any = "",
    **_: Any,
) -> Optional[dict[str, Any]]:
    if not _is_xai_request(provider=provider, base_url=base_url, api_mode=api_mode):
        return None

    plan = _build_alias_plan(original_request)
    if not plan:
        return None

    return {
        "request": _rewrite_request(request, plan),
        "source": PLUGIN_NAME,
        "reason": f"alias {CANONICAL_TOOL_NAME} for xAI wire compatibility",
    }


def _on_llm_execution(
    *,
    request: Any,
    original_request: Any,
    next_call: Any,
    provider: Any = "",
    base_url: Any = "",
    api_mode: Any = "",
    **_: Any,
) -> Any:
    plan = (
        _build_alias_plan(original_request)
        if _is_xai_request(provider=provider, base_url=base_url, api_mode=api_mode)
        else AliasPlan({}, {})
    )

    response = next_call(request)
    if plan:
        _restore_response(response, plan)
    return response


def register(ctx: Any) -> None:
    """Register both halves of the provider-boundary compatibility layer."""
    ctx.register_middleware("llm_request", _on_llm_request)
    ctx.register_middleware("llm_execution", _on_llm_execution)
