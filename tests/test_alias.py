from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace


PLUGIN_DIR = Path(__file__).resolve().parents[1]
PLUGIN_FILE = PLUGIN_DIR / "__init__.py"


spec = importlib.util.spec_from_file_location(
    "xai_tool_search_alias_plugin", PLUGIN_FILE
)
assert spec is not None and spec.loader is not None
plugin = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plugin
spec.loader.exec_module(plugin)


def _chat_tool(name: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": f"{name} description",
            "parameters": {"type": "object"},
        },
    }


def _responses_tool(name: str) -> dict:
    return {
        "type": "function",
        "name": name,
        "description": f"{name} description",
        "parameters": {"type": "object"},
    }


def test_request_aliases_bridge_and_avoids_real_tool_collision():
    request = {
        "model": "grok-4.6",
        "messages": [{"role": "user", "content": "find something"}],
        "tools": [_chat_tool("tool_search"), _chat_tool("hermes_tool_search")],
    }
    original = plugin._deepcopy(request)

    result = plugin._on_llm_request(
        request=request,
        original_request=original,
        provider="xai-oauth",
        api_mode="chat_completions",
    )

    assert result is not None
    wire_request = result["request"]
    assert [
        tool["function"]["name"] for tool in wire_request["tools"]
    ] == ["hermes_tool_search__1", "hermes_tool_search"]
    assert request == original


def test_request_rewrites_chat_history_tool_names_without_touching_schema_names():
    request = {
        "model": "grok-4.6",
        "messages": [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "tool_search", "arguments": "{}"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call-1",
                "name": "tool_search",
                "content": "{}",
            },
        ],
        "tools": [_chat_tool("tool_search")],
    }

    result = plugin._on_llm_request(
        request=request,
        original_request=plugin._deepcopy(request),
        provider="xai-oauth",
        api_mode="chat_completions",
    )
    wire_request = result["request"]

    assert wire_request["messages"][0]["tool_calls"][0]["function"]["name"] == "hermes_tool_search"
    assert wire_request["messages"][1]["name"] == "hermes_tool_search"
    assert wire_request["messages"][1]["content"] == "{}"


def test_responses_request_and_response_round_trip():
    original = {
        "model": "grok-4.6",
        "input": [
            {"type": "function_call", "call_id": "fc_1", "name": "tool_search", "arguments": "{}"}
        ],
        "tools": [_responses_tool("tool_search")],
    }
    result = plugin._on_llm_request(
        request=plugin._deepcopy(original),
        original_request=original,
        provider="xai-oauth",
        api_mode="codex_responses",
    )
    wire_request = result["request"]
    assert wire_request["tools"][0]["name"] == "hermes_tool_search"
    assert wire_request["input"][0]["name"] == "hermes_tool_search"

    raw_response = SimpleNamespace(
        output=[
            SimpleNamespace(
                type="function_call",
                call_id="fc_1",
                name="hermes_tool_search",
                arguments="{}",
            )
        ]
    )
    seen = {}

    def next_call(request):
        seen["request"] = request
        return raw_response

    response = plugin._on_llm_execution(
        request=wire_request,
        original_request=original,
        next_call=next_call,
        provider="xai-oauth",
        api_mode="codex_responses",
    )

    assert seen["request"] is wire_request
    assert response.output[0].name == "tool_search"


def test_chat_response_round_trip():
    original = {
        "model": "grok-4.6",
        "messages": [{"role": "user", "content": "search"}],
        "tools": [_chat_tool("tool_search")],
    }
    wire_request = plugin._on_llm_request(
        request=plugin._deepcopy(original),
        original_request=original,
        provider="xai-oauth",
        api_mode="chat_completions",
    )["request"]
    raw_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    tool_calls=[
                        SimpleNamespace(
                            function=SimpleNamespace(
                                name="hermes_tool_search", arguments="{}"
                            )
                        )
                    ]
                )
            )
        ]
    )

    response = plugin._on_llm_execution(
        request=wire_request,
        original_request=original,
        next_call=lambda request: raw_response,
        provider="xai-oauth",
        api_mode="chat_completions",
    )

    assert response.choices[0].message.tool_calls[0].function.name == "tool_search"


def test_non_xai_and_real_same_named_tool_are_left_alone():
    request = {
        "model": "gpt-5.6",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [_chat_tool("hermes_tool_search")],
    }
    result = plugin._on_llm_request(
        request=request,
        original_request=plugin._deepcopy(request),
        provider="openai-codex",
        api_mode="codex_responses",
    )
    assert result is None

    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    tool_calls=[
                        SimpleNamespace(
                            function=SimpleNamespace(
                                name="hermes_tool_search", arguments="{}"
                            )
                        )
                    ]
                )
            )
        ]
    )
    returned = plugin._on_llm_execution(
        request=request,
        original_request=request,
        next_call=lambda request: response,
        provider="openai-codex",
        api_mode="chat_completions",
    )
    assert returned.choices[0].message.tool_calls[0].function.name == "hermes_tool_search"


def test_xai_request_already_using_upstream_alias_is_a_noop():
    request = {
        "model": "grok-4.6",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [_chat_tool("hermes_tool_search")],
    }

    result = plugin._on_llm_request(
        request=request,
        original_request=plugin._deepcopy(request),
        provider="xai-oauth",
        api_mode="chat_completions",
    )

    assert result is None
