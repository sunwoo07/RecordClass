"""테스트 공용 설정. 실행: python -m unittest (저장소 루트에서)

- Qt는 화면 없이(offscreen) 띄운다.
- QSettings는 임시 폴더의 INI 파일로 돌려 실제 사용자 설정을 건드리지 않는다.
"""
import atexit
import os
import shutil
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_settings_dir = tempfile.mkdtemp(prefix="recordclass-test-")
atexit.register(shutil.rmtree, _settings_dir, ignore_errors=True)
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, _settings_dir)


def qt_app() -> QApplication:
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("RecordClassTest")
    app.setApplicationName("RecordClassTest")
    return app


def clear_settings() -> None:
    qt_app()
    QSettings().clear()
