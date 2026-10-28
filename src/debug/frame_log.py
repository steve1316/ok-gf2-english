"""Save the frame the bot was looking at next to each line a debug run logs.

A report of a misread screen or a stuck flow comes with the log and nothing else, so `main_debug.py` keeps the frame behind each INFO or louder line,
at most one a second, named by that line's own timestamp. Release runs never start it.
"""

import collections
import functools
import logging
import os
import queue
import re
import shutil
import threading
import time

import cv2

from ok import Logger, TaskExecutor

from src.debug import debug_run

logger = Logger.get_logger(__name__)

# Where each session's frames go. Not ok-script's `screenshots/`, which is wiped on every launch, and not `debug_frames/`, which `dump_screen` keeps for
# frames that were not what a flow expected.
FOLDER = os.path.join('logs', 'frames')
# Session folders kept, counting the new one.
SESSIONS_KEPT = 3
# Bytes one session keeps before its oldest frames go, so the three sessions top out at ~3 GB.
SESSION_CAP = 1024 ** 3
# Seconds between saved frames, so a poll that logs every frame does not save every frame.
INTERVAL = 1.0
# JPEG quality. A 1080p frame comes to ~0.3 MB here against ~2.5 MB as PNG.
QUALITY = 90
# Frames waiting on the disk before new ones are dropped, so a slow disk cannot pile up 6 MB copies in memory.
QUEUE_SIZE = 30
# Characters of the message kept in a file name, enough to browse the folder by.
SLUG_LENGTH = 40
# Runs of characters a file name cannot carry cleanly.
UNSAFE = re.compile(r'[^A-Za-z0-9]+')

# The frame ok-script last captured. It drops its own copy on every sleep, so `nullable_frame` is usually None.
_latest = None
_patched = False


class FrameLog(logging.Handler):
    """Queue the frame on screen for each line logged while a task runs, at most once per `INTERVAL`."""

    def __init__(self, executor, folder):
        """Set up a handler for one session.

        Args:
            executor: A callable returning ok-script's task executor, or None before there is one.
            folder: This session's folder, made on the first save.
        """
        super().__init__(logging.INFO)
        # Read on each line for the running task.
        self.executor = executor
        self.folder = folder
        # When the last frame was queued and the frame itself, so an unchanged frame is not saved twice.
        self.last_at = 0.0
        self.last_frame = None
        # Frames waiting for the writer thread, as `(path, frame)` pairs.
        self.pending = queue.Queue(QUEUE_SIZE)
        # Frames this session saved, oldest first, as `(path, bytes)` pairs, and their total.
        self.saved = collections.deque()
        self.saved_bytes = 0
        self.complained = False

    def emit(self, record):
        """Queue a copy of the frame behind one log line, unless one was queued too recently or nothing new is on screen.

        A failure, a full queue included, never reaches the line's caller.

        Args:
            record: The log record, whose time names the file.
        """
        if record.created - self.last_at < INTERVAL:
            return
        try:
            executor = self.executor()
            if executor is None or executor.current_task is None:
                return
            frame = latest()
            if frame is None or frame is self.last_frame:
                return
            self.last_at, self.last_frame = record.created, frame
            # The log line's own `HH:MM:SS,mmm`, so grepping the time finds both.
            stamp = time.strftime('%H-%M-%S', time.localtime(record.created)) + f'-{int(record.msecs):03d}'
            slug = UNSAFE.sub('-', record.getMessage())[:SLUG_LENGTH].strip('-')
            self.pending.put_nowait((os.path.join(self.folder, f'{stamp}_{slug}.jpg'), frame.copy()))
        except Exception as error:
            self.complain(error)

    def save(self, path, frame):
        """Write one queued frame to disk.

        Args:
            path: The file to write, inside this session's folder.
            frame: The frame, in BGR.
        """
        try:
            os.makedirs(self.folder, exist_ok=True)
            if not cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, QUALITY]):
                self.complain(f'OpenCV would not write {path}')
                return
            size = os.path.getsize(path)
            self.saved.append((path, size))
            self.saved_bytes += size
            while self.saved_bytes > SESSION_CAP:
                oldest, size = self.saved.popleft()
                self.saved_bytes -= size
                os.remove(oldest)
        except Exception as error:
            self.complain(error)

    def write(self):
        """Clear out old sessions, then save frames as they arrive. Runs forever on the writer thread."""
        prune(os.path.dirname(self.folder), SESSIONS_KEPT - 1)
        while True:
            self.save(*self.pending.get())

    def complain(self, error):
        """Log the first failure and stay quiet about the rest, since losing a frame must never cost a run.

        Args:
            error: What went wrong.
        """
        if not self.complained:
            self.complained = True
            logger.warning(f'could not save a debug frame, later failures stay quiet: {error}')


def latest():
    """Return the frame ok-script last captured, or None before the first one."""
    return _latest


def keep_frames():
    """Keep each frame ok-script captures, so `latest` still has it after a sleep drops the executor's copy."""
    original = TaskExecutor.next_frame

    @functools.wraps(original)
    def next_frame(self, *args, **kwargs):
        global _latest
        frame = original(self, *args, **kwargs)
        if frame is not None:
            _latest = frame
        return frame

    TaskExecutor.next_frame = next_frame


def prune(root, keep):
    """Delete all but the newest session folders. Their names are start times, so they sort oldest first.

    Args:
        root: The folder holding one subfolder per session.
        keep: How many of the newest sessions to leave.
    """
    if not os.path.isdir(root):
        return
    sessions = sorted(name for name in os.listdir(root) if os.path.isdir(os.path.join(root, name)))
    for name in sessions[:max(len(sessions) - keep, 0)]:
        shutil.rmtree(os.path.join(root, name), ignore_errors=True)


def apply():
    """Start saving a frame next to the log, on a debug run only."""
    global _patched
    if _patched:
        return
    _patched = True
    if not debug_run():
        return
    from ok import og

    keep_frames()
    session = os.path.join(FOLDER, time.strftime('%Y-%m-%d_%H-%M-%S'))
    handler = FrameLog(lambda: og.executor, session)
    threading.Thread(target=handler.write, name='frame_log', daemon=True).start()
    logging.getLogger('ok').addHandler(handler)
    logger.info(f'debug run, saving a frame per log line to {session}')
