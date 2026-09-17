import sys
import multiprocessing

from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow


def main():
    multiprocessing.freeze_support()

    app = QApplication(sys.argv)
    app.setApplicationName("Slot Math Designer")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()