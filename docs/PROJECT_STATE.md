# PROJECT_STATE

## 当前状态

当前进入 Phase 4.5：上下文压缩机制最小版。

本阶段已经新增 `src/wdcode/session/compression.py`。它用确定性的规则生成 `ConversationCompression`，在 conversation 历史超过阈值时，把旧消息压缩成 `# Compressed Conversation History` 摘要，并保留最近 N 条完整消息给模型。压缩只影响模型调用时的 messages，不删除 session JSON 中保存的完整 conversation messages。

模型调用现在可以收到：system prompt、可选 recovery summary、可选 compression summary、可选项目 context，以及最近 N 条 conversation messages。压缩摘要会记录来源消息范围、被压缩消息数量、保留的最近消息数量、关键文件路径和关键工具结果短预览。

当前不调用真实 LLM 做摘要，不做 embedding，不引入 tokenizer 依赖，不做数据库，不实现 Eval 任务系统，不改变 CLI 默认交互行为。

## 当前主流程

一次非空用户输入进入 `run_agent_loop` 后，系统先加载或创建 session，并恢复 conversation 的完整 messages、recovery summary 和 compression summary。启用 session store 时，本轮 user input 写入 conversation 前仍保存 pre-turn checkpoint。

user input 写入 conversation 后，主循环构建项目 context，并在构建模型 messages 前调用规则化压缩逻辑。如果 messages 数量超过 `CompressionPolicy.trigger_message_count`，系统会生成 compression summary；随后 `build_model_messages` 只把 compression summary 和最近 `CompressionPolicy.keep_recent_messages` 条 conversation messages 传给模型。

成功完成一轮后，session 仍保存完整 messages，同时保存最新 recovery summary 和 compression summary。失败 rollback 后，conversation 回滚到本轮开始前的内存 checkpoint，再根据 rollback 后的完整 messages 重新生成 compression summary 并保存 session。checkpoint metadata 会记录本轮是否存在 compression summary，以及对应的 source range 和 summary 字符数。

Phase 4.4 的 failure retry 仍然有效：模型调用保持默认最多 2 次重试，工具调用默认不重复执行；最终失败仍生成 failure report 并沿用 checkpoint / rollback。

## 代码文件和函数说明

`src/wdcode/session/compression.py`

- `CompressionPolicy` 描述压缩策略。它包含 `trigger_message_count`、`keep_recent_messages`、`max_summary_chars`、`max_tool_result_chars` 和 `max_key_files`；任一字段小于等于 0 时抛出 `ValueError`。
- `ConversationCompression` 描述一次压缩结果。它保存摘要正文、原始消息总数、保留的最近消息数、被压缩的旧消息数、关键文件列表、关键工具结果短预览、来源消息范围和 metadata。
- `build_conversation_compression(messages, recovery_summary, policy)` 是压缩入口。消息数未超过阈值时返回 `None`；超过阈值时复制 messages，拆分旧消息和最近消息，提取关键文件和工具结果，生成确定性摘要，不调用 LLM、不读文件、不修改原 messages。
- `split_messages_for_compression(messages, keep_recent_messages)` 把 messages 拆成旧消息和最近消息。最近消息是最后 N 条，旧消息是其余部分；函数返回深拷贝，避免调用方原始 messages 被改动。
- `extract_key_files_from_messages(messages, max_files)` 从 message content、tool calls、function arguments 和 tool result 内容中提取看起来像源码或文档路径的字符串。它只做字符串扫描，不检查文件是否存在，也不读取文件正文。
- `extract_key_tool_results(messages, max_results, max_result_chars)` 从 role 为 tool 或带 tool result 语义的消息中提取工具结果短预览。每条结果只保留 `tool_call_id`、`name`、`content_preview` 和 `truncated`，不保存完整工具输出。
- `conversation_compression_to_dict(compression)` 把 `ConversationCompression` 转成 JSON 可序列化 dict，并清洗 metadata 中的敏感字段。
- `conversation_compression_from_dict(data)` 从 session JSON 中恢复 `ConversationCompression`；传入 `None` 时返回 `None`，用于兼容旧 session。
- `_build_summary_text(...)` 按固定结构生成压缩摘要，包含 Source、Earlier user requests、Assistant progress、Key tool results、Key files 和 Source markers。
- `_message_preview_lines(messages, role)` 从旧消息中提取 user 请求或 assistant 进展短句，最多保留 12 条。
- `_tool_result_lines(key_tool_results)` 把关键工具结果短预览转成摘要中的列表行。
- `_key_file_lines(key_files)` 把关键文件路径转成摘要中的列表行。
- `_iter_message_text_fragments(messages)` 遍历消息中可用于路径提取的文本片段。
- `_iter_value_text(value)` 递归遍历字符串、dict 和 list，跳过敏感 key 下的内容。
- `_looks_like_tool_result(message)` 判断一条消息是否应该按工具结果处理。
- `_tool_content_preview(content, max_chars)` 生成工具结果预览。JSON 工具结果会只保留 ok、error、metadata 和 data_preview。
- `_apply_summary_budget(text, max_summary_chars)` 对摘要应用字符预算，超出时追加 `[TRUNCATED: conversation_compression]`。
- `_preview_with_truncation(text, max_chars)` 把文本压成单行并返回是否截断。
- `_preview_text(text, max_chars)` 返回单行短预览。
- `_json_preview(value)` 尝试把对象转成稳定 JSON 字符串，失败时退回 `str(value)`。
- `_try_parse_json(value)` 尝试解析 JSON 字符串，失败时返回 `None`。
- `_safe_metadata(value)` 清洗 metadata，递归截断长字符串并脱敏 key、token、secret、password、credential、authorization、api_key 等字段。
- `_is_sensitive_key(key)` 判断字段名是否有敏感含义。

`src/wdcode/core/message_builder.py`

- `build_model_messages(conversation, context, compression_summary, keep_recent_messages)` 构建模型输入 messages。没有 compression summary 时保持旧行为；有 compression summary 时，会在 recovery summary 之后、项目 context 之前插入 system message，并只保留最近 N 条 conversation messages。
- `_recovery_summary_text(recovery_summary)` 从 dict、对象或字符串中取出 recovery summary 文本。
- `_compression_summary_text(compression_summary)` 从 dict、对象或字符串中取出 compression summary 文本。
- `_compression_keep_recent(compression_summary, keep_recent_messages)` 决定模型输入要保留的最近消息数。显式参数优先，其次使用 compression summary 中的 `kept_recent_message_count`。
- `_format_compression_summary(summary_text)` 确保压缩摘要 system message 以 `# Compressed Conversation History` 开头，避免重复标题。

`src/wdcode/core/conversation.py`

- `Conversation.__init__(system_prompt, recovery_summary, compression_summary)` 创建内存 conversation。新增 `compression_summary` 字段，但不会把它写入 `messages` 本体。
- `Conversation.add_user_message(content)` 追加用户消息。
- `Conversation.add_assistant_message(content)` 追加 assistant 最终文本消息。
- `Conversation.add_assistant_tool_call_message(message)` 追加包含 tool calls 的 assistant 消息。
- `Conversation.add_tool_result(tool_call_id, name, content)` 追加工具结果消息。
- `Conversation.remove_last_message()` 删除最后一条非 system 消息。
- `Conversation.checkpoint()` 返回当前 messages 长度，用作内存 rollback 点。
- `Conversation.rollback(checkpoint)` 把 messages 回滚到指定长度，至少保留 system prompt；compression summary 字段不写入 messages。
- `Conversation.as_messages()` 返回 messages 的浅拷贝。
- `Conversation.to_messages()` 返回 messages 的深拷贝。
- `Conversation.from_messages(messages, recovery_summary, compression_summary)` 从保存的完整 messages 恢复 conversation，同时恢复 recovery summary 和 compression summary。

`src/wdcode/session/store.py`

- `SessionRecord` 是 session 持久化数据结构。Phase 4.5 新增 `compression_summary` 可选字段；session 仍保存完整 messages，不因压缩删除历史。
- `create_session_id()` 生成可作为文件名使用的 session id。
- `validate_session_id(session_id)` 校验 session id，只允许字母、数字、短横线和下划线，并拒绝空字符串、`..`、`/` 和 `\`。
- `SessionStore.__init__(root)` 保存 session 文件根目录。
- `SessionStore.save(record)` 把 `SessionRecord` 写成 UTF-8 JSON，继续使用 version 1，并包含 metadata、recovery summary 和 compression summary。
- `SessionStore.load(session_id)` 从 JSON 文件恢复 `SessionRecord`。旧 session 文件没有 metadata、recovery summary 或 compression summary 时仍可正常加载。
- `SessionStore.exists(session_id)` 判断指定 session 文件是否存在。
- `SessionStore._path_for(session_id)` 根据 session id 生成 JSON 文件路径。

`src/wdcode/core/agent_loop.py`

- `run_agent_loop(client, tool_registry, ...)` 是主编排函数。Phase 4.5 新增 `compression_policy` 可选参数；默认使用 `CompressionPolicy()`。每次模型调用前会刷新 compression summary，并把压缩摘要和最近 N 条 messages 交给 `build_model_messages`。
- `_ToolExecutionFailure` 是工具重试内部异常类型，只在显式启用工具错误重试时使用。
- `_record_tool_results(conversation, tool_calls, tool_results, trace_writer)` 把工具结果写回完整 conversation，并保持 `ToolResult.to_dict()` 格式不变。
- `_handle_many_tools(tool_gateway, tool_calls, retry_policy)` 调用工具网关，必要时把执行阶段工具失败升级为可重试内部异常。
- `_should_raise_tool_result_failure(tool_results, retry_policy)` 判断工具失败是否应该触发重试。
- `_tool_failure_message(tool_results)` 从失败工具结果中生成短错误消息。
- `_trace_assistant_message(trace_writer, route)` 记录 assistant 消息 trace。
- `_trace_tool_call(trace_writer, tool_call)` 记录工具调用 trace，并继续使用已有参数脱敏逻辑。
- `_write_trace(trace_writer, event_type, payload)` 是 trace 写入封装。
- `_write_error(message)` 是默认错误输出函数。
- `_trace_tool_arguments(tool_call)` 解析工具参数 JSON；解析失败时保留原始短文本。
- `_tool_name(tool_call)` 从 tool call 中取函数名。
- `_load_session_conversation(conversation, session_store, session_id)` 创建或加载 session，并恢复 messages、recovery summary 和 compression summary。
- `_save_session(session_store, session_record, conversation, checkpoint, rolled_back, failure_report, ..., compression_policy)` 保存完整 session。保存前会根据当前 conversation 状态刷新 compression summary，并把它写入 `SessionRecord.compression_summary`。
- `_latest_report_with_events(current, candidate)` 更新本轮 latest failure report。
- `_failure_report_from_exception(exc, current_report)` 从异常中提取或构造失败报告。
- `_record_failure_metadata(metadata, failure_report, checkpoint)` 把失败报告摘要写入 session metadata。
- `_build_recovery_summary_dict(conversation, summary_trigger_messages, keep_recent_messages, max_recovery_summary_chars)` 生成或复用 recovery summary。
- `_refresh_conversation_compression(conversation, compression_policy)` 根据完整 conversation messages 生成 compression summary dict，并挂到 `conversation.compression_summary`；消息数未超过阈值时清空该字段。
- `_compression_checkpoint_metadata(compression_summary)` 生成 checkpoint metadata，记录是否存在 compression summary、来源范围和摘要长度。
- `_resolve_checkpoint_store(session_store, checkpoint_store)` 决定 checkpoint store。
- `_create_turn_checkpoint(checkpoint_store, session_record, conversation, user_input, project_root)` 在本轮 user input 写入前创建 pre-turn checkpoint，并记录当时是否已有 compression summary。
- `_save_checkpoint_update(checkpoint_store, checkpoint, context_snapshot, tool_call_snapshot, metadata_updates)` 更新同一个 checkpoint 的 snapshot 或 metadata。
- `_next_turn_index(conversation)` 推导下一轮 user turn 编号。
- `_preview_text(text, max_chars)` 生成短文本预览。
- `_utc_now()` 返回 UTC ISO 时间字符串。

`src/wdcode/session/checkpoint.py`

- `TurnCheckpoint` 是单个用户回合的安全点数据结构，保存 pre-turn messages、recovery summary、context snapshot、tool call snapshot、file change snapshot 和 metadata。Phase 4.5 通过 metadata 记录 compression summary 的存在和来源范围。
- `CheckpointStore.__init__(root)` 保存 checkpoint 根目录。
- `CheckpointStore.save(checkpoint)` 把 checkpoint 写成 UTF-8 JSON。
- `CheckpointStore.load(session_id, checkpoint_id)` 按 session id 和 checkpoint id 读取 checkpoint。
- `CheckpointStore.list_for_session(session_id)` 读取某个 session 的所有 checkpoint，并按创建时间稳定排序。
- `CheckpointStore.latest_for_session(session_id)` 返回某个 session 最新的 checkpoint。
- `build_turn_checkpoint(...)` 构造新的 `TurnCheckpoint`，并防御性复制 messages、summary、snapshots 和 metadata。
- `create_checkpoint_id()` 生成可作为文件名使用的 checkpoint id。
- `build_context_snapshot(context)` 保存轻量上下文快照。
- `build_tool_call_snapshot(tool_calls)` 保存轻量工具调用快照，并脱敏参数预览。
- `build_file_change_snapshot(project_root)` 通过短 git 命令保存文件变更概览，不保存正文或 diff。
- `restore_conversation_from_checkpoint(checkpoint)` 根据 checkpoint messages 和 recovery summary 恢复 conversation。

`src/wdcode/session/recovery.py`

- `RecoverySummary` 是长对话恢复摘要的数据结构。
- `split_messages_for_recovery(messages, keep_recent_messages)` 把旧消息和最近消息分开，不修改原 messages。
- `build_recovery_summary(messages, max_summary_chars, keep_recent_messages)` 用规则化方式生成恢复摘要，不调用 LLM。

`src/wdcode/session/__init__.py`

- 当前导出 session store、recovery、checkpoint 和 compression 相关公开对象，包括 `CompressionPolicy`、`ConversationCompression`、`build_conversation_compression`、`conversation_compression_to_dict`、`conversation_compression_from_dict`、`extract_key_files_from_messages`、`extract_key_tool_results` 和 `split_messages_for_compression`。

## 当前测试说明

- `tests/test_session_compression.py` 覆盖 compression policy 校验、消息拆分、压缩摘要生成、摘要截断、关键文件提取、关键工具结果截断、JSON 转换和不修改原 messages。
- `tests/test_message_builder.py` 覆盖无压缩摘要时旧行为、压缩摘要 system message 插入顺序、只保留最近 N 条 messages，以及不修改 conversation.messages。
- `tests/test_session_store.py` 覆盖 compression summary 保存读取，以及旧 session 缺少 compression summary 的兼容加载。
- `tests/test_agent_loop_orchestration.py` 覆盖长 conversation 触发 compression summary、模型只收到摘要和最近 N 条 messages、session 仍保存完整 messages、rollback 后保存对应 compression summary、failure retry 与 checkpoint 不被压缩破坏。
- `tests/test_imports.py` 覆盖 compression 公开对象在无 API key 环境下可导入。

## 尚未开始

- validation repair loop
- 自动代码修复循环
- Eval 任务系统
- CLI checkpoint restore command
- embedding
- tokenizer 级精确压缩
- vector database
- Phase 4.6

## 明确推迟

- TUI
- MCP
- 多 agent
- 长期 memory
- VS Code 插件
- 大规模重构

## API Key Policy

默认测试不需要真实 API key。本项目不读取、不打印、不提交 `.env` 或真实密钥。compression summary 不保存 API key、完整环境变量、文件正文、diff 内容、traceback 全文、完整工具参数或完整工具输出。

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
