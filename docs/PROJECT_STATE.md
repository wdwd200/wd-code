# PROJECT_STATE

## 当前状态

当前进入 Phase 4.3：状态快照机制最小版。

本阶段已经新增 `TurnCheckpoint`、`CheckpointStore` 和 `src/wdcode/session/checkpoint.py`。系统现在可以在每个非空用户请求开始处理前，持久化一个 pre-turn checkpoint。这个 checkpoint 保存本轮 user input 加入前的 conversation messages，并附带 recovery summary、context snapshot、tool call snapshot、file change snapshot 和 metadata。

当前 RuntimeError 仍使用已有的 `conversation.rollback(checkpoint)` 做内存回滚；回滚后保存 session 时，会在 session metadata 中记录 `rollback_checkpoint_id`。成功完成回合时，session metadata 会记录 `latest_checkpoint_id`。

当前不实现失败重试，不实现自动 retry loop，不实现 CLI checkpoint restore 命令，不裁剪旧 messages，也不实现真正上下文压缩。Phase 4.4 / 4.5 / 4.6 尚未开始。

## 当前主流程

一次用户输入进入 `run_agent_loop` 后，如果启用了 session，会先创建或加载 session。每个非空用户输入开始处理前，系统会在添加本轮 user input 之前保存一个 `TurnCheckpoint`。

checkpoint 初始保存 pre-turn messages、recovery summary、file change snapshot 和 user input preview。随后 `ContextProvider.build` 完成后会更新同一个 checkpoint 的 `context_snapshot`。如果模型返回 tool calls，会在工具执行之前更新同一个 checkpoint 的 `tool_call_snapshot`。如果本轮 RuntimeError，主循环回滚到内存 checkpoint，并在 session metadata 中记录 rollback checkpoint id。

当前主流程为：

```text
可选加载 session 与 recovery_summary
-> 读取用户输入
-> 保存 pre-turn TurnCheckpoint
-> conversation 写入用户消息
-> ContextProvider.build
-> 更新 checkpoint.context_snapshot
-> build_model_messages 注入 recovery summary 与项目上下文
-> ModelRunner.call
-> route_assistant_message
-> 可选更新 checkpoint.tool_call_snapshot
-> final answer 或 ToolGateway.handle_many
-> RuntimeError 时 conversation.rollback
-> 可选生成 recovery summary
-> 保存 session metadata checkpoint id
```

## 当前代码文件和函数说明

`src/wdcode/session/checkpoint.py`

- `TurnCheckpoint` 是单个用户回合安全点的数据结构，记录 `checkpoint_id`、`session_id`、`turn_index`、`created_at`、messages、recovery summary、context snapshot、tool call snapshot、file change snapshot 和 metadata。
- `CheckpointStore.__init__(root)` 保存 checkpoint 根目录。agent loop 默认使用 `session_store.root / "checkpoints"`。
- `CheckpointStore.save(checkpoint)` 把 checkpoint 写为 UTF-8 JSON。实际保存路径是 `<checkpoint_root>/<session_id>/<checkpoint_id>.json`，并用 `validate_session_id` 校验 session id 和 checkpoint id。
- `CheckpointStore.load(session_id, checkpoint_id)` 按 session id 和 checkpoint id 读取 checkpoint。文件不存在时返回 `None`；JSON 损坏或版本不支持时抛出 `ValueError`。
- `CheckpointStore.list_for_session(session_id)` 读取某个 session 的所有 checkpoint，并按 `created_at` 和 `checkpoint_id` 稳定排序。
- `CheckpointStore.latest_for_session(session_id)` 返回某个 session 最新的 checkpoint，没有记录时返回 `None`。
- `build_turn_checkpoint(...)` 构建一个新的 checkpoint。它会校验 session id 和 `turn_index`，自动生成 checkpoint id，并对 messages、recovery summary、snapshots 和 metadata 做深拷贝。
- `create_checkpoint_id()` 生成可作为文件名使用的 checkpoint id。当前格式是 UTC 时间戳加 8 位 uuid 后缀。
- `build_context_snapshot(context)` 生成轻量上下文快照。它只保存 `has_text`、`char_count`、最多 500 字符的 `text_preview`、`text_truncated` 和 context metadata，不保存完整超长上下文正文。
- `build_tool_call_snapshot(tool_calls)` 生成轻量工具调用快照。它只保存 tool call id、工具名、最多 500 字符的 arguments preview 和是否截断；会对常见敏感参数名做 `[REDACTED]` 处理，不执行工具。
- `build_file_change_snapshot(project_root)` 生成轻量文件变更快照。它只运行 `git status --short`、`git diff --name-only` 和 `git diff --cached --name-only`，不读取文件正文，不保存 diff 内容；非 git 仓库或命令失败时返回 unavailable 或 error 信息，不让主流程崩溃。
- `restore_conversation_from_checkpoint(checkpoint)` 从 checkpoint messages 和 recovery summary 恢复一个 `Conversation`，不写 session、不执行工具。
- `_checkpoint_from_payload(payload)` 把 checkpoint JSON payload 转回 `TurnCheckpoint`。
- `_arguments_preview(arguments)` 尝试解析 tool call arguments，解析成功时输出排序后的 JSON preview，解析失败时保存 raw preview。
- `_redact_sensitive_values(value)` 递归脱敏参数中的 `api_key`、`token`、`password`、`secret` 等敏感字段。
- `_preview(text, max_chars=500)` 把文本压成单行并限制预览长度。
- `_run_git(project_root, args)` 用非 shell subprocess 执行短超时 git 命令。
- `_unavailable_file_snapshot(reason, error="")` 生成不可用的 file change snapshot。
- `_utc_now()` 返回 UTC ISO 时间字符串。

`src/wdcode/session/recovery.py`

- `RecoverySummary` 是恢复摘要的数据结构，记录 `summary`、`source_message_count`、`recent_message_count` 和 `metadata`。
- `split_messages_for_recovery(messages, keep_recent_messages=12)` 把 messages 拆成旧消息和最近消息，返回深拷贝，不修改原 messages。
- `build_recovery_summary(messages, max_summary_chars=4000, keep_recent_messages=12)` 基于 messages 生成规则化 recovery summary；不调用 LLM，不读取文件正文。超出预算时追加 `[TRUNCATED: recovery_summary]`。
- `_summary_lines(old_messages, recent_message_count)` 生成 recovery summary 的主要文本行。
- `_non_empty_lines(lines)` 保证空分类仍输出 `- none`。
- `_message_preview(message)` 根据消息 role 生成单行摘要。
- `_compact_text(text, max_chars=240)` 把消息预览压成短文本。
- `_apply_summary_budget(text, max_summary_chars)` 应用 summary 字符预算。

`src/wdcode/session/store.py`

- `SessionRecord` 是 session 持久化数据结构，记录 `session_id`、conversation messages、创建时间、更新时间、metadata，以及可选 `recovery_summary`。
- `create_session_id()` 生成可作为文件名使用的 session id。
- `validate_session_id(session_id)` 校验 session id，只允许字母、数字、短横线和下划线，并拒绝空字符串、`..`、`/` 和 `\`。
- `SessionStore.__init__(root)` 保存 session 文件目录。CLI 默认目录是项目根目录下的 `.wdcode/sessions`。
- `SessionStore.save(record)` 把 `SessionRecord` 写成 UTF-8 JSON，格式包含 `version: 1`。
- `SessionStore.load(session_id)` 从 `{session_id}.json` 读回 `SessionRecord`。旧格式 session 没有 `recovery_summary` 时仍能加载。
- `SessionStore.exists(session_id)` 判断指定 session 文件是否存在。
- `SessionStore._path_for(session_id)` 生成 session JSON 路径。

`src/wdcode/session/__init__.py`

- 当前导出 `SessionRecord`、`SessionStore`、`RecoverySummary`、`TurnCheckpoint`、`CheckpointStore`、session id helper、recovery helper、checkpoint snapshot helper 和 checkpoint restore helper。

`src/wdcode/core/agent_loop.py`

- `run_agent_loop(client, tool_registry=None, ...)` 是唯一 agent 主编排函数。Phase 4.3 后新增可选 `checkpoint_store` 参数。未传 session store 和 checkpoint store 时旧行为不变；启用 session store 且未传 checkpoint store 时，默认使用 `CheckpointStore(session_store.root / "checkpoints")`。
- `_record_tool_results(conversation, tool_calls, tool_results, trace_writer=None)` 把工具结果写回 conversation，并记录 tool result trace。
- `_trace_assistant_message(trace_writer, route)` 记录 assistant 消息级 trace。
- `_trace_tool_call(trace_writer, tool_call)` 记录单个工具调用的 trace。
- `_write_trace(trace_writer, event_type, payload)` 是 trace 写入的小封装。
- `_write_error(message)` 是默认错误输出函数。
- `_trace_tool_arguments(tool_call)` 解析工具调用 JSON 参数，解析失败时保留原始字符串。
- `_tool_name(tool_call)` 从模型 tool call 结构中取出函数名。
- `_load_session_conversation(conversation, session_store, session_id)` 加载或创建 session，并恢复 messages 和 recovery summary。
- `_save_session(session_store, session_record, conversation, checkpoint, rolled_back, ...)` 保存完整 conversation messages、recovery summary 和 session metadata。成功时记录 `latest_checkpoint_id`；rollback 时额外记录 `rollback_checkpoint_id`。
- `_build_recovery_summary_dict(conversation, summary_trigger_messages, keep_recent_messages, max_recovery_summary_chars)` 判断是否需要生成 recovery summary，并转成 JSON dict。
- `_resolve_checkpoint_store(session_store, checkpoint_store)` 决定本轮是否启用 checkpoint store。
- `_create_turn_checkpoint(checkpoint_store, session_record, conversation, user_input, project_root)` 在本轮 user input 加入 conversation 之前创建 pre-turn checkpoint。
- `_save_checkpoint_update(checkpoint_store, checkpoint, context_snapshot, tool_call_snapshot, metadata_updates)` 用 dataclass `replace` 更新同一个 checkpoint 文件。
- `_next_turn_index(conversation)` 根据当前 conversation 中 user 消息数量推导下一回合编号。
- `_preview_text(text, max_chars=500)` 生成 user input preview，不影响 conversation messages。
- `_utc_now()` 返回 UTC ISO 时间字符串。

`src/wdcode/core/conversation.py`

- `Conversation.__init__(system_prompt=SYSTEM_PROMPT, recovery_summary=None)` 创建内存对话，放入默认 system prompt，并保存可选 recovery summary。
- `Conversation.add_user_message(content)` 追加用户消息。
- `Conversation.add_assistant_message(content)` 追加 assistant 最终文本消息。
- `Conversation.add_assistant_tool_call_message(message)` 追加包含 tool calls 的 assistant 消息。
- `Conversation.add_tool_result(tool_call_id, name, content)` 追加工具结果消息。
- `Conversation.remove_last_message()` 删除最后一条非 system 消息。
- `Conversation.checkpoint()` 返回当前消息数量，用作内存回滚点。
- `Conversation.rollback(checkpoint)` 把消息列表回滚到 checkpoint，最低保留 system prompt。
- `Conversation.as_messages()` 返回当前 messages 的浅拷贝。
- `Conversation.to_messages()` 返回当前 messages 的深拷贝。
- `Conversation.from_messages(messages, recovery_summary=None)` 从保存的 messages 和 recovery summary 恢复 `Conversation`。

`src/wdcode/core/message_builder.py`

- `build_model_messages(conversation, context=None)` 把 conversation 转为模型输入消息。它会按顺序插入原 system prompt、session recovery summary、项目上下文和其余 conversation messages。
- `_recovery_summary_text(recovery_summary)` 从 dict、`RecoverySummary` 对象或普通字符串中取出 summary 文本。

`src/wdcode/cli/main.py`

- `parse_args(argv)` 解析 CLI 参数。当前支持 `--session-id` 和 `--session-dir`，本轮没有新增 CLI checkpoint restore 命令。
- `create_llm_client(config)` 根据运行时配置创建 OpenAI-compatible client。
- `main(argv=None)` 组装 config、client、默认工具注册表和可选 session store；默认 CLI 交互行为不变。

`src/cli_assistant.py`

- 兼容入口文件，直接调用 `wdcode.cli.main.main()`。

`src/wdcode/context/provider.py`

- `ContextBundle` 是上下文构建结果的数据结构，包含 `text` 和可选 `metadata`。
- `ContextProvider.__init__(project_root=None, max_retrieval_results=8, budget=None)` 保存项目根目录、relevant files 数量上限和上下文预算。
- `ContextProvider.build(user_input, conversation)` 构建 AGENTS.md、Repo Map、Recent Files、Symbol Index 和 Relevant Files。Phase 4.3 没有修改这段上下文工程逻辑。

`src/wdcode/tools/gateway.py`

- `ToolGateway.__init__(registry, project_root=None, approval_mode="auto")` 保存工具注册表、项目根目录和 approval 模式。
- `ToolGateway.schemas()` 返回工具 schema。
- `ToolGateway.handle(tool_call)` 处理单个工具调用，仍通过 tool guard 做校验并返回统一 `ToolResult`。
- `ToolGateway._failure(error, tool_name="", stage="execution", dry_run=False)` 生成统一失败结果。
- `ToolGateway.handle_many(tool_calls)` 按顺序批量处理工具调用。

## 当前测试说明

- `tests/test_session_checkpoint.py` 覆盖 checkpoint 深拷贝、非法 session id、非法 turn index、CheckpointStore save/load、missing load、稳定排序、latest 查询、context snapshot 预览、tool call snapshot 不修改原输入、file change snapshot unavailable，以及 checkpoint 恢复 conversation。
- `tests/test_agent_loop_orchestration.py` 覆盖默认主循环、session 保存、recovery summary、pre-turn checkpoint、context snapshot、tool call snapshot、rollback checkpoint metadata，以及无 session store 时不创建默认 checkpoint store。
- `tests/test_session_store.py` 覆盖 session JSON 保存读取、旧格式兼容和 recovery summary 字段。
- `tests/test_imports.py` 覆盖 `CheckpointStore` 和 `TurnCheckpoint` 可以从 `wdcode.session` 导入。
- `tests/test_session_recovery.py` 覆盖 recovery summary 生成、拆分和截断。
- `tests/test_message_builder.py` 覆盖 recovery summary 注入顺序和不修改 conversation。
- `tests/test_cli_help.py` 覆盖 CLI help 不需要 API key，并保留 session 参数。
- `tests/test_symbol_index.py` 覆盖最小 Symbol Index 行为。
- `tests/test_context_budget.py` 覆盖上下文预算。
- `tests/test_context_provider.py` 覆盖上下文组合。
- `tests/test_recent_files.py` 覆盖 git recent files 收集。
- `tests/test_retrieval.py` 覆盖 Smart Retrieval 元数据检索。
- `tests/test_agent_loop_fake_model.py` 覆盖 fake model 下的最终回答和工具调用。
- `tests/test_agent_loop_trace.py` 覆盖 trace 事件和敏感字段脱敏。
- `tests/test_agent_loop_approval.py` 覆盖 dry-run approval 行为。

## 尚未开始

- automatic failure retry
- automatic retry loop
- CLI checkpoint restore command
- true context compression
- message pruning
- validation repair loop
- embedding
- vector database
- Phase 4.4
- Phase 4.5
- Phase 4.6

## 明确推迟

- TUI
- MCP
- 多 agent
- 长期 memory
- VS Code 插件
- 大规模重构

## API Key Policy

默认测试不需要真实 API key。本项目不读取、不打印、不提交 `.env` 或真实密钥。Checkpoint 只保存 conversation messages 和轻量 snapshot；file change snapshot 不保存文件正文或 diff 内容。

## 当前验证命令

当前主要验证命令仍然是：

```bash
python -m pytest
```

本阶段建议额外验证：

```bash
python src/cli_assistant.py --help
python src/wdcode/cli/main.py --help
```
