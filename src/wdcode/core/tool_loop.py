def run_tool_loop(*args, **kwargs):
    raise RuntimeError(
        "wdcode.core.tool_loop is deprecated; use wdcode.core.agent_loop.run_agent_loop."
    )


__all__ = ["run_tool_loop"]
