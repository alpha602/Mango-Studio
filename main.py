import sys
import logging

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtNetwork import QLocalServer

from gui.main_window import MainWindow
from core.config import AppConfig
from core.i18n import set_language

SINGLE_INSTANCE_KEY = "mango_studio_single_instance"


def _excepthook(exc_type, exc_value, exc_tb):
    """Loggt unbehandelte Ausnahmen, statt sie still zu schlucken."""
    logging.critical("Unbehandelter Fehler:", exc_info=(exc_type, exc_value, exc_tb))


def _acquire_single_instance_lock(app: QApplication):
    server = QLocalServer(app)
    if not server.listen(SINGLE_INSTANCE_KEY):
        return None
    return server


def main():
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.warning("Mango Studio wird gestartet...")

    force_rescan = "--rescan" in sys.argv

    app = QApplication(sys.argv)

    lock = _acquire_single_instance_lock(app)
    if lock is None:
        QMessageBox.information(
            None, "Mango Studio",
            "Mango Studio läuft bereits.\n"
            "Es kann nur eine Instanz gleichzeitig gestartet werden.",
        )
        sys.exit(0)

    sys.excepthook = _excepthook

    app.setApplicationName("Mango Studio")
    app.setOrganizationName("Mango Studio")
    app.setApplicationVersion("1.0.0")

    config = AppConfig()
    set_language(config.language)

    window = MainWindow(config, force_rescan=force_rescan)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logging.critical(f"Kritischer Fehler beim Start der App: {e}", exc_info=True)
        sys.exit(1)