"""The icons on the Global task rows and tabs, drawn in two colours that follow the theme.

The framework can only tint an icon one colour, which would flatten the bright key mark into the rest of the shape. A `QIcon` passes through its icon lookup
untouched though, so these draw themselves. See `icons/tasks/README.md` for the art.
"""

from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QIconEngine, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from ok.ui.qt.kit.theme import theme

# Absolute, because the app can be started from a shortcut or a scheduled task whose working directory is not the install folder.
ICON_DIR = Path(__file__).resolve().parent.parent / 'icons' / 'tasks'

# The two colours every file in `ICON_DIR` is drawn in. They only mark what to swap, so an SVG still previews correctly on a dark background on its own.
INK_PLACEHOLDER = '#FFFFFF'
KEY_PLACEHOLDER = '#F06C18'

# Key mark colours, by whether the theme is dark. Orange is the game's own UI colour and marks what the app is opened for. The darker light-theme shade holds
# 4.4:1 on white, where the bright one only manages 3.1:1.
ORANGE = {True: '#F06C18', False: '#C9540C'}

# Teal marks the tasks run while fixing something. It sits apart from orange and from the red accent, so a Flow Check never reads as the main run.
TEAL = {True: '#4FC3CF', False: '#0E7C86'}


class TwoToneEngine(QIconEngine):
    """Draws an icon's SVG in the current theme's colours, looked up on every draw so a live theme switch reaches it."""

    def __init__(self, markup, key):
        """Keep what is needed to draw the icon later.

        Args:
            markup: The SVG text, drawn in `INK_PLACEHOLDER` and `KEY_PLACEHOLDER`.
            key: The key mark's colours, by whether the theme is dark. `ORANGE` or `TEAL`.
        """
        super().__init__()
        self.markup = markup
        self.key = key

    def paint(self, painter, rect, mode, state):
        """Draw the icon.

        Args:
            painter: The `QPainter` to draw with.
            rect: The `QRect` to fill.
            mode: The `QIcon.Mode`. Ignored, as no caller draws these disabled.
            state: The `QIcon.State`. Ignored for the same reason.
        """
        themed = self.markup.replace(INK_PLACEHOLDER, theme.color('text').name()).replace(KEY_PLACEHOLDER, self.key[theme.is_dark()])
        QSvgRenderer(QByteArray(themed.encode('ascii'))).render(painter, QRectF(rect))

    def scaledPixmap(self, size, mode, state, scale):
        """Draw the icon into a pixmap, which is how the task rows use it.

        Args:
            size: The `QSize` wanted, in device-independent pixels.
            mode: The `QIcon.Mode`, passed to `paint`.
            state: The `QIcon.State`, passed to `paint`.
            scale: The screen's device pixel ratio.

        Returns:
            A transparent `QPixmap` holding the icon.
        """
        image = QImage(size * scale, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        self.paint(painter, image.rect(), mode, state)
        painter.end()
        pixmap = QPixmap.fromImage(image)
        pixmap.setDevicePixelRatio(scale)
        return pixmap

    def pixmap(self, size, mode, state):
        """Draw the icon into a pixmap at normal scale.

        Args:
            size: The `QSize` wanted.
            mode: The `QIcon.Mode`, passed to `paint`.
            state: The `QIcon.State`, passed to `paint`.

        Returns:
            A transparent `QPixmap` holding the icon.
        """
        return self.scaledPixmap(size, mode, state, 1.0)

    def clone(self):
        """Copy the engine, which Qt asks for when a `QIcon` is detached.

        Returns:
            A new engine drawing the same icon.
        """
        return TwoToneEngine(self.markup, self.key)


def two_tone(name, key):
    """Load one icon from `ICON_DIR`.

    Args:
        name: The file's name, without `.svg`.
        key: The key mark's colours, `ORANGE` or `TEAL`.

    Returns:
        A `QIcon` that follows the theme.
    """
    return QIcon(TwoToneEngine((ICON_DIR / f'{name}.svg').read_text(encoding='ascii'), key))
