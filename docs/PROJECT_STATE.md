# PROJECT_STATE

## 当前状态

当前阶段是 Phase 4.6：验证闭环与 Eval 最小版。

本阶段已经新增最小 validation discovery、validation loop 和 eval 结构。系统现在可以先发现基础验证命令，再运行一组验证命令，最后生成可 JSON 序列化的 `ValidationLoopReport`。验证失败时可以生成结构化 `RepairRequest`，但默认不会调用真实 LLM，也不会自动修改代码。

`agent_loop` 新增了可选参数 `validate_after_turn`。默认值仍是 `False`，因此默认 CLI 交互行为不变。只有调用方显式开启，并且存在可用 `project_root` 时，系统才会在本轮最终 assistant 回复生成之后运行 validation loop，并把摘要写入已有的 `SessionRecord.metadata`。

本阶段没有创建最终稳定 tag，没有进入 Phase 5，没有引入数据库、大型 benchmark 框架、embedding、tokenizer 或真实 LLM 自动修复循环。

## 当前主流程

用户输入进入 `run_agent_loop` 后，系统仍按原流程加载或创建 session，创建 pre-turn checkpoint，构建 context，调用模型，处理工具调用，并在成功时保存完整 conversation messages、recovery summary 和 compression summary。

当 `validate_after_turn=False` 时，成功回合不会运行验证，旧 CLI 行为保持不变。

当 `validate_after_turn=True` 且 `tool_registry.project_root` 可用时，系统会在最终 assistant 回复写入 conversation 后运行 `run_validation_loop`。验证结果不会写入 conversation messages，也不会因为验证失败而抛出 `RuntimeError`。如果启用了 session store，验证摘要会写入 session metadata，字段包括 `latest_validation_ok`、`latest_validation_status`、`latest_validation_attempts`、`latest_validation_commands` 和 `latest_validation_report`。

validation loop 会通过 discovery 得到命令计划。默认会发现 `tests/`、`src/cli_assistant.py` 和 `src/wdcode/cli/main.py` 对应的最小验证命令；如果调用方显式传入命令，则显式命令优先。

## 代码文件和函数说明

### `src/wdcode/validation/discovery.py`

- `PYTEST_COMMAND` 表示默认 pytest 验证命令，当前值是 `python -m pytest`。
- `CLI_ASSISTANT_HELP_COMMAND` 表示兼容入口脚本的 help 验证命令，当前值是 `python src/cli_assistant.py --help`。
- `PACKAGE_CLI_HELP_COMMAND` 表示包内 CLI 入口的 help 验证命令，当前值是 `python src/wdcode/cli/main.py --help`。
- `ValidationPlan` 描述一次验证命令发现结果。它保存命令列表、命令来源、项目根目录字符串和轻量 metadata。
- `discover_validation_plan(project_root, explicit_commands=None)` 是验证命令发现入口。显式命令非空时直接使用显式命令；否则只检查目录和文件是否存在，不读取文件正文，不执行命令，并按规则发现 pytest 和 CLI help 命令；如果没有发现命令，则回退到 `python -m pytest`。
- `_build_metadata(root)` 生成 discovery metadata。它只记录项目根目录是否存在、是否是目录、`tests/` 是否存在、两个 CLI 入口文件是否存在。
- `_dedupe_commands(commands)` 对命令做稳定去重，过滤非字符串、空字符串和重复命令，保留首次出现顺序。

### `src/wdcode/validation/runner.py`

- `DEFAULT_VALIDATION_COMMANDS` 定义 runner 默认命令，当前是 `["python -m pytest"]`。
- `ValidationCommandResult` 描述单条验证命令的运行结果，包含命令、是否成功、退出码、stdout、stderr、耗时和错误信息。
- `ValidationCommandResult.to_dict()` 把单条验证结果转换成普通 dict，保持向后兼容。
- `ValidationReport` 描述一组验证命令的运行结果，包含整体是否成功和每条命令结果。
- `ValidationReport.to_dict()` 把验证报告转换成 JSON 友好的 dict，保留每条 command result 的完整字段。
- `run_validation(project_root, commands=None, timeout=60, trace_writer=None)` 是验证命令执行入口。它逐条执行验证命令，写入 `validation_started`、`validation_command_finished` 和 `validation_finished` trace 事件，并返回 `ValidationReport`。
- `_run_validation_command(project_root, command, timeout)` 执行单条验证命令。它先检查项目根目录，再检查命令策略，使用 `subprocess.run(..., shell=False)` 执行命令，并把超时和异常转换成结构化失败结果。
- `_failure(command, duration_ms, error)` 构造不执行命令时的失败结果。
- `elapsed_ms(start)` 根据开始时间计算毫秒耗时。
- `_normalize_output(output)` 把 subprocess 的 bytes、字符串或空输出统一转换为字符串。
- `_validation_command_argv(command)` 只为 validation runner 内部提供两个固定 CLI help 命令的 argv。它不会扩大通用 `run_command` 工具的命令白名单。
- `_write_trace(trace_writer, event_type, payload)` 在传入 trace writer 时写入 trace 事件。

### `src/wdcode/validation/loop.py`

- `DEFAULT_OUTPUT_PREVIEW_CHARS` 定义 validation loop 中 stdout、stderr、error 和 metadata 的默认预览长度。
- `SENSITIVE_KEY_PARTS` 定义 metadata 脱敏时使用的敏感字段名片段。
- `ValidationLoopPolicy` 描述验证循环策略，包含最大尝试次数、是否允许生成 repair request 并调用 fake repair callback，以及输出预览长度。`max_attempts` 和 `output_preview_chars` 小于等于 0 时会抛出 `ValueError`。
- `RepairRequest` 描述验证失败后的结构化修复请求，包含失败 attempt、失败命令、失败摘要、修复 prompt 和 metadata。
- `ValidationLoopReport` 描述一次 validation loop 的最终报告，包含整体是否成功、尝试次数、每次验证报告预览、repair request 列表、最终状态和 metadata。
- `run_validation_loop(project_root, commands=None, policy=None, trace_writer=None, repair_callback=None)` 是验证闭环入口。它先调用 discovery，再运行 `run_validation`，成功时返回 `final_status="passed"`；失败且不允许 repair 时返回 `final_status="failed"`；失败且允许 repair 时生成 `RepairRequest`，仅当 fake callback 返回 truthy 且未超过最大尝试次数时才进入下一次验证。
- `build_repair_request(validation_report, attempt, output_preview_chars=4000)` 根据 `ValidationReport` 生成修复请求。prompt 以 `# Validation Repair Request` 开头，只包含失败命令、退出码和 stdout/stderr/error 的短预览。
- `validation_loop_report_to_dict(report)` 把 `ValidationLoopReport` 转换成 JSON 友好的 dict，并对 metadata 做递归脱敏和截断。
- `repair_request_to_dict(request)` 把 `RepairRequest` 转换成 JSON 友好的 dict。
- `_validation_report_to_preview_dict(report, max_chars)` 把完整 `ValidationReport` 转换成只保存短输出预览的 dict。
- `_validation_result_to_preview_dict(result, max_chars)` 把单条 `ValidationCommandResult` 转换成预览结构，记录 stdout、stderr 和 error 是否被截断。
- `_preview_with_truncation(value, max_chars)` 生成截断预览，并追加 `[TRUNCATED: validation_output]` 标记。
- `_preview_text(value, max_chars)` 返回只包含预览文本的简化结果。
- `_normalize_text(value)` 把任意值转换成字符串，`None` 转换为空字符串。
- `_strip_stack_trace_text(text)` 去掉 traceback 关键词，避免报告保存完整堆栈文本。
- `_redact_sensitive_text(text)` 对 `.env`、`api_key`、`authorization` 等短文本标记做基础脱敏。
- `_safe_value(value, max_chars)` 递归清洗 dict、list、tuple 和字符串，敏感 key 下的值会被替换成 `[redacted]`，长字符串会被截断。
- `_is_sensitive_key(key)` 判断 metadata key 是否包含敏感字段名片段。
- `_policy_to_dict(policy)` 把 `ValidationLoopPolicy` 转换成普通 dict，用于 trace payload。
- `_write_trace(trace_writer, event_type, payload)` 在传入 trace writer 时写入 loop trace 事件。

### `src/wdcode/validation/__init__.py`

- 当前公开导出 runner、discovery 和 loop 的主要类型与函数，包括 `ValidationPlan`、`discover_validation_plan`、`ValidationLoopPolicy`、`RepairRequest`、`ValidationLoopReport`、`run_validation_loop`、`build_repair_request`、`validation_loop_report_to_dict`、`repair_request_to_dict`、`ValidationCommandResult`、`ValidationReport` 和 `run_validation`。

### `src/wdcode/eval/tasks.py`

- `SENSITIVE_KEY_PARTS` 定义 Eval metadata 脱敏时使用的敏感字段名片段。
- `EvalTask` 描述一个最小 eval 任务，包含 task id、任务名称、提示文本、验证命令列表和 metadata。`task_id`、`name`、`prompt` 和 `validation_commands` 不能为空。
- `EvalResult` 描述一个 eval 任务的结果，包含 task id、是否成功、validation loop 报告和 metadata。
- `run_eval_task(task, project_root, validation_policy=None, trace_writer=None)` 运行一个 eval 任务。它不会调用真实 LLM，只会把任务里的验证命令交给 `run_validation_loop`，并把结果包装成 `EvalResult`。
- `eval_task_to_dict(task)` 把 `EvalTask` 转换成 JSON 友好的 dict，并清洗 metadata。
- `eval_result_to_dict(result)` 把 `EvalResult` 转换成 JSON 友好的 dict，并清洗 metadata。
- `_safe_value(value)` 递归清洗 Eval metadata，敏感 key 会被替换成 `[redacted]`，超长字符串会被截断。
- `_is_sensitive_key(key)` 判断 Eval metadata key 是否包含敏感字段名片段。

### `src/wdcode/eval/__init__.py`

- 当前公开导出 eval 最小结构和入口函数，包括 `EvalTask`、`EvalResult`、`run_eval_task`、`eval_task_to_dict` 和 `eval_result_to_dict`。

### `src/wdcode/core/agent_loop.py`

- `run_agent_loop(client, tool_registry, ...)` 是主编排入口。本阶段新增 `validate_after_turn`、`validation_commands` 和 `validation_policy` 可选参数。默认不运行 validation loop；显式开启时，在最终 assistant 回复后运行验证，并在 session metadata 中记录摘要。
- `_ToolExecutionFailure` 是工具重试内部异常类型，只在显式启用工具执行错误重试时使用。
- `_record_tool_results(conversation, tool_calls, tool_results, trace_writer=None)` 把工具结果写回完整 conversation，并写入 trace。
- `_handle_many_tools(tool_gateway, tool_calls, retry_policy)` 调用工具网关执行多条工具调用，并在需要时把执行失败升级为内部异常。
- `_should_raise_tool_result_failure(tool_results, retry_policy)` 判断工具执行失败是否应该触发重试。
- `_tool_failure_message(tool_results)` 从失败工具结果中生成短错误消息。
- `_trace_assistant_message(trace_writer, route)` 记录 assistant 消息 trace，包含内容和是否包含工具调用。
- `_trace_tool_call(trace_writer, tool_call)` 记录工具调用 trace，包含工具名和已解析的参数。
- `_write_trace(trace_writer, event_type, payload)` 是 trace 写入封装。
- `_write_error(message)` 是默认错误输出函数。
- `_trace_tool_arguments(tool_call)` 尝试把工具参数从 JSON 字符串解析为对象，解析失败时保留原始短文本。
- `_tool_name(tool_call)` 从 tool call 中取出函数名。
- `_load_session_conversation(conversation, session_store, session_id)` 加载或创建 session，并恢复完整 messages、recovery summary 和 compression summary。
- `_save_session(session_store, session_record, conversation, checkpoint, rolled_back, failure_report, ..., validation_report=None)` 保存完整 session。它继续刷新 recovery summary 和 compression summary，并在传入 validation report 时写入 validation metadata。
- `_run_turn_validation(validate_after_turn, project_root, validation_commands, validation_policy, trace_writer)` 是 agent loop 的验证入口。默认关闭；开启后调用 `run_validation_loop`，并把结果转换成 dict。验证入口异常会被转换成失败报告，不会打断 assistant 回复。
- `_latest_report_with_events(current, candidate)` 选择最近包含事件的 failure report。
- `_failure_report_from_exception(exc, current_report)` 从异常中提取或构造 failure report。
- `_record_failure_metadata(metadata, failure_report, checkpoint)` 把最近 failure report 摘要写入 session metadata。
- `_record_validation_metadata(metadata, validation_report)` 把最近 validation loop 摘要写入 session metadata。
- `_build_recovery_summary_dict(conversation, summary_trigger_messages, keep_recent_messages, max_recovery_summary_chars)` 根据完整 conversation 生成或复用 recovery summary。
- `_refresh_conversation_compression(conversation, compression_policy)` 根据完整 conversation 生成 compression summary，并挂到 conversation 上。
- `_compression_checkpoint_metadata(compression_summary)` 生成 checkpoint metadata，用于记录是否存在 compression summary 和它的来源范围。
- `_resolve_checkpoint_store(session_store, checkpoint_store)` 决定本轮使用哪个 checkpoint store。
- `_create_turn_checkpoint(checkpoint_store, session_record, conversation, user_input, project_root)` 在 user input 写入前创建 pre-turn checkpoint。
- `_save_checkpoint_update(checkpoint_store, checkpoint, context_snapshot, tool_call_snapshot, metadata_updates)` 更新同一个 checkpoint 的 snapshot 或 metadata。
- `_next_turn_index(conversation)` 根据已有 user 消息数量推导下一轮用户回合编号。
- `_preview_text(text, max_chars=500)` 生成单行短文本预览。
- `_utc_now()` 返回 UTC ISO 时间字符串。

### `src/wdcode/session/store.py`

- `SessionRecord` 是 session 持久化数据结构。它继续保存完整 messages、metadata、recovery summary 和 compression summary；本阶段没有新增破坏性字段，validation 摘要直接保存在现有 metadata 中。
- `create_session_id()` 生成可作为文件名使用的 session id。
- `validate_session_id(session_id)` 校验 session id，拒绝空字符串、路径分隔符、`..` 和非法字符。
- `SessionStore.__init__(root)` 保存 session 文件根目录。
- `SessionStore.save(record)` 把 `SessionRecord` 写成 UTF-8 JSON，继续使用 version 1。
- `SessionStore.load(session_id)` 从 JSON 文件恢复 `SessionRecord`，兼容缺少 metadata、recovery summary 或 compression summary 的旧 session。
- `SessionStore.exists(session_id)` 判断 session JSON 是否存在。
- `SessionStore._path_for(session_id)` 根据 session id 生成 session JSON 路径。

### `src/wdcode/session/__init__.py`

- 当前继续公开导出 session、checkpoint、recovery 和 compression 相关对象。本阶段不需要为 validation metadata 新增 session 模型字段，因此该文件没有新增 validation 专用导出。

## 测试文件说明

- `tests/test_validation_discovery.py` 覆盖显式命令优先、tests 目录发现、两个 CLI help 入口发现、稳定去重、项目根目录不存在时回退默认命令、空项目回退 pytest。
- `tests/test_validation_loop.py` 覆盖 policy 参数校验、首轮通过、失败但不 repair、失败生成 repair request、fake repair callback 后重试、达到最大 attempts 后失败、长 stdout/stderr 截断、JSON 序列化和 trace 事件。
- `tests/test_eval_tasks.py` 覆盖 `EvalTask` 必填字段校验、`run_eval_task` 只运行 validation loop、不调用真实 LLM，以及成功和失败结果。
- `tests/test_agent_loop_orchestration.py` 新增覆盖默认不运行 validation loop、显式开启后运行验证、成功和失败验证都写入 session metadata、验证失败不抛 runtime error、不修改 conversation messages、无 session store 时不写 session metadata。
- `tests/test_session_store.py` 新增覆盖 validation metadata 可以和 recovery summary、compression summary 一起保存和读取。
- `tests/test_imports.py` 新增覆盖 validation discovery、validation loop 和 eval 公开对象在无 API key 环境中可导入。
- `tests/test_validation_runner.py` 新增覆盖 validation runner 内部允许 discovery 固定发现的两个 CLI help 命令，同时保留 `shell=False`。

## 当前验证命令

当前主要验证命令仍是：

```bash
python -m pytest
```

本阶段也建议额外验证：

```bash
python src/cli_assistant.py --help
python src/wdcode/cli/main.py --help
git diff --check
```

## API Key 和敏感信息策略

本阶段不需要真实 API key。默认测试不调用真实 LLM，不读取 `.env`，不打印或提交真实密钥。

`ValidationLoopReport`、`RepairRequest` 和 `EvalResult` 不保存完整超长 stdout/stderr，不保存文件正文，不保存 diff，不保存完整 traceback，不保存完整工具参数或完整工具输出。metadata 中疑似包含 key、token、secret、password、credential、authorization、api_key 的字段会被脱敏。

## 尚未开始

- 自动代码修复循环
- 大型 benchmark 系统
- CLI checkpoint restore command
- embedding
- tokenizer 级精确压缩
- vector database
- Phase 5

## 明确推迟

- TUI
- MCP
- 多 agent
- 长期 memory
- VS Code 插件
- 大规模重构
