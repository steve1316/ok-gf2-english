"""Draw the Tasks page's Info table without column titles, with rows tall enough for their text.

The flow rows carry a sentence or three each, and the framework fixes every row at one height, which cuts a Crew Deck result off after two lines. The
`Info` / `Value` titles say nothing the rows do not.
"""

import functools

from ok import Logger

logger = Logger.get_logger(__name__)

# Set on the detail class once it has been wrapped, so a second `apply` cannot nest wrappers.
MARKER = '_ok_gf2_info_table'

# The framework's own row height. A one-line row keeps it, so only rows with more to say grow.
MIN_ROW_HEIGHT = 40


def _fitting(original):
    """Wrap `TaskDetail._fill_info` to hide the column titles and grow each row to fit its wrapped text, never below the framework's height.

    The framework fills the table whenever it is shown, so the titles are gone before it is ever seen.

    Args:
        original: The `_fill_info` being replaced.

    Returns:
        The replacement.
    """

    @functools.wraps(original)
    def fill_info(self, *args, **kwargs):
        original(self, *args, **kwargs)
        table = self.info_table
        table.horizontalHeader().hide()
        for row in range(table.rowCount()):
            table.setRowHeight(row, max(MIN_ROW_HEIGHT, table.sizeHintForRow(row)))

    return fill_info


def patch(task_detail):
    """Wrap one detail class. Safe to call more than once.

    Args:
        task_detail: The framework's `TaskDetail` class, or a stand-in shaped like it.
    """
    if MARKER in task_detail.__dict__:
        return
    task_detail._fill_info = _fitting(task_detail._fill_info)
    setattr(task_detail, MARKER, True)


def apply():
    """Patch the framework's Tasks page detail pane. Logs and leaves the table as it is if the framework moved it."""
    try:
        from ok.ui.qt.tasks.tasks_page import TaskDetail
    except ImportError as error:
        logger.warning(f'could not tidy the Info table, the task page moved: {error}')
        return
    patch(TaskDetail)
