"""Grey out every other task's Start button while one task is running.

The framework lets a second Start through and queues that task behind the one already running, which only shows as a small "Waiting for" note. A click
meant to switch tasks would then wait silently and run later, so the other Starts are locked until the running task stops. Shortcuts, scheduled tasks and
the MCP remote control start tasks without these buttons, so they are not affected.
"""

from ok import Logger, og

logger = Logger.get_logger(__name__)

# Set on the card class once it has been wrapped, so a second `apply` cannot nest wrappers.
MARKER = '_ok_gf2_start_lock'

# Tooltip on a locked Start. Kept as one key with a placeholder so `ok.po` can translate it whatever task is running.
LOCKED_TEXT = '{task_name} is running. Stop it first.'


def _locking_update_buttons(original):
    """Wrap `TaskCard.update_buttons` so a card's Start is greyed out while another task holds the executor.

    The framework calls `update_buttons` on every one-time card whenever any task starts, stops, pauses or fails, so the lock follows the running task with
    no signal of its own.

    Args:
        original: The `update_buttons` being replaced.

    Returns:
        A replacement that draws the buttons as before, then locks or unlocks Start.
    """

    def update_buttons(self, task):
        original(self, task)
        # A card whose own task is running, queued or paused shows Stop or Resume, and Resume must stay clickable.
        if not self.onetime or self.task.enabled:
            return
        # Any other task that is running, queued or paused holds the executor.
        blocker = next((other for other in self.task.executor.onetime_tasks if other is not self.task and other.enabled), None)
        self.start_button.setEnabled(blocker is None)
        self.start_button.setToolTip(og.app.tr(LOCKED_TEXT).format(task_name=og.app.tr(blocker.name)) if blocker else '')

    return update_buttons


def apply():
    """Lock the other Start buttons while a task runs. Safe to call more than once."""
    try:
        from ok.gui.tasks.TaskCard import TaskCard
    except ImportError as error:
        logger.warning(f'could not lock the other Start buttons while a task runs, the task card moved: {error}')
        return
    if MARKER in TaskCard.__dict__:
        return
    TaskCard.update_buttons = _locking_update_buttons(TaskCard.update_buttons)
    setattr(TaskCard, MARKER, True)
