# hermes-xai-tool-search-alias

English · [中文](README.zh-CN.md)

Community workaround for [Hermes Agent #95003](https://github.com/NousResearch/hermes-agent/issues/95003):

```text
HTTP 400: The function name tool_search is reserved for the tool_search tool
```

This is **not** a Hermes core patch. Hermes keeps the canonical internal name `tool_search`. The plugin rewrites only the xAI wire payload:

```text
Hermes: tool_search
xAI:    hermes_tool_search
```

It covers xAI Responses (`codex_responses`) and Chat Completions, restores the returned function name before Hermes dispatches the tool, and uses `hermes_tool_search__1` when a real user tool already occupies `hermes_tool_search`.

## Install

CLI:

```bash
hermes plugins install soulYANG/hermes-xai-tool-search-alias --enable
```

Desktop one-click (confirmation dialog, not silent):

```text
hermes://plugin/install?repo=soulYANG/hermes-xai-tool-search-alias&enable=1
```

Then start a **new session** or restart Hermes Desktop / Gateway. Enabling a plugin does not rewrite an already-running process.

Pin a commit if you want a reproducible install:

```bash
hermes plugins install soulYANG/hermes-xai-tool-search-alias --enable --ref <40-char-sha>
```

## Uninstall

```bash
hermes plugins disable xai-tool-search-alias
hermes plugins remove xai-tool-search-alias
```

After a Hermes core fix ships, disable/remove this plugin. It is a no-op if the outbound request no longer contains canonical `tool_search`.

## Behavior

Active only when:

- provider is `xai` or `xai-oauth`, or the base URL host is `api.x.ai` / `*.x.ai`
- API mode is `codex_responses` or `chat_completions`
- the original request still declares Hermes' canonical `tool_search`

The alias map is request-scoped. It is never stored on the transport instance and is never sent to the SDK.

`tool_describe` and `tool_call` are left unchanged.

## Verify

```bash
hermes plugins doctor "$PWD" --ci
python -m pytest tests/test_alias.py -q -o 'addopts='
```

## Limits

- Hermes middleware is fail-open: if this plugin raises, the original (invalid on xAI) request may still be sent.
- This does not enable xAI native tool search.
- Review the source before enabling third-party plugins. Index inclusion, if any, is metadata review, not a code audit.

## License

MIT
