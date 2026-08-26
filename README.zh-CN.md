# hermes-xai-tool-search-alias

[English](README.md) · 中文

这是 [Hermes Agent #95003](https://github.com/NousResearch/hermes-agent/issues/95003) 的社区临时方案：

```text
HTTP 400: The function name tool_search is reserved for the tool_search tool
```

这**不是** Hermes 核心补丁。Hermes 内部仍使用规范名 `tool_search`。插件只改 xAI 线上请求：

```text
Hermes 内部：tool_search
xAI 线上：  hermes_tool_search
```

覆盖 xAI Responses（`codex_responses`）和 Chat Completions。模型返回后再把名字还原，Hermes 才分发工具。如果用户真实工具已经占用 `hermes_tool_search`，桥接工具会改成 `hermes_tool_search__1`。

## 安装

命令行：

```bash
hermes plugins install soulYANG/hermes-xai-tool-search-alias --enable
```

Desktop 一键安装（会弹出确认框，不会静默安装）：

```text
hermes://plugin/install?repo=soulYANG/hermes-xai-tool-search-alias&enable=1
```

然后**新开会话**，或重启 Hermes Desktop / Gateway。启用插件不会改写已经在跑的进程。

如果要锁定版本：

```bash
hermes plugins install soulYANG/hermes-xai-tool-search-alias --enable --ref <40位commit SHA>
```

## 卸载

```bash
hermes plugins disable xai-tool-search-alias
hermes plugins remove xai-tool-search-alias
```

Hermes 上游修好后，关掉或卸掉这个插件即可。如果出站请求里已经没有规范名 `tool_search`，插件会自动 no-op。

## 行为

只在以下情况生效：

- provider 是 `xai` 或 `xai-oauth`，或 base URL 主机是 `api.x.ai` / `*.x.ai`
- API 模式是 `codex_responses` 或 `chat_completions`
- 原始请求里仍然声明了 Hermes 的规范名 `tool_search`

别名映射按单次请求计算，不放在 transport 实例上，也不会发给 SDK。

`tool_describe` 和 `tool_call` 保持原名。

## 验证

```bash
hermes plugins doctor "$PWD" --ci
python -m pytest tests/test_alias.py -q -o 'addopts='
```

## 限制

- Hermes middleware 是 fail-open：插件如果抛错，原来那份对 xAI 非法的请求仍可能被发出去。
- 这不会启用 xAI 原生 tool search。
- 启用第三方插件前请自己看源码。即便进入社区索引，审的也只是元数据，不是代码审计。

## 许可证

MIT
