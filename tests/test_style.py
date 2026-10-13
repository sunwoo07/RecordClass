import re
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication

from sttgui import style


class StyleTest(unittest.TestCase):
    def test_qss_formats_for_both_themes(self) -> None:
        for theme in (style.LIGHT, style.DARK):
            qss = style.QSS.format(icons=style.ICONS, **theme)
            # 치환 누락된 {key}가 남아 있지 않아야 한다
            self.assertIsNone(re.search(r"\{[a-z_]+\}", qss))

    def test_icons_exist(self) -> None:
        for url in set(re.findall(r"url\(\{icons\}/([\w-]+\.svg)\)", style.QSS)):
            self.assertTrue((Path(style.ICONS) / url).is_file(), url)

    def test_apply_style(self) -> None:
        app = QApplication.instance() or QApplication([])
        style.apply_style(app)
        self.assertIn("QPushButton", app.styleSheet())


if __name__ == "__main__":
    unittest.main()
