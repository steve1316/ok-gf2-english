# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp==2.3.0"]
# ///
"""MCP server giving Claude a debug run's screen, OCR, settings and clicks.

Claude Code starts this with `uv run --script` (see `.mcp.json`), so `mcp` lives in uv's own environment. Installed
into the app's Python it would upgrade starlette past what FastAPI accepts. Each tool forwards to `src/debug/remote.py`,
which only a `main_debug.py` run serves.
"""

import base64
import contextlib
import json
import threading
import time
import urllib.error
import urllib.request

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

# Where `src/debug/remote.py` listens.
URL = "http://127.0.0.1:47822"
# Seconds to wait for a reply. Above the remote's own 15 s wait for a frame read, so its clearer error arrives first.
TIMEOUT = 30
# Seconds between pings, which keep "MCP connected" in the app's title. Below the remote's `STALE`.
HEARTBEAT = 5

server = MCPServer(
    "gf2",
    instructions="Drives a running `python main_debug.py` session of the GF2 bot. Coordinates are fractions of the 16:9 game frame. "
                 "Actions run when a task reads its next frame, so hold the bot and start a task (`RunGoHome` is safe) before clicking "
                 "through screens yourself, and release it afterwards.",
)


def call(command, **kwargs):
    """Send one command to the debug run and return its result.

    Args:
        command: The remote command name, one of `remote.COMMANDS`.
        **kwargs: The command's arguments.

    Returns:
        The command's result, decoded from JSON.

    Raises:
        ToolError: The debug run is not answering, or the command failed there. Any other exception reaches Claude as
            a bare "Error executing tool", without its message.
    """
    request = urllib.request.Request(f"{URL}/{command}", data=json.dumps(kwargs).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            reply = json.load(response)
    except urllib.error.URLError as error:
        raise ToolError(f"nothing answering on {URL} - start `python main_debug.py` first ({error.reason})") from error
    if not reply["ok"]:
        raise ToolError(reply["error"])
    return reply["result"]


def ping():
    """Tell the debug run this bridge is alive, for as long as Claude Code keeps it open. Any failure is ignored, so the pings never stop."""
    while True:
        with contextlib.suppress(Exception):
            call("status")
        time.sleep(HEARTBEAT)


@server.tool()
def status() -> dict:
    """Which task is running, whether the bot is held, and which tasks are switched on."""
    return call("status")


@server.tool()
def screenshot() -> Image:
    """The game frame the bot last read, as a JPEG."""
    return Image(data=base64.b64decode(call("screenshot")["jpeg"]), format="jpeg")


@server.tool()
def texts() -> list:
    """Run an OCR pass over the current frame as the running task reads it, with each text's centre as fractions of the frame."""
    return call("texts")


@server.tool()
def click(x: float, y: float) -> str:
    """Click a point, given as fractions of the frame from 0 to 1. Runs between the bot's frames, so it never races a handler."""
    return call("click", x=x, y=y)


@server.tool()
def press_key(key: str) -> str:
    """Press a key in the game, such as `esc`."""
    return call("press_key", key=key)


@server.tool()
def hold(on: bool = True) -> dict:
    """Stop the running task at its next frame read, or release it with `on=False`. A held bot still captures, so screenshots stay current."""
    return call("hold", on=on)


@server.tool()
def settings(task: str = "GlobalDailyTask") -> dict:
    """Every setting a task carries, by its config key."""
    return call("settings", task=task)


@server.tool()
def set_setting(key: str, value: str | int | float | bool | list[str], task: str = "GlobalDailyTask") -> str | int | float | bool | list[str]:
    """Change one setting, saved as the settings card would. Upstream's CN task keys are Chinese, so read `settings` for the exact key."""
    return call("set_setting", key=key, value=value, task=task)


@server.tool()
def set_running(task: str, running: bool) -> dict:
    """Start or stop a task such as `GlobalDailyTask` or `RunGoHome`, as its Start and Stop buttons would. Hold the bot first to start it idle."""
    return call("set_running", task=task, running=running)


if __name__ == "__main__":
    threading.Thread(target=ping, name="ping", daemon=True).start()
    server.run()
