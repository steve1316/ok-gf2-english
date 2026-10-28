"""Check the debug-run tools: one saved frame per log line a second, and the remote control's seat in the bot's frame reads."""

import concurrent.futures
import logging
import os
import tempfile
import threading
import time
import types
import unittest

from unittest import mock

import cv2
import numpy as np

from ok import TaskExecutor

from src.debug import frame_log, remote

# 00:48:52,268 local time on the day of a live run, as the log line would print it.
LOGGED_AT = time.mktime((2026, 10, 25, 0, 48, 52, 0, 0, -1)) + 0.268


def record(level, at, message='GlobalDailyTask:Crew Deck walk stopped short'):
    """Build a log record stamped at a fixed time.

    Args:
        level: The record's logging level.
        at: The epoch time the record says it was logged at.
        message: The logged text.

    Returns:
        A `logging.LogRecord`.
    """
    line = logging.LogRecord('ok', level, __file__, 0, message, None, None)
    line.created, line.msecs = at, round((at % 1) * 1000)
    return line


class FakeExecutor:
    """Stands in for ok-script's executor, counting the frames read through the wrapped `next_frame`."""

    def __init__(self):
        """Start with a running task and no frames read."""
        # What a queued action is handed.
        self.current_task = object()
        # How many frames the unwrapped `next_frame` captured.
        self.reads = 0

    def next_frame(self, time_out=6):
        """Capture one frame.

        Args:
            time_out: Ignored, as ok-script's own argument.

        Returns:
            A small blank frame.
        """
        self.reads += 1
        return np.zeros((9, 16, 3), np.uint8)


class TestFrameLog(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.executor = types.SimpleNamespace(current_task=object())
        # A fresh frame per read, the way ok-script hands over each capture.
        self.enterContext(mock.patch.object(frame_log, 'latest', lambda: np.full((8, 8, 3), 200, np.uint8)))
        self.handler = frame_log.FrameLog(lambda: self.executor, os.path.join(self.folder.name, 'session'))
        self.log = logging.Logger('tests.frame_log', logging.DEBUG)
        self.log.addHandler(self.handler)

    def test_a_line_saves_the_frame_it_was_logged_on(self):
        self.log.handle(record(logging.INFO, LOGGED_AT))
        path, frame = self.handler.pending.get_nowait()
        self.assertEqual('00-48-52-268_GlobalDailyTask-Crew-Deck-walk-stopped-s.jpg', os.path.basename(path))
        self.handler.save(path, frame)
        self.assertEqual((8, 8, 3), cv2.imread(path).shape)

    def test_only_one_info_line_a_second_saves_while_a_task_runs(self):
        # Every one of these is a frame saved for nothing, and a poll can log on every frame.
        self.log.handle(record(logging.INFO, LOGGED_AT))
        self.log.handle(record(logging.INFO, LOGGED_AT + 0.2))
        self.log.handle(record(logging.DEBUG, LOGGED_AT + 2))
        self.executor.current_task = None
        self.log.handle(record(logging.INFO, LOGGED_AT + 4))
        self.assertEqual(1, self.handler.pending.qsize())

    def test_a_full_session_drops_its_oldest_frames(self):
        paths = [os.path.join(self.folder.name, 'session', f'{index}.jpg') for index in range(3)]
        frame = np.full((8, 8, 3), 200, np.uint8)
        self.handler.save(paths[0], frame)
        with mock.patch.object(frame_log, 'SESSION_CAP', os.path.getsize(paths[0]) * 2):
            for path in paths[1:]:
                self.handler.save(path, frame)
        self.assertEqual([False, True, True], [os.path.exists(path) for path in paths])

    def test_only_the_newest_sessions_are_kept(self):
        for name in ('2026-10-22_10-00-00', '2026-10-23_10-00-00', '2026-10-24_10-00-00', '2026-10-25_10-00-00'):
            os.makedirs(os.path.join(self.folder.name, name))
        frame_log.prune(self.folder.name, frame_log.SESSIONS_KEPT - 1)
        self.assertEqual(['2026-10-24_10-00-00', '2026-10-25_10-00-00'], sorted(os.listdir(self.folder.name)))


class TestRemote(unittest.TestCase):

    def setUp(self):
        # The wrap patches the class it is given, so each test wraps a fresh one.
        self.executor = type('Executor', (FakeExecutor,), {})()
        remote.wrap_next_frame(type(self.executor))

    def tearDown(self):
        remote._held.clear()
        while not remote._actions.empty():
            remote._actions.get_nowait()

    def queue_action(self, action):
        """Queue an action the way `on_bot_thread` does, without blocking on it.

        Args:
            action: Takes the running task.

        Returns:
            The action's future.
        """
        future = concurrent.futures.Future()
        remote._actions.put((action, future))
        remote._wake.set()
        return future

    def test_an_action_runs_on_the_next_frame_read(self):
        """A click lands between two frames on the bot's own thread, so it never races the flow."""
        future = self.queue_action(lambda task: task)
        self.executor.next_frame()
        self.assertIs(self.executor.current_task, future.result(0))

    def test_an_abandoned_click_never_lands(self):
        """A click whose caller gave up would otherwise land on whatever screen the bot reaches next."""
        clicks = []
        with mock.patch.object(remote, 'ACTION_TIMEOUT', 0.01), self.assertRaises(TimeoutError):
            remote.on_bot_thread(clicks.append)
        self.executor.next_frame()
        self.assertEqual([], clicks)

    def test_a_held_bot_waits_in_its_frame_read_until_released(self):
        """Otherwise the flow carries on over the screen being stepped through by hand."""
        remote._held.set()
        returned = []
        thread = threading.Thread(target=lambda: returned.append(self.executor.next_frame()), daemon=True)
        with mock.patch.object(remote, 'HOLD_POLL', 0.05):
            thread.start()
            time.sleep(0.3)
            self.assertEqual([], returned)
            # Still reading while held, so a screenshot shows the screen as it is now.
            self.assertGreater(self.executor.reads, 1)
            self.assertEqual('clicked', self.queue_action(lambda task: 'clicked').result(1))
            remote._held.clear()
            remote._wake.set()
            thread.join(1)
        self.assertEqual(1, len(returned))

    def test_an_action_that_reads_a_frame_does_not_run_the_next_one_inside_it(self):
        """An OCR pass reads a frame of its own, and a click run inside it would land before the OCR is done."""
        order = []
        self.queue_action(lambda task: (order.append('ocr start'), self.executor.next_frame(), order.append('ocr end')))
        self.queue_action(lambda task: order.append('click'))
        self.executor.next_frame()
        self.assertEqual(['ocr start', 'ocr end', 'click'], order)

    def test_a_screenshot_outlives_the_frame_ok_script_drops(self):
        """ok-script drops its frame on every sleep, so a held bot would otherwise have nothing to show."""
        self.assertIn('next_frame', vars(TaskExecutor))
        captured = np.zeros((9, 16, 3), np.uint8)
        with mock.patch.object(TaskExecutor, 'next_frame', lambda executor: captured), mock.patch.object(frame_log, '_latest', None):
            frame_log.keep_frames()
            TaskExecutor.next_frame(None)
            self.assertEqual(16, remote.screenshot()['width'])


if __name__ == '__main__':
    unittest.main()
