# PROJECT_STATE

## 当前状态

当前进入 Phase 3.6：Symbol Index 最小版。

本阶段已经新增基于 Python 内置 `ast` 的最小符号索引。它只读取 repo map 中标记为 Python 的文件，只提取顶层 `class`、普通函数、异步函数、`import` 和 `from import` 摘要，并把这些摘要作为上下文的一段交给模型。它不会保存或输出源代码正文、函数体或类体。

当前 `ContextProvider` 在提供 `project_root` 时，可以组合输出 `AGENTS.md`、Repo Map、Recent Files、Symbol Index 和 Relevant Files。`ContextBudget` 已经支持 Symbol Index section 的独立字符预算和截断 metadata。`project_root=None` 时仍返回空上下文，避免破坏旧调用方式。

当前没有进入 Phase 4，也没有实现 session 持久化、长对话恢复、上下文压缩、失败重试、embedding、向量数据库或 live LLM 默认测试。

## 当前主流程

一次用户输入进入 `run_agent_loop` 后，会先写入 `Conversation`。随后同一个主循环在每一轮中依次调用 `ContextProvider.build`、`build_model_messages`、`ModelRunner.call` 和 `route_assistant_message`。如果模型返回最终回答，就写回 assistant 消息并输出；如果模型返回工具调用，就交给 `ToolGateway.handle_many` 执行，再把工具结果写回 conversation，进入下一轮模型调用。

Phase 3.6 后，`ContextProvider.build` 在有项目根目录时会执行：

```text
build_repo_map -> load_agents_context -> collect_recent_files -> build_symbol_index -> retrieve_relevant_files -> apply_context_budget -> ContextBundle
```

`build_model_messages` 会把非空上下文作为额外 system message 插入到原系统提示词之后，不修改 conversation 本体。

## 当前代码文件和函数说明

`src/wdcode/context/symbol_index.py`

- `SymbolInfo` 是单个顶层符号的数据结构，记录符号名、符号类型和所在行号。当前符号类型只包括 `class`、`function` 和 `async_function`。
- `FileSymbols` 是单个 Python 文件的符号摘要，记录相对项目根目录的 POSIX 路径、顶层类和函数列表，以及顶层 import 摘要。
- `build_symbol_index(project_root, repo_map, max_files=40)` 是 Symbol Index 的入口。它校验项目根目录和 `max_files`，只处理 repo map 中 `kind == "python"` 的文件，并确保目标路径仍位于项目根目录内。它按路径稳定排序，最多返回 `max_files` 个成功解析的文件摘要；遇到语法错误、解码失败或不可读文件时跳过该文件，不中断整体流程。
- `format_symbol_index(index)` 把符号索引格式化为文本。空结果输出 `No Python symbols indexed.`；非空结果按文件列出相对路径、imports 和 symbols。它只输出摘要，不包含绝对路径、源代码正文、函数体或类体。
- `_extract_file_symbols(file_path, relative_path)` 读取单个 Python 文件并用 `ast.parse` 建树，只扫描 AST 顶层节点。它提取顶层 `Import`、`ImportFrom`、`ClassDef`、`FunctionDef` 和 `AsyncFunctionDef`，不会递归输出函数体或类体内容。
- `_format_from_import(node, name)` 把 `from x import y` 格式化为 `x.y` 形式；相对 import 会保留前导点，满足最小摘要需求。
- `_format_symbols(symbols)` 把符号列表格式化为 `name(kind)` 的短文本；没有符号时返回 `none`。
- `_is_inside_root(path, root)` 判断解析后的文件路径是否仍在项目根目录内，用来拦截越界路径。

`src/wdcode/context/budget.py`

- `ContextBudget` 是字符级上下文预算配置，当前包含 `max_total_chars`、`max_agents_chars`、`max_repo_map_chars`、`max_recent_files_chars`、`max_symbol_index_chars` 和 `max_relevant_files_chars`。所有预算值都必须大于 0，否则抛出 `ValueError`。
- `apply_char_budget(text, max_chars, label=...)` 对单段文本应用字符预算。未超长时原样返回；超长时截断并追加 `[TRUNCATED: label]` 标记。
- `apply_context_budget(...)` 先分别按 section 预算截断 AGENTS.md、Repo Map、Recent Files、Symbol Index 和 Relevant Files，再按总预算截断合并后的 Project Context，并返回每段是否截断的 metadata。它保留旧调用方式，未传 `recent_files_text` 或 `symbol_index_text` 时使用空文本。

`src/wdcode/context/provider.py`

- `ContextBundle` 是上下文构建结果的数据结构，包含 `text` 和可选 `metadata`。metadata 里记录预算截断状态、最大检索数量、recent files 数量和 symbol index 文件数量。
- `ContextProvider.__init__(project_root=None, max_retrieval_results=8, budget=None)` 保存项目根目录、relevant files 数量上限和上下文预算。没有项目根目录时保持空上下文行为。
- `ContextProvider.build(user_input, conversation)` 是上下文构建入口。有项目根目录时，它构建 repo map、读取根目录 `AGENTS.md`、收集 recent files、构建 symbol index、选择 relevant files，并通过 `apply_context_budget` 组合成受控的上下文文本。

`src/wdcode/context/recent_files.py`

- `RecentFile` 是最近变动文件的数据结构，记录相对路径、状态和原因。
- `collect_recent_files(project_root, max_results=12)` 从 git 获取最近变动文件。它优先使用 `git status --short --untracked-files=all`，再用 `git diff --name-only` 补充路径；非 git 仓库或 git 命令失败时返回空 tuple。
- `format_recent_files(files)` 把 recent files 格式化为 `# Recent Files` 文本块。没有结果时输出 `No recent files detected.`。
- `_run_git(project_root, args)` 用非 shell 的 subprocess 调用 git，并使用 UTF-8 解码，适配中文路径环境。
- `_is_git_repository_root(project_root)` 确认传入目录本身是 git 仓库根目录，避免测试临时子目录误读父仓库状态。
- `_parse_status_line(line)` 解析 `git status --short` 的一行输出，并在 rename 场景中只保留新路径。
- `_status_from_code(status_code)` 把 git short status 转换为 `modified`、`staged`、`untracked`、`deleted` 或 `renamed`。
- `_normalize_path(path)` 把 git 输出路径转换为 POSIX 风格相对路径。

`src/wdcode/context/retrieval.py`

- `RetrievalCandidate` 是候选相关文件的数据结构，记录文件路径、分数和简短原因。
- `retrieve_relevant_files(user_input, repo_map, max_results=8)` 根据用户输入和 repo map 元数据选出候选文件。它只使用路径、文件类型、summary 和角色标记，不读取文件正文；结果按 score 降序、path 升序稳定排序。
- `format_retrieval_candidates(candidates)` 把候选文件格式化为可注入模型的文本块。没有候选时输出 `No relevant files selected.`。
- `_score_entry(entry, query_terms)` 给单个 repo map entry 打分，覆盖路径、文件名、summary、测试意图、文档意图、工具相关路径、agent 相关路径和 context 目录加分。
- `_score_path_terms(path, terms, reason_prefix, reasons)` 是路径类规则的共用打分函数。
- `_query_terms(user_input)` 把用户输入归一化为关键词，并识别测试、文档、工具、agent、context 等特殊查询意图。

`src/wdcode/context/repo_map.py`

- `RepoMapEntry` 是 repo map 中单个文件的数据结构，记录路径、类型、大小、源码/测试/文档角色和摘要。
- `RepoMap` 是项目文件索引的数据结构，记录根目录和所有条目。
- `build_repo_map(project_root)` 扫描项目根目录，过滤缓存、虚拟环境、构建产物和 `.env`，生成稳定排序的文件索引。
- `format_repo_map(repo_map)` 把 repo map 格式化为文本，包含根目录、文件路径、类型标签和摘要。
- `iter_repo_files(project_root)` 遍历项目文件，并在遍历目录时应用忽略规则。
- `should_ignore_dir(name)` 判断目录名是否应被 repo map 忽略。
- `should_ignore_file(path)` 判断文件是否应被 repo map 忽略。
- `classify_file(path)` 根据扩展名把文件归类为 Python、Markdown、配置、文本或其他。
- `is_source_file(relative_path, path)` 判断文件是否属于 `src` 下的 Python 源码。
- `is_test_file(relative_path, path)` 判断文件是否是测试文件。
- `is_doc_file(relative_path, path)` 判断文件是否是文档文件。
- `summarize_file(kind, is_source, is_test, is_doc)` 为文件生成简短摘要。
- `role_tags(entry)` 根据源码、测试、文档角色生成标签列表。

`src/wdcode/context/agents.py`

- `AgentsContext` 是 `AGENTS.md` 上下文的数据结构，记录路径、正文和是否存在。
- `load_agents_context(project_root)` 只读取项目根目录下的 `AGENTS.md`。文件不存在时返回空正文和 `exists=False`。
- `format_agents_context(context)` 把 AGENTS 上下文格式化为文本。没有文件时输出 `No AGENTS.md found at project root.`。

`src/wdcode/context/__init__.py`

- 当前导出 AGENTS、Repo Map、Retrieval、Recent Files、Symbol Index、ContextProvider 和 Context Budget 相关接口，方便后续模块统一从 `wdcode.context` 引用上下文能力。

`src/wdcode/core/message_builder.py`

- `build_model_messages(conversation, context=None)` 负责把 conversation 转成模型输入消息。空 context 下保持旧行为；非空 context 下，会把上下文作为 system message 插入到原系统提示词之后，并且不修改 conversation 本体。

`src/wdcode/core/agent_loop.py`

- `run_agent_loop(client, tool_registry=None, ...)` 是唯一 agent 主编排函数。它读取用户输入，处理退出命令，把用户消息写入 conversation，并组织上下文构建、模型消息构建、模型调用、回复路由、工具执行、工具结果写回、最终回答输出和错误回滚。
- `_record_tool_results(conversation, tool_calls, tool_results, trace_writer=None)` 把 `ToolGateway.handle_many` 返回的工具结果写回 conversation，并记录 tool result trace。
- `_trace_assistant_message(trace_writer, route)` 记录 assistant 消息级 trace。
- `_trace_tool_call(trace_writer, tool_call)` 记录单个工具调用的 trace，包括调用 id、工具名和解析后的参数。
- `_write_trace(trace_writer, event_type, payload)` 是 trace 写入的小封装，没有 trace writer 时不做任何事。
- `_write_error(message)` 是默认错误输出函数，把错误消息写到 `stderr`。测试可注入 `error_fn`，默认 CLI 行为不变。
- `_trace_tool_arguments(tool_call)` 把工具调用中的 JSON 参数解析成对象，解析失败时保留原始字符串。
- `_tool_name(tool_call)` 从模型 tool call 结构中取出函数名，避免主流程重复写嵌套字段访问。

`src/wdcode/core/tool_loop.py`

- `run_tool_loop(*args, **kwargs)` 只保留 deprecated 提示，不再导入或转发旧的 `run_agent_turn`。项目不再维护第二套 tool loop。

`src/wdcode/tools/gateway.py`

- `ToolGateway.__init__(registry, project_root=None, approval_mode="auto")` 保存工具注册表、项目根目录和 approval 模式。
- `ToolGateway.schemas()` 返回工具 schema，供模型调用前传入。
- `ToolGateway.handle(tool_call)` 处理单个工具调用。它通过 `tool_guard.prepare_tool_request` 做校验和准备，再执行具体工具，并把结果统一封装成 `ToolResult`。
- `ToolGateway._failure(error, tool_name="", stage="execution", dry_run=False)` 生成统一失败结果。
- `ToolGateway.handle_many(tool_calls)` 是批量工具入口。它按顺序逐个调用 `handle`，让 `run_agent_loop` 只面对工具层入口，不关心工具层内部细节。

## 当前测试说明

- `tests/test_symbol_index.py` 覆盖顶层 class、普通函数、异步函数、import、from import、非 Python 文件跳过、语法错误跳过、`max_files`、非法 `max_files`、空格式化输出、相对路径输出，以及不输出函数体或源代码正文。
- `tests/test_context_budget.py` 覆盖字符预算未截断、字符预算截断、非法预算值、Recent Files 预算、Symbol Index 预算、各 section 截断、旧调用方式兼容、总预算截断和 metadata。
- `tests/test_context_provider.py` 覆盖 `project_root=None` 空上下文、有项目根目录时组合 AGENTS / Repo Map / Recent Files / Symbol Index / Relevant Files、recent files metadata、symbol index metadata、预算截断 metadata，以及不输出候选文件正文和符号所在函数体。
- `tests/test_recent_files.py` 覆盖非 git 目录、modified、untracked、deleted、renamed、`max_results`、非法 `max_results`、格式化空输出和相对路径输出。
- `tests/test_retrieval.py` 覆盖路径匹配、文件名匹配、测试意图、context 意图、空输入、`max_results`、非法 `max_results`、稳定排序和格式化输出。
- `tests/test_message_builder.py` 覆盖空 context 旧行为、非空 context system message 注入，以及不修改 conversation 本体。
- `tests/test_agent_loop_fake_model.py` 覆盖无工具调用最终回答、工具调用执行和坏参数工具结果写回。
- `tests/test_agent_loop_trace.py` 覆盖主循环 trace 事件顺序和敏感字段脱敏。
- `tests/test_agent_loop_approval.py` 覆盖 dry-run approval 行为。
- `tests/test_agent_loop_orchestration.py` 覆盖上下文接口调用、max tool rounds 停止和单轮工具数量限制。
- `tests/test_response_router.py` 覆盖 final answer、空内容归一化和 tool calls tuple 化。
- `tests/test_model_runner.py` 覆盖 `ModelRunner` 对 `client.chat` 的委托调用。
- `tests/test_tool_gateway.py` 覆盖 `handle_many` 顺序返回行为。

## 尚未开始

- session persistence
- long conversation restore
- context compression
- retry system
- embedding
- vector database
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

本阶段建议额外验证：

```bash
python src/cli_assistant.py --help
python src/wdcode/cli/main.py --help
```
