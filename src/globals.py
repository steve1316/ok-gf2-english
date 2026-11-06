from ok import Logger
from PySide6.QtCore import QObject

logger = Logger.get_logger(__name__)


def translate_notifications():
    """Let toast messages use the app translation catalog.

    `MainWindow.show_notification` only runs the message through Qt's "app" context, which holds the framework's own strings. Everything this project
    translates lives in the gettext catalog instead, so task messages reach the toast untranslated. Passing it through `og.app.tr` first fixes that, and a
    string with no catalog entry comes back unchanged. The framework already does this for the title.
    """
    try:
        from ok.ui.qt.MainWindow import MainWindow
    except ImportError:
        logger.warning('could not import MainWindow, skipping notification translation')
        return

    original_show = MainWindow.show_notification

    def patched_show(self, message, *args, **kwargs):
        # ok-script has grown arguments here before, so forward the rest instead of respelling them.
        from ok import og
        try:
            if message:
                message = og.app.tr(message)
        except Exception as e:
            logger.warning(f'could not translate notification: {e}')
        original_show(self, message, *args, **kwargs)

    MainWindow.show_notification = patched_show
    logger.info('notifications routed through the translation catalog')


class Globals(QObject):
    def __init__(self, exit_event):
        super().__init__()
        from src.debug import frame_log, remote

        # Neither does anything outside a debug run.
        frame_log.apply()
        remote.apply()
        translate_notifications()
        # ok.og.executor.ocr_lib.add_text_fix({"a": "b"})


if __name__ == "__main__":
    glbs = Globals(exit_event=None)
