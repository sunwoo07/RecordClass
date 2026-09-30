import sys

from PySide6.QtWidgets import QApplication

from sttgui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    # QSettings 저장 위치 (~/Library/Preferences/com.recordclass.RecordClass.plist)
    app.setOrganizationName("RecordClass")
    app.setOrganizationDomain("recordclass.com")
    app.setApplicationName("RecordClass")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
