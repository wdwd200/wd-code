# PROJECT_STATE

## Current Phase

Phase 3.2：AGENTS.md 注入

## Last Reviewed Source

Phase 3.1 commit：`da8e97d`；当前工作分支为 `phase-2.5-tool-layer-cleanup`。

## Completed

- `src/wdcode/` 已作为正式源码目录存在。
- `src/cli_assistant.py` 是兼容入口。
- 已有 CLI、core、infra、providers、security、tools 等基础目录。
- 已有文件工具和搜索工具的注册入口。
- 已有路径安全相关模块。
- 无 API key 测试基线已存在。
- `run_command` 和 `command_policy` 已实现为保守 allowlist 版本。
- `ToolExecutor` 已抽离为工具执行入口，当前保持工具返回结构不变。
- `ToolResult` 已提供最小统一结果结构，ToolExecutor 现在返回 ToolResult。
- FakeModelClient 风格的无 API key 测试已覆盖 agent/tool loop 核心闭环：普通 assistant 回复、tool_call 成功路径、tool_call 参数失败路径。
- `TraceWriter` 最小 JSONL 记录能力已实现并有测试，能够记录 tool loop 关键事件并对敏感字段做基础脱敏。
- 最小 approval / dry-run 执行保护已落地：`ToolExecutor` 支持 `approval_mode`，dry-run 下读工具允许执行，写文件、编辑文件和运行命令会被统一 `ToolResult` 拦截。
- 最小 git diff rollback 能力已落地：可以捕获 tracked diff 和新增 untracked 普通文件，并用反向 patch 与保守文件删除恢复快照内变更。
- 最小 validation runner 已落地：集中执行 command policy 允许的验证命令，并返回结构化 `ValidationReport`。
- Phase 2.5 已新增 `ToolGateway`，当前 `tool_loop` 已通过网关处理工具调用。
- Phase 2.5 已新增 `tool_guard`，提供工具调用级校验和准备请求的集中入口。
- `ToolRegistry` 已收窄为工具目录职责，只保留注册、查找、列表和 schema 输出；兼容的 `ToolExecutor` 现在转入 `ToolGateway`。
- 工具循环主体已合并进 `agent_loop.run_agent_turn`，`tool_loop.py` 当前仅保留兼容转发入口。
- Phase 2.5 工具层调用链收口已完成：正式路径为 `main -> run_agent_loop -> run_agent_turn -> ToolGateway.handle -> tool_guard.prepare_tool_request -> tool.execute`。
- 旧 `test_tool_loop_*` 测试已迁移为 `test_agent_turn_*`，测试入口不再把 `tool_loop.py` 当作真实执行层。
- Phase 3.1 已新增最小 Repo Map 骨架：当前只做文件级扫描、分类、角色识别和稳定格式化输出，尚未接入 agent loop。
- Phase 3.2 已新增 AGENTS.md 读取与格式化模块：当前只读取仓库根目录 `AGENTS.md`，支持长度截断和稳定上下文格式化，尚未接入 agent loop。

## In Progress

- Phase 3.2 AGENTS.md 上下文模块验证；当前验证命令仍为 `python -m pytest`。

## Not Started

- smart retrieval
- context budget
- recent files
- symbol index
- eval task skeleton

## Explicitly Deferred

- TUI
- MCP
- 多 agent
- 长期 memory
- VS Code 插件
- 大规模重构

## API Key Policy

- 默认测试不需要真实 API key。
- 不读取、不打印、不提交 `.env`。
- live LLM 测试未来必须显式标记，环境变量不存在时自动 skip。
