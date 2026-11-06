"""Open the Tasks page on one group's tab, and list that tab ahead of the other groups.

The framework orders group tabs by whichever task registered first, and reopens whichever tab was left open last. The tab Global Daily and Global Weekly live
on should win both. Registration order cannot change to suit it, because shortcuts and scheduled tasks store a position in that list.
"""

import functools

from ok import Logger

logger = Logger.get_logger(__name__)

# Set on the page class once it has been wrapped, so a second `apply` cannot nest wrappers.
MARKER = '_ok_gf2_task_tabs'


def _listing_first(original, group):
    """Wrap `task_groups` so `group` comes first.

    Args:
        original: The `task_groups` being replaced.
        group: The group's name.

    Returns:
        A replacement that returns the same groups, with `group` moved to the front.
    """

    @functools.wraps(original)
    def task_groups(tasks):
        groups = original(tasks)
        return {group: groups[group], **groups} if group in groups else groups

    return task_groups


def _opening_on(original, key):
    """Wrap `TasksPage.__init__` so a new page starts on the tab `key`.

    Args:
        original: The `__init__` being replaced.
        key: The tab's key.

    Returns:
        A replacement that switches tab once the page is built. Later rebuilds of the tabs keep whichever one is open by then.
    """

    @functools.wraps(original)
    def init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        self.set_filter(key)

    return init


def apply(group):
    """Make `group` the tab the Tasks page lists first and opens on. Safe to call more than once.

    Args:
        group: The group's name, as the tasks set it in `group_name`.
    """
    try:
        from ok.ui.qt.tasks import tasks_page
    except ImportError as error:
        logger.warning(f'could not open the Tasks page on {group}, the task page moved: {error}')
        return
    page = tasks_page.TasksPage
    if MARKER in page.__dict__:
        return
    tasks_page.task_groups = _listing_first(tasks_page.task_groups, group)
    page.__init__ = _opening_on(page.__init__, tasks_page.GROUP_PREFIX + group)
    setattr(page, MARKER, True)
