# PROJECT_STATE

## Current Phase

Phase 0：架构清理与基线

## Last Reviewed Source

GitHub default branch main，未提供 commit hash，本轮以当前可见状态为准。

## Completed

- `src/wdcode/` 已作为正式源码目录存在。
- `src/cli_assistant.py` 是兼容入口。
- 已有 CLI、core、infra、providers、security、tools 等基础目录。
- 已有文件工具和搜索工具的注册入口。
- 已有路径安全相关模块。
- `run_command` 和 `command_policy` 目前仍是占位。

## In Progress

- 建立无 API key 测试基线。
- 建立项目状态记录文件。

## Not Started

- 真正的 `run_command`
- command policy
- ToolExecutor
- 统一 ToolResult
- trace writer
- approval / dry-run
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
