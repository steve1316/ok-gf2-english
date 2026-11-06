"""Give links a colour that is readable on the theme they are shown on.

The framework's palette sets no link colour, so links keep the one Windows supplies. On this machine that is a dark shade of the accent, which read at 1.4:1 on
the dark theme's dialogs. It has to go on the application's palette, because a stylesheet-polished label takes its link colour from there and not from the
palette the theme sets on its window.
"""

import functools

from ok import Logger
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

logger = Logger.get_logger(__name__)

# Set on the theme class once it has been wrapped, so a second `apply` cannot nest wrappers.
MARKER = '_ok_gf2_link_colour'

# How far a link moves from the accent towards white on the dark theme. The default red goes from 3.7:1 on a dark dialog to 6.5:1, and it still reads as red.
DARK_THEME_LIFT = 0.45


def _link_colour(manager):
    """Work out the link colour for the current theme and accent.

    Args:
        manager: The `ThemeManager` to read them from.

    Returns:
        A `QColor`. On the light theme that is the accent itself, which the framework has already darkened until it holds up against white.
    """
    accent = manager.accent()
    if not manager.is_dark():
        return accent
    return QColor(*(round(channel + (255 - channel) * DARK_THEME_LIFT) for channel in (accent.red(), accent.green(), accent.blue())))


def _setting_link_colour(original):
    """Wrap `ThemeManager._apply`, which runs whenever a window is themed and again on every theme or accent change.

    Args:
        original: The `_apply` being replaced.

    Returns:
        A replacement that themes the window as before, then brings the application's link colour up to date.
    """

    @functools.wraps(original)
    def apply_theme(self, root):
        original(self, root)
        link = _link_colour(self)
        palette = QApplication.palette()
        # Every themed window comes through here, and setting the palette redraws the whole app.
        if palette.color(QPalette.ColorRole.Link) != link:
            palette.setColor(QPalette.ColorRole.Link, link)
            palette.setColor(QPalette.ColorRole.LinkVisited, link)
            QApplication.setPalette(palette)

    return apply_theme


def apply():
    """Keep the application's link colour readable. Safe to call more than once."""
    try:
        from ok.ui.qt.kit.theme import ThemeManager
    except ImportError as error:
        logger.warning(f'could not set the link colour, the theme moved: {error}')
        return
    if MARKER in ThemeManager.__dict__:
        return
    ThemeManager._apply = _setting_link_colour(ThemeManager._apply)
    setattr(ThemeManager, MARKER, True)
