# PROJECT_STATE

## 当前状态

当前进入 Phase 4.2：长对话恢复机制最小版。

本阶段已经新增 `RecoverySummary` 和 `src/wdcode/session/recovery.py`。系统现在可以在 conversation messages 超过阈值时，基于已有 messages 生成规则化 recovery summary，并把该 summary 保存到 session JSON 的 `recovery_summary` 字段中。恢复 session 后，`message_builder` 可以把 recovery summary 作为额外 system message 注入模型输入。

当前 recovery summary 不调用真实 LLM，不读取文件正文，不读取 `.env`，不处理 API key。当前也不裁剪旧 messages：session JSON 仍保存完整 conversation messages，summary 只是额外恢复上下文。

当前尚未实现真正上下文压缩、状态快照、失败重试、validation repair loop、数据库、embedding 或向量数据库。Phase 4.3 / 4.4 / 4.5 尚未开始。

## 当前主流程

一次用户输入进入 `run_agent_loop` 后，会先归属到当前内存 conversation。若调用方传入 `session_store`，主循环启动时会根据 `session_id` 尝试加载历史 messages 和 `recovery_summary`；加载成功后用 messages 恢复 `Conversation`，并把 recovery summary 挂到 conversation 上。

构造模型消息时，`build_model_messages` 会在原始 system prompt 后插入 session recovery summary，再插入项目上下文 section。用户请求完成后，主循环会保存 rollback 后或成功后的完整 messages；如果 messages 数量超过阈值，会同时生成并保存 recovery summary。

当前主流程为：

```text
可选加载 session 与 recovery_summary
-> 用户输入
-> conversation 写入用户消息
-> ContextProvider.build
-> build_model_messages 注入 recovery summary 与项目上下文
-> ModelRunner.call
-> route_assistant_message
-> final answer 或 ToolGateway.handle_many
-> conversation 写回结果
-> 可选生成 recovery summary
-> 可选保存 session
```

## 当前代码文件和函数说明

`src/wdcode/session/recovery.py`

- `RecoverySummary` 是恢复摘要的数据结构，记录 `summary`、`source_message_count`、`recent_message_count` 和 `metadata`。`summary` 是可注入模型的文本；`source_message_count` 是摘要覆盖的旧消息数量；`recent_message_count` 是没有进入摘要、仍完整保留的最近消息数量；`metadata` 记录生成方式和是否截断。
- `split_messages_for_recovery(messages, keep_recent_messages=12)` 把 messages 拆成旧消息和最近消息。它返回深拷贝，不修改原 messages；`keep_recent_messages <= 0` 时抛出 `ValueError`。
- `build_recovery_summary(messages, max_summary_chars=4000, keep_recent_messages=12)` 是规则化 recovery summary 的入口。messages 数量不足以产生旧消息时返回 `None`；有旧消息时按用户请求、assistant 进展和工具结果生成稳定文本；超过字符预算时追加 `[TRUNCATED: recovery_summary]`。
- `_summary_lines(old_messages, recent_message_count)` 生成 recovery summary 的主要文本行，包含总旧消息数量、保留的最近消息数量、用户请求、assistant/tool 进展和工具结果。
- `_non_empty_lines(lines)` 保证某一类消息为空时输出 `- none`，让摘要结构稳定。
- `_message_preview(message)` 根据消息 role 生成单行摘要。tool 消息会带上工具名；assistant tool call 消息没有 content 时会显示 tool call 数量。
- `_compact_text(text, max_chars=240)` 把多行文本压成单行，并限制单条预览长度。
- `_apply_summary_budget(text, max_summary_chars)` 应用 recovery summary 字符预算，必要时截断并追加截断标记。

`src/wdcode/session/store.py`

- `SessionRecord` 是一个 session 的持久化数据结构，记录 `session_id`、conversation messages、创建时间、更新时间、metadata，以及可选 `recovery_summary`。
- `create_session_id()` 生成可作为文件名使用的 session id。当前格式是 UTC 时间戳加 8 位 uuid 后缀，例如 `20260602-153012-a1b2c3d4`。
- `validate_session_id(session_id)` 校验 session id。它只允许字母、数字、短横线和下划线，并拒绝空字符串、`..`、`/` 和 `\`，避免路径穿越。
- `SessionStore.__init__(root)` 保存 session 文件目录。CLI 默认目录是项目根目录下的 `.wdcode/sessions`。
- `SessionStore.save(record)` 把 `SessionRecord` 写成 UTF-8 JSON，格式包含 `version: 1`，并使用 `ensure_ascii=False` 和 `indent=2`。Phase 4.2 后 JSON 会包含 `recovery_summary` 字段。
- `SessionStore.load(session_id)` 从 `{session_id}.json` 读回 `SessionRecord`。文件不存在时返回 `None`；JSON 损坏或版本不支持时抛出 `ValueError`。旧格式 session 没有 `recovery_summary` 时仍能加载，字段值为 `None`。
- `SessionStore.exists(session_id)` 判断指定 session 文件是否存在，同时复用 session id 安全校验。
- `SessionStore._path_for(session_id)` 生成 session JSON 路径，只使用通过校验的文件名。

`src/wdcode/session/__init__.py`

- 当前导出 `SessionRecord`、`SessionStore`、`RecoverySummary`、`create_session_id`、`validate_session_id`、`build_recovery_summary` 和 `split_messages_for_recovery`，方便主循环和测试统一从 `wdcode.session` 引用 session 能力。

`src/wdcode/core/conversation.py`

- `Conversation.__init__(system_prompt=SYSTEM_PROMPT, recovery_summary=None)` 创建内存对话，放入默认 system prompt，并保存可选 recovery summary。
- `Conversation.add_user_message(content)` 追加用户消息。
- `Conversation.add_assistant_message(content)` 追加 assistant 最终文本消息。
- `Conversation.add_assistant_tool_call_message(message)` 追加包含 tool calls 的 assistant 消息，并把 tool calls 转成列表保存。
- `Conversation.add_tool_result(tool_call_id, name, content)` 追加工具结果消息。
- `Conversation.remove_last_message()` 删除最后一条非 system 消息。
- `Conversation.checkpoint()` 返回当前消息数量，用作错误回滚点。
- `Conversation.rollback(checkpoint)` 把消息列表回滚到 checkpoint，最低保留 system prompt。
- `Conversation.as_messages()` 返回当前 messages 的浅拷贝，保持旧模型消息构建行为。
- `Conversation.to_messages()` 返回当前 messages 的深拷贝，供 session store 保存，避免外部修改污染 conversation。
- `Conversation.from_messages(messages, recovery_summary=None)` 从保存的 messages 深拷贝恢复一个新的 `Conversation`，并带上可选 recovery summary。

`src/wdcode/core/message_builder.py`

- `build_model_messages(conversation, context=None)` 把 conversation 转为模型输入消息。没有 recovery summary 且没有项目上下文时保持旧行为；有 recovery summary 时，会在原始 system prompt 后插入 `# Session Recovery Summary` system message；有项目上下文时，再插入项目上下文 system message。它不会修改 `conversation.messages` 本体。
- `_recovery_summary_text(recovery_summary)` 从 dict、`RecoverySummary` 对象或普通字符串中取出可注入的 summary 文本；没有 summary 时返回空字符串。

`src/wdcode/core/agent_loop.py`

- `run_agent_loop(client, tool_registry=None, ...)` 是唯一 agent 主编排函数。Phase 4.2 后它新增可选 `summary_trigger_messages`、`keep_recent_messages` 和 `max_recovery_summary_chars` 参数；默认只在启用 `session_store` 时生效。未传 session store 时行为不变。
- `_record_tool_results(conversation, tool_calls, tool_results, trace_writer=None)` 把工具结果写回 conversation，并记录 tool result trace。
- `_trace_assistant_message(trace_writer, route)` 记录 assistant 消息级 trace。
- `_trace_tool_call(trace_writer, tool_call)` 记录单个工具调用的 trace，包括调用 id、工具名和解析后的参数。
- `_write_trace(trace_writer, event_type, payload)` 是 trace 写入的小封装，没有 trace writer 时不做任何事。
- `_write_error(message)` 是默认错误输出函数，把错误消息写到 `stderr`。
- `_trace_tool_arguments(tool_call)` 解析工具调用 JSON 参数，解析失败时保留原始字符串。
- `_tool_name(tool_call)` 从模型 tool call 结构中取出函数名。
- `_load_session_conversation(conversation, session_store, session_id)` 是 session 加载入口。没有 session store 时返回普通 `Conversation`；有 store 时校验或创建 session id，并在找到已有记录时用保存的 messages 和 recovery summary 恢复 conversation。
- `_save_session(session_store, session_record, conversation, ...)` 把当前完整 conversation messages 写回 session store，并在超过阈值时生成 recovery summary。RuntimeError rollback 后也会保存 rollback 后的 messages 和对应 summary。
- `_build_recovery_summary_dict(conversation, summary_trigger_messages, keep_recent_messages, max_recovery_summary_chars)` 判断是否需要生成 recovery summary，并把 `RecoverySummary` 转成可写入 JSON 的 dict。短会话会保留已有 recovery summary，新短会话保持 `None`。
- `_utc_now()` 返回 UTC ISO 时间字符串，用作 session `updated_at`。

`src/wdcode/cli/main.py`

- `parse_args(argv)` 解析 CLI 参数。当前支持 `--session-id` 和 `--session-dir`。
- `create_llm_client(config)` 根据运行时配置创建 OpenAI-compatible client。
- `main(argv=None)` 组装 config、client、默认工具注册表和可选 session store。只有传入 `--session-id` 或 `--session-dir` 时才启用 session 持久化；不传时保持旧交互体验。

`src/cli_assistant.py`

- 兼容入口文件，直接调用 `wdcode.cli.main.main()`。它继承 package CLI 的 session help 参数。

`src/wdcode/context/provider.py`

- `ContextBundle` 是上下文构建结果的数据结构，包含 `text` 和可选 `metadata`。
- `ContextProvider.__init__(project_root=None, max_retrieval_results=8, budget=None)` 保存项目根目录、relevant files 数量上限和上下文预算。没有项目根目录时保持空上下文行为。
- `ContextProvider.build(user_input, conversation)` 构建 AGENTS.md、Repo Map、Recent Files、Symbol Index 和 Relevant Files，并通过 `apply_context_budget` 组合成受控上下文。Phase 4.2 没有修改这段上下文工程逻辑。

`src/wdcode/context/symbol_index.py`

- `SymbolInfo` 记录单个顶层符号的名称、类型和行号。
- `FileSymbols` 记录单个 Python 文件的相对路径、顶层符号和 import 摘要。
- `build_symbol_index(project_root, repo_map, max_files=40)` 使用 Python 内置 `ast` 从 repo map 中的 Python 文件提取顶层 class、function、async function、import 和 from import。
- `format_symbol_index(index)` 把符号索引格式化为文本摘要，不输出源代码正文、函数体或类体。
- `_extract_file_symbols(file_path, relative_path)` 读取单个 Python 文件并解析 AST；语法错误、解码失败或不可读时跳过。
- `_format_from_import(node, name)` 把 `from x import y` 摘要格式化成 `x.y`。
- `_format_symbols(symbols)` 把符号列表格式化为 `name(kind)`。
- `_is_inside_root(path, root)` 防止越界路径进入符号索引。

`src/wdcode/context/budget.py`

- `ContextBudget` 是字符级上下文预算配置，包含 AGENTS、Repo Map、Recent Files、Symbol Index、Relevant Files 和总上下文预算。
- `apply_char_budget(text, max_chars, label=...)` 对单段文本应用字符预算并追加截断标记。
- `apply_context_budget(...)` 合并各上下文 section，并返回每段是否被截断的 metadata。

`src/wdcode/context/recent_files.py`

- `RecentFile` 记录最近变动文件的路径、状态和原因。
- `collect_recent_files(project_root, max_results=12)` 从 git status 和 git diff 中收集最近变动文件；非 git 仓库或 git 失败时返回空 tuple。
- `format_recent_files(files)` 把 recent files 格式化为文本块。
- `_run_git(project_root, args)` 用非 shell subprocess 调用 git。
- `_is_git_repository_root(project_root)` 判断目录本身是否为 git 仓库根目录。
- `_parse_status_line(line)` 解析一行 git short status。
- `_status_from_code(status_code)` 把 git 状态码转换成人类可读状态。
- `_normalize_path(path)` 把 git 输出路径转换成 POSIX 相对路径。

`src/wdcode/context/retrieval.py`

- `RetrievalCandidate` 记录候选相关文件的路径、分数和原因。
- `retrieve_relevant_files(user_input, repo_map, max_results=8)` 只根据 repo map 元数据选择相关文件，不读取文件正文。
- `format_retrieval_candidates(candidates)` 把候选文件格式化为文本块。
- `_score_entry(entry, query_terms)` 给单个 repo map entry 打分。
- `_score_path_terms(path, terms, reason_prefix, reasons)` 复用路径匹配打分逻辑。
- `_query_terms(user_input)` 把用户输入归一化为关键词和特殊意图。

`src/wdcode/context/repo_map.py`

- `RepoMapEntry` 记录单个文件的路径、类型、大小、角色和摘要。
- `RepoMap` 记录项目根目录和所有文件条目。
- `build_repo_map(project_root)` 扫描项目文件，过滤缓存、虚拟环境、构建产物和 `.env`。
- `format_repo_map(repo_map)` 把 repo map 格式化为文本。
- `iter_repo_files(project_root)` 遍历项目文件并应用忽略规则。
- `should_ignore_dir(name)` 判断目录是否应忽略。
- `should_ignore_file(path)` 判断文件是否应忽略。
- `classify_file(path)` 根据扩展名归类文件。
- `is_source_file(relative_path, path)` 判断文件是否是源码文件。
- `is_test_file(relative_path, path)` 判断文件是否是测试文件。
- `is_doc_file(relative_path, path)` 判断文件是否是文档文件。
- `summarize_file(kind, is_source, is_test, is_doc)` 生成文件摘要。
- `role_tags(entry)` 生成源码、测试、文档角色标签。

`src/wdcode/context/agents.py`

- `AgentsContext` 记录 `AGENTS.md` 的路径、正文和存在状态。
- `load_agents_context(project_root)` 只读取项目根目录下的 `AGENTS.md`。
- `format_agents_context(context)` 把 AGENTS 上下文格式化为文本。

`src/wdcode/tools/gateway.py`

- `ToolGateway.__init__(registry, project_root=None, approval_mode="auto")` 保存工具注册表、项目根目录和 approval 模式。
- `ToolGateway.schemas()` 返回工具 schema。
- `ToolGateway.handle(tool_call)` 处理单个工具调用，仍通过 tool guard 做校验并返回统一 `ToolResult`。
- `ToolGateway._failure(error, tool_name="", stage="execution", dry_run=False)` 生成统一失败结果。
- `ToolGateway.handle_many(tool_calls)` 按顺序批量处理工具调用。

## 当前测试说明

- `tests/test_session_recovery.py` 覆盖 recovery summary 生成、messages 拆分、截断标记、非法预算、非法最近消息数量，以及不修改原 messages。
- `tests/test_session_store.py` 覆盖 session id 生成与校验、session JSON 保存和读取、不存在返回 `None`、损坏 JSON、unsupported version、`exists`、`recovery_summary` 保存读取，以及旧格式 session 兼容。
- `tests/test_message_builder.py` 覆盖空 recovery summary 旧行为、项目上下文注入、recovery summary 注入、recovery summary 与项目上下文的顺序，以及不修改 conversation 本体。
- `tests/test_agent_loop_orchestration.py` 覆盖 Conversation 导入导出、默认主循环上下文构建、工具轮数限制、单轮工具数限制、session 保存、同 session 恢复历史、RuntimeError rollback 保存、长会话写入 recovery summary、恢复后注入 recovery summary，以及 rollback 后按回滚状态生成 summary。
- `tests/test_cli_help.py` 覆盖兼容入口和 package 入口的 `--help`，并确认包含 `--session-id` 和 `--session-dir`。
- `tests/test_symbol_index.py` 覆盖最小 Symbol Index 提取和格式化行为。
- `tests/test_context_budget.py` 覆盖上下文预算和截断 metadata。
- `tests/test_context_provider.py` 覆盖上下文组合、recent files、symbol index 和预算截断。
- `tests/test_recent_files.py` 覆盖 git recent files 收集。
- `tests/test_retrieval.py` 覆盖 Smart Retrieval 元数据检索。
- `tests/test_agent_loop_fake_model.py` 覆盖 fake model 下的最终回答、工具调用和坏参数结果写回。
- `tests/test_agent_loop_trace.py` 覆盖 trace 事件和敏感字段脱敏。
- `tests/test_agent_loop_approval.py` 覆盖 dry-run approval 行为。

## 尚未开始

- true context compression
- state snapshot
- retry system
- validation repair loop
- embedding
- vector database
- Phase 4.3
- Phase 4.4
- Phase 4.5

## 明确推迟

- TUI
- MCP
- 多 agent
- 长期 memory
- VS Code 插件
- 大规模重构

## API Key Policy

默认测试不需要真实 API key。本项目不读取、不打印、不提交 `.env` 或真实密钥。Recovery summary 只基于 conversation messages 做规则化摘要，不读取外部敏感文件；session 文件不额外保存 API key、trace、文件正文快照或工具内部临时状态。

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
