# PROJECT_STATE

## 当前状态

当前进入 Phase 4.4：失败恢复 / 重试机制最小版。

本阶段已经新增最小失败恢复模块 `src/wdcode/core/failure_recovery.py`，用于描述失败类型、判断是否可以重试、按策略包装一次模型或工具调用，并生成可以写入 session metadata 的 failure report。

模型调用现在默认使用 `RetryPolicy(max_attempts=2)`。工具调用也经过同一套重试包装，但默认策略是 `RetryPolicy(max_attempts=1, retry_tool_errors=False)`，也就是默认不重复执行可能有副作用的工具。只有调用方显式传入 `retry_tool_errors=True` 且 `max_attempts > 1` 时，执行阶段失败的工具结果才会触发重试。

最终失败时，主循环仍沿用 Phase 4.3 的 checkpoint / rollback 能力：本轮 user input 加入 conversation 前会保存 pre-turn checkpoint；失败后 conversation 回滚到内存 checkpoint，并在 session metadata 中记录 rollback checkpoint id 和最近一次 failure report 摘要。

当前不实现 validation repair loop，不实现自动代码修复循环，不实现真正上下文压缩，不实现 Eval 任务系统，也不改变 CLI 默认交互行为。

## 当前主流程

一次非空用户输入进入 `run_agent_loop` 后，系统会按当前 session 恢复 conversation 和 recovery summary。启用 session store 时，本轮处理前会保存一个 pre-turn `TurnCheckpoint`。随后 user input 写入 conversation，系统构建项目上下文，更新 checkpoint 的 context snapshot，再构建模型消息。

模型调用通过 `call_with_retries` 包装。成功时继续路由 assistant message；如果期间发生过可重试错误，会把成功后的 failure report 保留到本轮 session metadata。模型最终失败时，会生成 failed failure report、回滚 conversation、更新 checkpoint metadata，并保存 session。

如果模型返回 tool calls，系统会先保存 tool call snapshot，再记录 assistant tool-call message。工具调用同样通过 `call_with_retries` 包装，但默认不会重试执行失败；默认情况下工具失败仍作为 `ToolResult.failure` 写回 conversation，让模型自行处理。显式开启工具错误重试时，执行阶段失败会升级为内部 `_ToolExecutionFailure`，并按传入策略重新运行该批工具调用。

成功完成本轮后，系统保存 session messages、recovery summary、latest checkpoint id，以及可选的 latest failure report 摘要。

## 代码文件和函数说明

`src/wdcode/core/failure_recovery.py`

- `RetryPolicy` 描述重试策略。它记录最大尝试次数，以及 transient、timeout、rate_limit、tool_error 四类错误是否允许重试；当 `max_attempts <= 0` 时会抛出 `ValueError`，避免出现无效策略。
- `FailureEvent` 描述一次失败事件。它记录失败来自 model、tool、validation、runtime 还是 unknown，失败类别是什么，短错误消息、异常类型、当前尝试次数、最大尝试次数、是否还能重试，以及经过清洗的 metadata。
- `FailureReport` 描述一次调用链路的失败报告。它保存若干个 `FailureEvent`，记录最终状态是 success 还是 failed，并携带经过清洗的报告级 metadata。
- `RetryResult` 是 `call_with_retries` 成功返回时的包装结果。它同时返回真实调用值和本次调用形成的 `FailureReport`。
- `classify_exception(exc, component, attempt, max_attempts, metadata)` 把异常转换成 `FailureEvent`。当前会把 `TimeoutError` 归为 `timeout`，`ConnectionError` 归为 `transient`，`PermissionError` 归为 `permission_error`，`ValueError` / `TypeError` 归为 `invalid_request`，工具组件里的 `RuntimeError` 归为 `tool_error`，带 rate limit 特征的异常归为 `rate_limit`，其他异常归为 `unknown`。
- `should_retry(event, policy)` 根据失败事件和策略判断是否继续尝试。它会先检查当前 attempt 是否已经达到上限，然后分别按策略字段处理 timeout、transient、rate_limit 和 tool_error；permission_error、invalid_request 和 validation_error 默认不重试。
- `call_with_retries(func, component, policy, metadata)` 执行传入的零参数函数。调用成功时返回 `RetryResult`；调用失败时会分类异常，必要时继续重试；最终失败时重新抛出最后一个异常，并在异常对象上附加 `failure_report` 属性。
- `build_validation_failure_event(command, returncode, output_preview, attempt, max_attempts)` 只构造验证失败事件，不执行验证命令。它会保留命令、返回码和最多 1000 字符的输出预览，为后续验证闭环预留结构。
- `failure_event_to_dict(event)` 把单个失败事件转换成 JSON 可序列化 dict，并再次截断 message、清洗 metadata。
- `failure_report_to_dict(report)` 把失败报告转换成 JSON 可序列化 dict，用于写入 session metadata。
- `_category_for_exception(exc, component)` 是内部分类 helper，集中维护异常类型到失败类别的映射。
- `_safe_metadata(value)` 是内部 metadata 清洗入口。它会防御性复制 dict，递归处理基础 JSON 类型，并对 key、token、secret、password、credential、authorization、api_key 等敏感字段做 `[REDACTED]`。
- `_safe_metadata_value(value, max_chars)` 处理 metadata 中的单个值。字符串会被截断，list / tuple 只保留前 20 项，未知对象转成短字符串。
- `_metadata_string_limit(key)` 决定 metadata 字符串截断长度。普通字段默认 500 字符，`output_preview` 保留 1000 字符。
- `_is_sensitive_key(key)` 判断字段名是否带有敏感含义。
- `_preview_text(text, max_chars)` 把文本压成单行短预览。
- `_exception_message(exc)` 从异常文本中提取短消息，避免把 traceback 正文写入 failure report。

`src/wdcode/core/agent_loop.py`

- `run_agent_loop(client, tool_registry, ...)` 是主编排函数。Phase 4.4 新增 `model_retry_policy` 和 `tool_retry_policy` 两个可选参数；模型调用默认最多尝试 2 次，工具调用默认只尝试 1 次。它会在成功、失败、rollback 和 session 保存之间传递本轮的 latest failure report。
- `_ToolExecutionFailure` 是内部异常类型，只在显式开启工具错误重试时使用。它把执行阶段失败的 `ToolResult.failure` 转换成 retry wrapper 可以识别的工具异常。
- `_record_tool_results(conversation, tool_calls, tool_results, trace_writer)` 把工具结果写回 conversation，并保持原有 `ToolResult.to_dict()` 外部格式不变。
- `_handle_many_tools(tool_gateway, tool_calls, retry_policy)` 调用 `ToolGateway.handle_many`。默认直接返回工具结果；显式开启工具错误重试时，如果有执行阶段失败结果，会抛出 `_ToolExecutionFailure` 让 `call_with_retries` 重试。
- `_should_raise_tool_result_failure(tool_results, retry_policy)` 判断当前工具结果是否应该升级为内部可重试失败。只有 `retry_tool_errors=True` 且 `max_attempts > 1` 时才可能返回 true。
- `_tool_failure_message(tool_results)` 从失败的工具结果中生成短错误消息，用于 failure report。
- `_trace_assistant_message(trace_writer, route)` 记录 assistant 消息 trace，只包含内容和是否有 tool calls。
- `_trace_tool_call(trace_writer, tool_call)` 记录工具调用 trace，并继续使用已有参数脱敏逻辑。
- `_write_trace(trace_writer, event_type, payload)` 是 trace 写入的小封装。
- `_write_error(message)` 是默认错误输出函数。
- `_trace_tool_arguments(tool_call)` 解析工具参数 JSON；解析失败时保留原始短文本，供 trace 使用。
- `_tool_name(tool_call)` 从 tool call 中取函数名。
- `_load_session_conversation(conversation, session_store, session_id)` 创建或加载 session，并把已保存的 messages 和 recovery summary 恢复到 conversation。
- `_save_session(session_store, session_record, conversation, checkpoint, rolled_back, failure_report, ...)` 保存 session。它会写入 messages、recovery summary、checkpoint metadata；当 failure report 存在时，还会写入 `latest_failure_report`、`latest_failure_component`、`latest_failure_category`、`latest_failure_retryable`、`latest_failure_attempts` 和 `latest_failure_checkpoint_id`。
- `_latest_report_with_events(current, candidate)` 只在候选报告中真正存在失败事件时更新本轮 latest failure report。
- `_failure_report_from_exception(exc, current_report)` 从异常对象上读取 `failure_report`；如果没有，则根据 runtime 异常构造一个最小 failed report。
- `_record_failure_metadata(metadata, failure_report, checkpoint)` 把失败报告摘要写入 session metadata。
- `_build_recovery_summary_dict(conversation, summary_trigger_messages, keep_recent_messages, max_recovery_summary_chars)` 判断是否需要生成长对话恢复摘要，并转换成 JSON dict。
- `_resolve_checkpoint_store(session_store, checkpoint_store)` 决定是否启用 checkpoint store；传入 checkpoint store 时优先使用，只有 session store 存在时才默认创建 checkpoint store。
- `_create_turn_checkpoint(checkpoint_store, session_record, conversation, user_input, project_root)` 在本轮 user input 写入 conversation 前创建 pre-turn checkpoint。
- `_save_checkpoint_update(checkpoint_store, checkpoint, context_snapshot, tool_call_snapshot, metadata_updates)` 更新同一个 checkpoint 的 context snapshot、tool call snapshot 或 metadata。
- `_next_turn_index(conversation)` 根据现有 user 消息数量推导下一轮编号。
- `_preview_text(text, max_chars)` 生成 user input 等短文本预览。
- `_utc_now()` 返回 UTC ISO 时间字符串，用于 session 更新时间。

`src/wdcode/session/store.py`

- `SessionRecord` 是 session 持久化数据结构，记录 session id、conversation messages、创建时间、更新时间、metadata 和可选 recovery summary。本阶段复用已有 metadata 字段存放 failure report 摘要。
- `create_session_id()` 生成可作为文件名使用的 session id。
- `validate_session_id(session_id)` 校验 session id，只允许字母、数字、短横线和下划线，并拒绝空字符串、`..`、`/` 和 `\`。
- `SessionStore.__init__(root)` 保存 session 文件根目录。
- `SessionStore.save(record)` 把 `SessionRecord` 写成 UTF-8 JSON，继续使用 version 1 格式，并包含 metadata 和 recovery summary。
- `SessionStore.load(session_id)` 从 JSON 文件恢复 `SessionRecord`。旧 session 文件没有 metadata 或 recovery summary 时仍可正常加载。
- `SessionStore.exists(session_id)` 判断指定 session 文件是否存在。
- `SessionStore._path_for(session_id)` 根据 session id 生成 JSON 文件路径。

`src/wdcode/session/checkpoint.py`

- `TurnCheckpoint` 是单个用户回合的安全点数据结构，保存 pre-turn messages、recovery summary、context snapshot、tool call snapshot、file change snapshot 和 metadata。
- `CheckpointStore.__init__(root)` 保存 checkpoint 根目录。
- `CheckpointStore.save(checkpoint)` 把 checkpoint 写成 UTF-8 JSON。
- `CheckpointStore.load(session_id, checkpoint_id)` 按 session id 和 checkpoint id 读取 checkpoint。
- `CheckpointStore.list_for_session(session_id)` 读取某个 session 的所有 checkpoint，并按创建时间稳定排序。
- `CheckpointStore.latest_for_session(session_id)` 返回某个 session 最新的 checkpoint。
- `build_turn_checkpoint(...)` 构造新的 `TurnCheckpoint`，并防御性复制 messages、summary、snapshots 和 metadata。
- `create_checkpoint_id()` 生成可作为文件名使用的 checkpoint id。
- `build_context_snapshot(context)` 保存轻量上下文快照，只记录是否有文本、字符数、短预览、是否截断和 context metadata。
- `build_tool_call_snapshot(tool_calls)` 保存轻量工具调用快照，只记录 tool call id、工具名和脱敏后的参数短预览。
- `build_file_change_snapshot(project_root)` 通过短 git 命令保存文件变更概览，不保存文件正文或 diff 内容。
- `restore_conversation_from_checkpoint(checkpoint)` 根据 checkpoint messages 和 recovery summary 恢复一个内存 conversation。

`src/wdcode/session/recovery.py`

- `RecoverySummary` 是长对话恢复摘要的数据结构。
- `split_messages_for_recovery(messages, keep_recent_messages)` 把旧消息和最近消息分开，不修改原 messages。
- `build_recovery_summary(messages, max_summary_chars, keep_recent_messages)` 用规则化方式生成恢复摘要，不调用 LLM。

`src/wdcode/session/__init__.py`

- 当前继续导出 session store、recovery、checkpoint 相关公开对象。本阶段没有新增 session 包级导出。

## 当前测试说明

- `tests/test_failure_recovery.py` 覆盖 `RetryPolicy`、失败分类、retry 判断、`call_with_retries` 成功和失败路径、failure report JSON 化、metadata 脱敏，以及 validation failure helper 的输出截断。
- `tests/test_agent_loop_orchestration.py` 继续覆盖主循环、session、checkpoint、rollback、recovery summary，并新增模型 timeout 后成功重试、模型最终失败 metadata、默认工具失败不重试、显式工具失败重试等用例。
- `tests/test_session_store.py` 覆盖 session JSON 保存读取、metadata 保存读取、旧格式缺少 metadata / recovery summary 的兼容加载。
- `tests/test_imports.py` 覆盖 `RetryPolicy`、`FailureEvent`、`FailureReport` 在无 API key 环境下可导入。

## 尚未开始

- validation repair loop
- 自动代码修复循环
- true context compression
- message pruning
- Eval 任务系统
- CLI checkpoint restore command
- embedding
- vector database
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

默认测试不需要真实 API key。本项目不读取、不打印、不提交 `.env` 或真实密钥。failure report 不保存 API key、完整环境变量、完整工具参数、完整文件正文、traceback 正文或 diff 内容。

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
