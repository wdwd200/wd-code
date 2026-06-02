# PROJECT_STATE

## 当前状态

本次任务是非阶段任务，不属于 Phase 3.3，也不表示 smart retrieval、context budget、symbol index 或 recent files 已经开始。

当前已经完成“第三次编排重构”：`run_agent_turn` 已完全移除，`run_agent_loop` 现在是唯一主编排函数。主流程不再外包给中间 turn 函数，而是在 `run_agent_loop` 中直接按接口顺序组织。

当前正式工具调用链是：

```text
main -> run_agent_loop -> ToolGateway.handle_many -> ToolGateway.handle -> tool_guard.prepare_tool_request -> tool.execute
```

## 当前主流程

一次用户输入进入 `run_agent_loop` 后，会先写入 `Conversation`。随后同一个主循环在每一轮中依次调用 `ContextProvider.build`、`build_model_messages`、`ModelRunner.call`、`route_assistant_message`。如果模型返回最终回答，就写回 assistant 消息并输出；如果模型返回工具调用，就交给 `ToolGateway.handle_many` 执行，再把工具结果写回 conversation，进入下一轮模型调用。

`ContextProvider` 当前只是接口整理，占位返回空上下文；它没有接入 repo map、AGENTS.md 注入、smart retrieval 或上下文预算。

## 当前代码文件和函数说明

`src/wdcode/core/agent_loop.py`

- `run_agent_loop(client, tool_registry=None, ...)` 是唯一 agent 主编排函数。它读取用户输入，处理退出命令，把用户消息写入 conversation，并直接组织上下文构建、模型消息构建、模型调用、回复路由、工具执行、工具结果写回、最终回答输出和错误回滚。
- `_record_tool_results(conversation, tool_calls, tool_results, trace_writer=None)` 负责把 `ToolGateway.handle_many` 返回的工具结果写回 conversation。它同时记录 tool result trace，避免 `run_agent_loop` 堆积 JSON 拼装细节。
- `_trace_assistant_message(trace_writer, route)` 负责记录 assistant 消息级 trace。它保留模型原始 `content` 的记录方式，同时使用 route 判断是否包含工具调用。
- `_trace_tool_call(trace_writer, tool_call)` 负责记录单个工具调用的 trace，包括调用 id、工具名和解析后的参数。
- `_write_trace(trace_writer, event_type, payload)` 是 trace 写入的小封装；没有 trace writer 时不做任何事。
- `_write_error(message)` 是默认错误输出函数，把错误消息写到 `stderr`。测试可以注入 `error_fn`，默认 CLI 行为不变。
- `_trace_tool_arguments(tool_call)` 负责把工具调用中的 JSON 参数解析成对象，解析失败时保留原始字符串，方便 trace 仍能记录异常输入。
- `_tool_name(tool_call)` 负责从模型 tool call 结构中取出函数名，避免主流程重复写嵌套字段访问。

`src/wdcode/core/tool_loop.py`

- `run_tool_loop(*args, **kwargs)` 现在只保留 deprecated 提示，不再导入或转发旧的 `run_agent_turn`。项目不再维护第二套 tool loop。

`src/wdcode/context/provider.py`

- `ContextBundle` 是上下文结果的数据结构，目前只有 `text` 字段，默认是空字符串。
- `ContextProvider.build(user_input, conversation)` 是上下文构建接口。目前返回空 `ContextBundle`，只为后续上下文能力预留稳定入口。

`src/wdcode/core/message_builder.py`

- `build_model_messages(conversation, context=None)` 负责把 conversation 转成模型输入消息。当前在空上下文下保持旧行为，直接返回 `conversation.as_messages()`。

`src/wdcode/core/model_runner.py`

- `ModelRunner.__init__(client)` 保存模型客户端实例。
- `ModelRunner.call(messages, tools=None)` 负责调用 `client.chat(messages, tools=tools)`，让 `run_agent_loop` 不直接依赖客户端调用细节。

`src/wdcode/core/response_router.py`

- `AssistantRoute` 是模型回复路由结果。它记录是否是最终回答、归一化后的内容、稳定 tuple 形式的工具调用，以及原始 assistant 消息。
- `route_assistant_message(assistant_message)` 负责判断模型回复是最终回答还是工具调用。没有 `tool_calls` 时视为最终回答，有 `tool_calls` 时进入工具路径；`content` 会归一化为字符串。

`src/wdcode/tools/gateway.py`

- `ToolGateway.__init__(registry, project_root=None, approval_mode="auto")` 保存工具注册表、项目根目录和 approval 模式。
- `ToolGateway.schemas()` 返回工具 schema，供模型调用前传入。
- `ToolGateway.handle(tool_call)` 处理单个工具调用。它仍然通过 `tool_guard.prepare_tool_request` 做校验和准备，再执行具体工具，并把结果统一封装成 `ToolResult`。
- `ToolGateway._failure(error, tool_name="", stage="execution", dry_run=False)` 负责生成统一失败结果。
- `ToolGateway.handle_many(tool_calls)` 是批量工具入口。它按顺序逐个调用 `handle`，让 `run_agent_loop` 只面对工具层入口，而不关心工具层内部细节。

`tests/fakes.py`

- `FakeModelClient` 是无 API key 的模型客户端假对象，用于按顺序返回预置 assistant 消息并记录模型调用参数。
- `InputSequence` 是测试用输入函数，按顺序返回预置用户输入，输入耗尽时触发 EOF 退出主循环。
- `run_agent_loop_with_inputs(client, inputs, **kwargs)` 是测试辅助函数，用注入输入和输出的方式运行 `run_agent_loop`，并返回输出消息和错误消息。

## 当前测试说明

- `tests/test_agent_loop_fake_model.py` 覆盖无工具调用最终回答、工具调用执行和坏参数工具结果写回。
- `tests/test_agent_loop_trace.py` 覆盖主循环 trace 事件顺序和敏感字段脱敏。
- `tests/test_agent_loop_approval.py` 覆盖 dry-run approval 行为。
- `tests/test_agent_loop_orchestration.py` 覆盖上下文接口调用、max tool rounds 停止和单轮工具数量限制。
- `tests/test_response_router.py` 覆盖 final answer、空内容归一化和 tool calls tuple 化。
- `tests/test_message_builder.py` 覆盖空上下文下模型消息保持旧行为，并确认不会改写 conversation。
- `tests/test_model_runner.py` 覆盖 `ModelRunner` 对 `client.chat` 的委托调用。
- `tests/test_tool_gateway.py` 覆盖 `handle_many` 顺序返回行为。

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
