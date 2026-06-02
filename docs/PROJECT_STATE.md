# PROJECT_STATE

## 当前状态

本次任务是非阶段任务，不属于 Phase 3.3，也不表示 smart retrieval、context budget、symbol index 或 recent files 已经开始。

当前已经完成“第二次编排重构”：`agent_loop.py` 现在主要负责按顺序组织一次 agent turn 的主流程，把上下文构建、模型消息构建、模型调用、模型回复路由和工具层执行分别交给独立接口承接。

当前正式工具调用链仍然是：

```text
main -> run_agent_loop -> run_agent_turn -> ToolGateway.handle_many -> ToolGateway.handle -> tool_guard.prepare_tool_request -> tool.execute
```

## 本轮主流程

一次用户输入进入 `run_agent_loop` 后，会先写入 `Conversation`。随后 `run_agent_turn` 在每一轮中依次调用 `ContextProvider.build`、`build_model_messages`、`ModelRunner.call`、`route_assistant_message`。如果模型返回最终回答，就写回 assistant 消息并结束；如果模型返回工具调用，就交给 `ToolGateway.handle_many` 执行，再把工具结果写回 conversation，进入下一轮。

`ContextProvider` 当前只是接口整理，占位返回空上下文；它没有接入 repo map、AGENTS.md 注入、smart retrieval 或上下文预算。

## 本轮代码文件和函数说明

`src/wdcode/core/agent_loop.py`

- `run_agent_loop(client, tool_registry=None)` 是 CLI agent 主循环入口。它读取用户输入，处理退出命令，把用户消息写入 conversation，并调用 `run_agent_turn` 完成一次模型交互。
- `run_agent_turn(...)` 是单次 agent turn 的编排函数。它保留旧入口兼容性，但现在主要按模块接口组织流程：构建上下文、构建模型消息、调用模型、路由回复、执行工具或返回最终回答。
- `_handle_tool_calls(conversation, route, tool_gateway, trace_writer=None)` 负责处理一轮模型返回的工具调用。它检查工具层是否可用和单轮工具数量限制，写入 assistant tool-call 消息，调用 `ToolGateway.handle_many`，并把每个工具结果写回 conversation。
- `_trace_assistant_message(trace_writer, route)` 负责记录 assistant 消息级 trace。它保留模型原始 `content` 的记录方式，同时使用 route 判断是否包含工具调用。
- `_trace_tool_call(trace_writer, tool_call)` 负责记录单个工具调用的 trace，包括调用 id、工具名和解析后的参数。
- `_write_trace(trace_writer, event_type, payload)` 是 trace 写入的小封装；没有 trace writer 时不做任何事。
- `_trace_tool_arguments(tool_call)` 负责把工具调用中的 JSON 参数解析成对象，解析失败时保留原始字符串，方便 trace 仍能记录异常输入。
- `_tool_name(tool_call)` 负责从模型 tool call 结构中取出函数名，避免主流程重复写嵌套字段访问。

`src/wdcode/context/provider.py`

- `ContextBundle` 是上下文结果的数据结构，目前只有 `text` 字段，默认是空字符串。
- `ContextProvider.build(user_input, conversation)` 是上下文构建接口。目前返回空 `ContextBundle`，只为后续上下文能力预留稳定入口。

`src/wdcode/core/message_builder.py`

- `build_model_messages(conversation, context=None)` 负责把 conversation 转成模型输入消息。当前在空上下文下保持旧行为，直接返回 `conversation.as_messages()`。

`src/wdcode/core/model_runner.py`

- `ModelRunner.__init__(client)` 保存模型客户端实例。
- `ModelRunner.call(messages, tools=None)` 负责调用 `client.chat(messages, tools=tools)`，让 `agent_loop.py` 不直接依赖客户端调用细节。

`src/wdcode/core/response_router.py`

- `AssistantRoute` 是模型回复路由结果。它记录是否是最终回答、归一化后的内容、稳定 tuple 形式的工具调用，以及原始 assistant 消息。
- `route_assistant_message(assistant_message)` 负责判断模型回复是最终回答还是工具调用。没有 `tool_calls` 时视为最终回答，有 `tool_calls` 时进入工具路径；`content` 会归一化为字符串。

`src/wdcode/tools/gateway.py`

- `ToolGateway.__init__(registry, project_root=None, approval_mode="auto")` 保存工具注册表、项目根目录和 approval 模式。
- `ToolGateway.schemas()` 返回工具 schema，供模型调用前传入。
- `ToolGateway.handle(tool_call)` 处理单个工具调用。它仍然通过 `tool_guard.prepare_tool_request` 做校验和准备，再执行具体工具，并把结果统一封装成 `ToolResult`。
- `ToolGateway._failure(error, tool_name="", stage="execution", dry_run=False)` 负责生成统一失败结果。
- `ToolGateway.handle_many(tool_calls)` 是本轮新增的批量工具入口。它按顺序逐个调用 `handle`，让 `agent_loop.py` 只面对工具层入口，而不关心工具层内部细节。

## 本轮测试说明

- `tests/test_response_router.py` 覆盖 final answer、空内容归一化和 tool calls tuple 化。
- `tests/test_message_builder.py` 覆盖空上下文下模型消息保持旧行为，并确认不会改写 conversation。
- `tests/test_model_runner.py` 覆盖 `ModelRunner` 对 `client.chat` 的委托调用。
- `tests/test_agent_loop_orchestration.py` 覆盖 `run_agent_turn` 的上下文接口调用、工具轮数停止和单轮工具数量限制。
- `tests/test_tool_gateway.py` 新增 `handle_many` 顺序返回测试。

## 尚未开始

- smart retrieval
- context budget
- recent files
- symbol index
- eval task skeleton
- Phase 3.3

## 明确推迟

- TUI
- MCP
- 多 agent
- 长期 memory
- VS Code 插件
- 大规模重构

## API Key Policy

默认测试不需要真实 API key。本项目不读取、不打印、不提交 `.env` 或真实密钥。未来 live LLM 测试必须显式标记，并在环境变量不存在时自动跳过。

## 当前验证命令

当前主要验证命令仍然是：

```bash
python -m pytest
```
