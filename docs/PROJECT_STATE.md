# PROJECT_STATE

## 当前状态

当前进入 Phase 3.4：Context Budget 最小版。

本轮已经新增字符级上下文预算控制。`ContextProvider` 在提供 `project_root` 时，可以按预算输出 AGENTS.md、Repo Map 和 Relevant Files 上下文；默认没有 `project_root` 时仍返回空上下文，避免破坏现有测试和调用方式。

当前只做字符数预算，不做 token 预算，不引入 tokenizer。当前检索仍只读取 repo map 元数据，不读取候选文件正文。当前没有实现 recent files、symbol index、embedding、向量数据库或 Phase 3.5 / Phase 3.6 能力。

当前正式工具调用链保持不变：

```text
main -> run_agent_loop -> ToolGateway.handle_many -> ToolGateway.handle -> tool_guard.prepare_tool_request -> tool.execute
```

## 当前主流程

一次用户输入进入 `run_agent_loop` 后，会先写入 `Conversation`。随后同一个主循环在每一轮中依次调用 `ContextProvider.build`、`build_model_messages`、`ModelRunner.call`、`route_assistant_message`。如果模型返回最终回答，就写回 assistant 消息并输出；如果模型返回工具调用，就交给 `ToolGateway.handle_many` 执行，再把工具结果写回 conversation，进入下一轮模型调用。

Phase 3.4 后，`ContextProvider.build` 在有项目根目录时会执行：

```text
build_repo_map -> load_agents_context -> retrieve_relevant_files -> apply_context_budget -> ContextBundle
```

`build_model_messages` 会把非空上下文作为额外 system message 插入到原系统提示词之后。

## 当前代码文件和函数说明

`src/wdcode/context/budget.py`

- `ContextBudget` 是字符级上下文预算配置，包含 `max_total_chars`、`max_agents_chars`、`max_repo_map_chars`、`max_relevant_files_chars`。所有预算值都必须大于 0，否则抛出 `ValueError`。
- `apply_char_budget(text, max_chars, label=...)` 对单段文本应用字符预算。未超长时原样返回；超长时截断并追加 `[TRUNCATED: label]` 标记。
- `apply_context_budget(agents_text, repo_map_text, relevant_files_text, budget)` 先分别按 section 预算截断 AGENTS.md、Repo Map、Relevant Files，再按总预算截断合并后的 Project Context，并返回截断 metadata。

`src/wdcode/context/retrieval.py`

- `RetrievalCandidate` 是候选相关文件的数据结构，记录文件路径、分数和简短原因。
- `retrieve_relevant_files(user_input, repo_map, max_results=8)` 根据用户输入和 repo map entries 选出候选文件。它只使用 path、kind、summary、is_source、is_test、is_doc 等元数据，不读取文件正文；结果按 score 降序、path 升序稳定排序。
- `format_retrieval_candidates(candidates)` 把候选文件格式化为可注入模型的文本块。没有候选时输出 `No relevant files selected.`。
- `_score_entry(entry, query_terms)` 负责给单个 repo map entry 打分，包括路径、文件名、summary、测试意图、文档意图、工具相关路径、agent 相关路径和 context 目录加分。
- `_score_path_terms(path, terms, reason_prefix, reasons)` 是路径类规则的共享打分函数。
- `_query_terms(user_input)` 负责把用户输入归一化为关键词，并识别测试、文档、工具、agent、context 等特殊查询意图。

`src/wdcode/context/provider.py`

- `ContextBundle` 是上下文结果的数据结构，包含 `text` 和可选 `metadata`。`metadata["budget"]` 记录 AGENTS.md、Repo Map、Relevant Files 和总上下文是否被截断。
- `ContextProvider.__init__(project_root=None, max_retrieval_results=8, budget=None)` 保存项目根目录、retrieval 结果数量上限和 `ContextBudget`。`project_root=None` 时保持空上下文行为。
- `ContextProvider.build(user_input, conversation)` 是上下文构建入口。有项目根目录时，它会构建 repo map、读取根目录 AGENTS.md、检索候选相关文件，并通过 `apply_context_budget` 组合成受控的 `ContextBundle.text`。

`src/wdcode/core/message_builder.py`

- `build_model_messages(conversation, context=None)` 负责把 conversation 转成模型输入消息。空 context 下保持旧行为；非空 context 下，会把上下文作为 system message 插入到原系统提示词之后，并且不修改 conversation 本体。

`src/wdcode/core/agent_loop.py`

- `run_agent_loop(client, tool_registry=None, ...)` 是唯一 agent 主编排函数。它读取用户输入，处理退出命令，把用户消息写入 conversation，并直接组织上下文构建、模型消息构建、模型调用、回复路由、工具执行、工具结果写回、最终回答输出和错误回滚。
- `_record_tool_results(conversation, tool_calls, tool_results, trace_writer=None)` 负责把 `ToolGateway.handle_many` 返回的工具结果写回 conversation。它同时记录 tool result trace，避免 `run_agent_loop` 堆积 JSON 拼装细节。
- `_trace_assistant_message(trace_writer, route)` 负责记录 assistant 消息级 trace。它保留模型原始 `content` 的记录方式，同时使用 route 判断是否包含工具调用。
- `_trace_tool_call(trace_writer, tool_call)` 负责记录单个工具调用的 trace，包括调用 id、工具名和解析后的参数。
- `_write_trace(trace_writer, event_type, payload)` 是 trace 写入的小封装；没有 trace writer 时不做任何事。
- `_write_error(message)` 是默认错误输出函数，把错误消息写到 `stderr`。测试可以注入 `error_fn`，默认 CLI 行为不变。
- `_trace_tool_arguments(tool_call)` 负责把工具调用中的 JSON 参数解析成对象，解析失败时保留原始字符串，方便 trace 仍能记录异常输入。
- `_tool_name(tool_call)` 负责从模型 tool call 结构中取出函数名，避免主流程重复写嵌套字段访问。

`src/wdcode/context/__init__.py`

- 当前导出 AGENTS、Repo Map、Retrieval、ContextProvider 和 Context Budget 相关入口，方便后续模块统一从 `wdcode.context` 引用上下文能力。

`src/wdcode/core/tool_loop.py`

- `run_tool_loop(*args, **kwargs)` 只保留 deprecated 提示，不再导入或转发旧的 `run_agent_turn`。项目不再维护第二套 tool loop。

`src/wdcode/tools/gateway.py`

- `ToolGateway.__init__(registry, project_root=None, approval_mode="auto")` 保存工具注册表、项目根目录和 approval 模式。
- `ToolGateway.schemas()` 返回工具 schema，供模型调用前传入。
- `ToolGateway.handle(tool_call)` 处理单个工具调用。它仍然通过 `tool_guard.prepare_tool_request` 做校验和准备，再执行具体工具，并把结果统一封装成 `ToolResult`。
- `ToolGateway._failure(error, tool_name="", stage="execution", dry_run=False)` 负责生成统一失败结果。
- `ToolGateway.handle_many(tool_calls)` 是批量工具入口。它按顺序逐个调用 `handle`，让 `run_agent_loop` 只面对工具层入口，而不关心工具层内部细节。

## 当前测试说明

- `tests/test_context_budget.py` 覆盖字符预算未截断、字符预算截断、非法预算值、section 截断、总截断和 metadata。
- `tests/test_context_provider.py` 覆盖 `project_root=None` 空上下文、有项目根目录时组合 AGENTS / Repo Map / Relevant Files、预算截断 metadata，以及不读取候选文件正文。
- `tests/test_retrieval.py` 覆盖路径匹配、文件名匹配、测试意图、context 意图、空输入、max_results、非法 max_results、稳定排序和格式化输出。
- `tests/test_message_builder.py` 覆盖空 context 旧行为、非空 context system message 注入，以及不修改 conversation 本体。
- `tests/test_agent_loop_fake_model.py` 覆盖无工具调用最终回答、工具调用执行和坏参数工具结果写回。
- `tests/test_agent_loop_trace.py` 覆盖主循环 trace 事件顺序和敏感字段脱敏。
- `tests/test_agent_loop_approval.py` 覆盖 dry-run approval 行为。
- `tests/test_agent_loop_orchestration.py` 覆盖上下文接口调用、max tool rounds 停止和单轮工具数量限制。
- `tests/test_response_router.py` 覆盖 final answer、空内容归一化和 tool calls tuple 化。
- `tests/test_model_runner.py` 覆盖 `ModelRunner` 对 `client.chat` 的委托调用。
- `tests/test_tool_gateway.py` 覆盖 `handle_many` 顺序返回行为。

## 尚未开始

- recent files
- symbol index
- embedding
- vector database
- Phase 3.5
- Phase 3.6
- Phase 4

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
