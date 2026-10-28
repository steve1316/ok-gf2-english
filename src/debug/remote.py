"""Serve a debug run's frame, OCR and settings on localhost, and take clicks between its frames.

`main_debug.py` answers a few JSON commands for `scripts/gf2_mcp.py`, so a screen can be read and a button pressed with nobody at the desk. The Global
flows are straight-line code with no per-frame hook of their own, so actions queue for `TaskExecutor.next_frame` instead. Every flow reads its frames
through it, so a click lands on the bot's own thread between two frames and never races the flow. Release runs never start it.
"""

import base64
import concurrent.futures
import functools
import http.server
import json
import queue
import threading
import time

import cv2
from PySide6.QtCore import QTimer

from ok import Logger, TaskExecutor

from src.debug import debug_run, frame_log

logger = Logger.get_logger(__name__)

# Loopback only, so nothing off this machine can reach it. One above ok-czn-english's 47821, so both debug runs can be up at once.
# `scripts/gf2_mcp.py` carries the same address.
HOST = '127.0.0.1'
PORT = 47822
# Seconds an action waits for the bot to read a frame. Polls read one every second or two, so only a long bare sleep or no task at all runs this out.
ACTION_TIMEOUT = 15
# Seconds the bot waits after a remote click or key before reading the next frame.
AFTER_INPUT = 1
# Seconds between captures while the bot is held and nothing is asked of it. A queued action or a release wakes it at once, so this only sets how
# stale an idle screenshot can get.
HOLD_POLL = 1.0
# JPEG quality for frames sent out. A 1080p frame comes to ~0.3 MB.
QUALITY = 90
# The task a settings command reads when none is named.
DEFAULT_TASK = 'GlobalDailyTask'
# The functions below a request may name, so a path can never reach anything else in the module.
COMMANDS = ('status', 'screenshot', 'texts', 'click', 'press_key', 'hold', 'settings', 'set_setting', 'set_running')
# Seconds since the last request before the window title stops saying the MCP bridge is connected.
STALE = 15
# How often, in milliseconds, the window title is brought up to date.
TITLE_CHECK = 2000
# Where the main window class lives, newest layout first. ok-script's app builds `ok.gui`'s, and `ok.ui.qt` is the older layout.
MAIN_WINDOWS = ('ok.gui.MainWindow', 'ok.ui.qt.MainWindow')

# Actions waiting for the bot's thread, as `(action, future)` pairs.
_actions = queue.Queue()
# Set while the bot is held, so it waits in its frame read and nothing in the flow moves.
_held = threading.Event()
# Set when an action is queued or the bot is released, so a held bot answers at once rather than on its next `HOLD_POLL`.
_wake = threading.Event()
# True while an action runs, so a frame it reads itself does not run the next action inside it.
_running = False
# `time.monotonic()` of the last request, from the MCP bridge's pings or a tool call.
_last_contact = None
_patched = False


class Remote(http.server.BaseHTTPRequestHandler):
    """Answer `POST /<command>` with a JSON body of keyword arguments, replying `{"ok", "result" | "error"}`."""

    def do_POST(self):
        """Run one command and reply with its result, or with the error it raised."""
        global _last_contact
        _last_contact = time.monotonic()
        name = self.path.strip('/')
        try:
            if name not in COMMANDS:
                raise KeyError(f"unknown command {name!r}, expected one of {', '.join(COMMANDS)}")
            body = self.rfile.read(int(self.headers.get('Content-Length') or 0))
            reply = {'ok': True, 'result': globals()[name](**json.loads(body or b'{}'))}
        except Exception as error:
            reply = {'ok': False, 'error': f'{type(error).__name__}: {error}'}
        data = json.dumps(reply, ensure_ascii=False, default=str).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        """Keep each request out of the console."""


def run_pending(executor):
    """Run the actions queued for the bot's thread.

    Args:
        executor: ok-script's task executor, whose running task each action is handed.
    """
    global _running
    _running = True
    try:
        while not _actions.empty():
            action, future = _actions.get_nowait()
            # False once the caller gave up waiting, so a late click never lands on a screen nobody is looking at.
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(action(executor.current_task))
            except Exception as error:
                future.set_exception(error)
    finally:
        _running = False


def wrap_next_frame(executor_class):
    """Run queued actions on each frame read, and keep a held bot waiting inside it.

    A held bot still captures, so a screenshot shows the screen as it is now. Stopping the task still ends the wait, since ok-script's own read checks
    for that. ok-script's own pause cannot do this job, because a debug run's sleeps and frame reads skip it.

    Args:
        executor_class: The class whose `next_frame` every flow reads through, `TaskExecutor` outside the tests.
    """
    original = executor_class.next_frame

    @functools.wraps(original)
    def next_frame(self, *args, **kwargs):
        if _running:
            return original(self, *args, **kwargs)
        run_pending(self)
        while _held.is_set():
            original(self)
            _wake.wait(HOLD_POLL)
            _wake.clear()
            run_pending(self)
        return original(self, *args, **kwargs)

    executor_class.next_frame = next_frame


def on_bot_thread(action):
    """Queue an action for the bot's next frame read and wait for it to run.

    Args:
        action: Takes the running task. Its return value is passed back.

    Returns:
        What `action` returned.

    Raises:
        TimeoutError: The bot did not read a frame in `ACTION_TIMEOUT` seconds. The action is dropped, not left queued.
    """
    future = concurrent.futures.Future()
    _actions.put((action, future))
    _wake.set()
    try:
        return future.result(ACTION_TIMEOUT)
    except concurrent.futures.TimeoutError:
        future.cancel()
        raise TimeoutError(f'the bot did not read a frame in {ACTION_TIMEOUT}s - no task is running, or it is in a long sleep. '
                           f'Hold the bot and start a task to drive the game with nothing else moving')


def _executor():
    """Return ok-script's task executor.

    Raises:
        RuntimeError: The executor has not been built yet.
    """
    from ok import og

    if og.executor is None:
        raise RuntimeError('the task executor has not started')
    return og.executor


def _task(name):
    """Find a task by its class name, such as `GlobalDailyTask`.

    Args:
        name: The class name a request gave.

    Raises:
        KeyError: No task has that name.
    """
    task = _executor().get_task_by_class_name(name)
    if task is None:
        raise KeyError(f'no task named {name!r}')
    return task


def status():
    """Report which task is running, whether the bot is held, and which tasks are switched on."""
    executor = _executor()
    current = executor.current_task
    return {
        'running': type(current).__name__ if current is not None else None,
        'held': _held.is_set(),
        'pending': _actions.qsize(),
        'enabled': {type(task).__name__: task.enabled for task in executor.get_all_tasks()},
    }


def screenshot():
    """Return the frame the bot last read, as base64 JPEG.

    Raises:
        RuntimeError: Nothing has been captured yet.
    """
    frame = frame_log.latest()
    if frame is None:
        raise RuntimeError('no frame captured yet')
    _, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, QUALITY])
    return {'jpeg': base64.b64encode(jpeg.tobytes()).decode('ascii'), 'width': frame.shape[1], 'height': frame.shape[0]}


def texts():
    """Run an OCR pass over the whole frame as the running task reads it, with centres as fractions of the frame.

    The Global tasks read English as it is on screen, and upstream's CN tasks read it rewritten into the Chinese tokens they match against.
    """
    def read(task):
        centres = [(box.name, box.center()) for box in task.ocr()]
        return [{'text': name, 'x': round(x / task.width, 3), 'y': round(y / task.height, 3)} for name, (x, y) in centres]

    return on_bot_thread(read)


def click(x, y):
    """Click a point on the bot's thread, between two frames.

    Args:
        x: Horizontal position as a fraction of the frame, 0 to 1.
        y: Vertical position as a fraction of the frame, 0 to 1.
    """
    if not (0 <= x <= 1 and 0 <= y <= 1):
        raise ValueError('x and y are fractions of the frame, from 0 to 1')
    label = f'click at ({x:.3f}, {y:.3f})'
    logger.info(f'remote {label}')
    on_bot_thread(lambda task: task.click(x, y, after_sleep=AFTER_INPUT))
    return label


def press_key(key):
    """Press a key on the bot's thread, between two frames.

    Args:
        key: The key name ok-script sends, such as `esc`.
    """
    logger.info(f'remote key {key}')
    on_bot_thread(lambda task: task.send_key(key, after_sleep=AFTER_INPUT))
    return f'key {key}'


def hold(on=True):
    """Stop the flow at its next frame read, or let it carry on. A held bot still captures, so `screenshot` and `texts` stay current.

    Args:
        on: True to hold the bot, False to release it.
    """
    _held.set() if on else _held.clear()
    _wake.set()
    logger.info(f"remote {'hold' if on else 'release'}")
    return status()


def settings(task=DEFAULT_TASK):
    """Return every setting a task carries, by its config key.

    Args:
        task: The task's class name.
    """
    return dict(_task(task).config)


def set_setting(key, value, task=DEFAULT_TASK):
    """Change one setting on a task, saved to its config file as the settings card would.

    Args:
        key: The config key, which for upstream's CN settings is the Chinese one.
        value: The new value, of the type the setting already holds.
        task: The task's class name.

    Raises:
        KeyError: The task has no such setting.
        ValueError: ok-script's validation refused the value.
    """
    config = _task(task).config
    if key not in config:
        raise KeyError(f'{task} has no setting {key!r}')
    config[key] = value
    if config[key] != value:
        raise ValueError(f'{task} refused {value!r} for {key!r}')
    logger.info(f'remote set {task} {key} = {value!r}')
    return config[key]


def set_running(task, running):
    """Start or stop a task, as its Start and Stop buttons would.

    Args:
        task: The task's class name, such as `RunGoHome`.
        running: True to start it, False to stop it.
    """
    from ok import og

    target = _task(task)
    if running:
        # Posted to the controller's own thread, which finds the game window first as the button does.
        og.app.start_controller.start(target)
    else:
        target.disable()
        target.unpause()
    logger.info(f"remote {'start' if running else 'stop'} {task}")
    return status()


def show_connection():
    """Add "MCP connected" to the main window's title while the MCP bridge is pinging."""
    for module in MAIN_WINDOWS:
        try:
            main_window = __import__(module, fromlist=['MainWindow']).MainWindow
            break
        except (ImportError, AttributeError):
            continue
    else:
        logger.warning('could not import MainWindow, the title will not show the MCP connection')
        return
    original_init = main_window.__init__

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        title = self.windowTitle().rstrip()

        def update():
            connected = _last_contact is not None and time.monotonic() - _last_contact < STALE
            self.setWindowTitle(f'{title}  MCP connected' if connected else title)

        # Parented to the window, so it stops when the window goes.
        timer = QTimer(self)
        timer.timeout.connect(update)
        timer.start(TITLE_CHECK)

    main_window.__init__ = patched_init


def apply():
    """Serve the remote control, on a debug run only."""
    global _patched
    if _patched:
        return
    _patched = True
    if not debug_run():
        return
    # Its wrap of the frame read has to sit inside this one, so a held bot's captures still reach the screenshot.
    frame_log.apply()
    wrap_next_frame(TaskExecutor)
    show_connection()
    try:
        server = http.server.ThreadingHTTPServer((HOST, PORT), Remote)
    except OSError as error:
        logger.warning(f'remote control could not listen on {HOST}:{PORT}: {error}')
        return
    threading.Thread(target=server.serve_forever, name='remote', daemon=True).start()
    logger.info(f'debug run, remote control listening on http://{HOST}:{PORT}')
