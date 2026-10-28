"""Tools that only a `main_debug.py` run starts: a frame saved per log line, and the remote control the MCP bridge talks to."""


def debug_run():
    """Report whether this is a `main_debug.py` run, the only kind that starts these tools."""
    from ok import og

    return bool((og.config or {}).get('debug'))
