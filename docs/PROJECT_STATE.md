# PROJECT_STATE

## Current Phase

Phase 2：安全和可回放

## Last Reviewed Source

AGENTS.md 标注的基准 commit：`30f67ef`；本轮以当前工作区可见状态为准。

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

## In Progress

- Phase 2 下一步候选：git diff rollback 或 validation runner。

## Not Started

- validation runner
- repo map
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
