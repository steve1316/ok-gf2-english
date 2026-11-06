"""Grey out every other task's Start button while one task is running.

The framework lets a second Start through and queues that task behind the one already running, which only shows as a small "Waiting for" note. A click
meant to switch tasks would then wait silently and run later, so the other Starts are locked until the running task stops. Shortcuts, scheduled tasks and
the MCP remote control start tasks without these buttons, so they are not affected.
"""

import functools

from ok import Logger, og

logger = Logger.get_logger(__name__)

# Set on the row class once it has been wrapped, so a second `apply` cannot nest wrappers.
MARKER = '_ok_gf2_start_lock'

# Tooltip on a locked Start. Kept as one key with a placeholder so `ok.po` can translate it whatever task is running.
LOCKED_TEXT = '{task_name} is running. Stop it first.'


def _lock_start(button, task, unlocked_tooltip):
    """Grey out `button` if another task holds the executor, otherwise make sure it is clickable.

    Args:
        button: The row's action button or the detail pane's Run button.
        task: The one-time task that `button` starts.
        unlocked_tooltip: The tooltip to show when `button` is not locked.
    """
    # A task that is itself running, queued or paused shows Stop or Resume, and those must stay clickable.
    blocker = None if task.enabled else next((other for other in task.executor.onetime_tasks if other is not task and other.enabled), None)
    button.setEnabled(blocker is None)
    button.setToolTip(og.app.tr(LOCKED_TEXT).format(task_name=og.app.tr(blocker.name)) if blocker else unlocked_tooltip)


def _locking_row_refresh(original):
    """Wrap `TaskRow.refresh` so a row's button is greyed out while another task holds the executor.

    Args:
        original: The `refresh` being replaced.

    Returns:
        A replacement that draws the row as before, then locks or unlocks its button.
    """

    @functools.wraps(original)
    def refresh(self):
        original(self)
        # Trigger rows have an on/off switch and no button.
        if not self.is_trigger:
            # The framework has just set the button's own tooltip, so that is the one to keep when unlocked.
            _lock_start(self.action_button, self.task, self.action_button.toolTip())

    return refresh


def _locking_detail_refresh(original):
    """Wrap `TaskDetail.refresh` so the Run button is greyed out while another task holds the executor.

    Args:
        original: The `refresh` being replaced.

    Returns:
        A replacement that draws the pane as before, then locks or unlocks Run.
    """

    @functools.wraps(original)
    def refresh(self):
        original(self)
        # The pane starts with no task, and its Run button is hidden for a trigger task.
        if self.task is not None and not self.is_trigger:
            _lock_start(self.run_button, self.task, '')

    return refresh


def _redrawing_every_row(original):
    """Wrap `TasksPage._on_task_event` so every row redraws when any task changes.

    The framework redraws only the changed task's row and leaves the rest to a one-second timer, which would leave the other Starts clickable for that long.

    Args:
        original: The `_on_task_event` being replaced.

    Returns:
        A replacement that drops the task, which is how the framework asks for every row.
    """

    @functools.wraps(original)
    def on_task_event(self, task=None):
        original(self)

    return on_task_event


def apply():
    """Lock the other Start buttons while a task runs. Safe to call more than once."""
    try:
        from ok.ui.qt.tasks.tasks_page import TaskDetail, TaskRow, TasksPage
    except ImportError as error:
        logger.warning(f'could not lock the other Start buttons while a task runs, the task page moved: {error}')
        return
    if MARKER in TaskRow.__dict__:
        return
    TaskRow.refresh = _locking_row_refresh(TaskRow.refresh)
    TaskDetail.refresh = _locking_detail_refresh(TaskDetail.refresh)
    TasksPage._on_task_event = _redrawing_every_row(TasksPage._on_task_event)
    setattr(TaskRow, MARKER, True)
