"""앱 전역 스타일. DESIGN-apple.md 토큰(Action Blue 단일 강조색, Parchment 배경, hairline, pill 버튼)을 QSS로 옮긴다.

위젯은 `setProperty("role", ...)`로 역할을 지정하고, 여기서 역할별 모양을 정한다.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

ICONS = (Path(__file__).parent / "icons").as_posix()

LIGHT = {
    "sidebar": "#ececef",  # 왼쪽 대기열
    "canvas": "#f5f5f7",  # 본문 배경 (parchment)
    "surface": "#ffffff",  # 카드·입력칸
    "ink": "#1d1d1f",
    "muted": "#7a7a7a",
    "hairline": "#e0e0e0",
    "primary": "#0066cc",
    "primary_hover": "#0071e3",
    "button": "#ffffff",
    "button_hover": "#fafafc",
    "selection": "#dcdce1",  # 사이드바 선택 행
    "text_selection": "#d6e6f8",
    "track": "#e3e3e8",
    "indicator": "#c7c7cc",
    "danger": "#d70015",
    "switch_off": "switch-off-light.svg",
}
DARK = {
    "sidebar": "#252527",
    "canvas": "#1d1d1f",
    "surface": "#2c2c2e",
    "ink": "#f5f5f7",
    "muted": "#a1a1a6",
    "hairline": "#3a3a3c",
    "primary": "#0071e3",
    "primary_hover": "#2997ff",
    "button": "#3a3a3c",
    "button_hover": "#444446",
    "selection": "#3a3a3c",
    "text_selection": "#1f3a5c",
    "track": "#3a3a3c",
    "indicator": "#5a5a5e",
    "danger": "#ff453a",
    "switch_off": "switch-off-dark.svg",
}

# 대기열 상태 점 색 (라이트·다크 공통 시스템 색)
STATUS_COLORS = {
    "pending": "#8e8e93",
    "running": "#0a84ff",
    "summarizing": "#bf5af2",
    "done": "#30d158",
    "failed": "#ff453a",
}

_current: dict[str, str] = LIGHT

QSS = """
QWidget {{ color: {ink}; font-size: 13px; }}
QMainWindow, QDialog {{ background: {canvas}; }}
QFrame[role="sidebar"] {{ background: {sidebar}; border-right: 1px solid {hairline}; }}
QWidget[role="content"], QWidget[role="page"] {{ background: {canvas}; }}
QScrollArea {{ background: transparent; border: none; }}
QFrame[role="card"] {{ background: {surface}; border: 1px solid {hairline}; border-radius: 12px; }}
QFrame[role="separator"] {{ background: {hairline}; border: none; }}

QLabel {{ background: transparent; }}
QLabel[role="title"] {{ font-size: 15px; font-weight: 600; }}
QLabel[role="hero"] {{ font-size: 24px; font-weight: 600; }}
QLabel[role="headline"] {{ font-size: 20px; font-weight: 600; }}
QLabel[role="section"] {{ color: {muted}; font-size: 12px; font-weight: 600; padding: 14px 4px 2px 4px; }}
QLabel[role="muted"] {{ color: {muted}; font-size: 12px; }}
QLabel[role="summary"] {{ color: {muted}; font-size: 12px; padding: 2px 4px; }}
QLabel[role="summary"]:hover {{ color: {primary_hover}; }}

QPushButton {{
    background: {button}; color: {ink}; border: 1px solid {hairline};
    border-radius: 8px; padding: 5px 14px; min-height: 18px;
}}
QPushButton:hover {{ background: {button_hover}; }}
QPushButton:pressed {{ background: {hairline}; }}
QPushButton:disabled {{ color: {muted}; }}
QPushButton[role="primary"] {{
    background: {primary}; color: #ffffff; border: none;
    border-radius: 18px; padding: 9px 22px; font-size: 14px; font-weight: 600;
}}
QPushButton[role="primary"]:hover {{ background: {primary_hover}; }}
QPushButton[role="primary"]:disabled {{ background: {track}; color: {muted}; }}
QPushButton[role="cancel"] {{
    background: transparent; color: {danger}; border: 1px solid {danger};
    border-radius: 18px; padding: 8px 22px; font-size: 14px; font-weight: 600;
}}
QPushButton[role="plain"] {{ background: transparent; border: none; color: {primary}; padding: 4px 6px; }}
QPushButton[role="plain"]:hover {{ color: {primary_hover}; }}
QPushButton[role="plain"]:disabled {{ color: {muted}; }}
QPushButton[role="icon"] {{
    background: transparent; border: none; border-radius: 6px; padding: 4px;
    min-width: 22px; min-height: 22px;
}}
QPushButton[role="icon"]:hover {{ background: {selection}; }}

QFrame[role="segmented"] {{ background: {track}; border-radius: 8px; }}
QPushButton[role="segment"] {{
    background: transparent; border: none; border-radius: 6px;
    padding: 4px 22px; font-weight: 600; color: {muted};
}}
QPushButton[role="segment"]:checked {{ background: {surface}; color: {ink}; }}
QPushButton[role="chip"] {{
    background: {surface}; border: 1px solid {hairline}; border-radius: 13px;
    padding: 4px 14px; color: {ink};
}}
QPushButton[role="chip"]:checked {{ background: {primary}; border-color: {primary}; color: #ffffff; }}

QListWidget[role="queue"] {{ background: transparent; border: 2px solid transparent; border-radius: 10px; outline: none; }}
QListWidget[role="queue"][dropping="true"] {{ border: 2px dashed {primary_hover}; }}

QTextBrowser[role="reader"] {{
    background: {surface}; border: 1px solid {hairline}; border-radius: 12px; padding: 14px 18px;
    font-size: 14px; selection-background-color: {text_selection}; selection-color: {ink};
}}
QPlainTextEdit[role="log"] {{
    background: {surface}; border: 1px solid {hairline}; border-radius: 8px; padding: 6px;
    font-family: Menlo; font-size: 11px; color: {muted};
}}
QPlainTextEdit, QLineEdit, QComboBox, QDoubleSpinBox {{
    background: {surface}; border: 1px solid {hairline}; border-radius: 7px;
    selection-background-color: {text_selection}; selection-color: {ink};
}}
QPlainTextEdit {{ padding: 6px; }}
QLineEdit, QComboBox, QDoubleSpinBox {{ padding: 3px 8px; min-height: 18px; }}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {primary_hover};
}}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url({icons}/chevron-down.svg); width: 10px; height: 10px; }}
QComboBox QAbstractItemView {{
    background: {surface}; border: 1px solid {hairline}; selection-background-color: {text_selection};
}}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ border: none; width: 18px; }}
QDoubleSpinBox::up-arrow {{ image: url({icons}/chevron-up.svg); width: 9px; height: 9px; }}
QDoubleSpinBox::down-arrow {{ image: url({icons}/chevron-down.svg); width: 9px; height: 9px; }}

QCheckBox {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator {{
    width: 14px; height: 14px; border: 1px solid {indicator}; border-radius: 4px; background: {surface};
}}
QCheckBox::indicator:checked {{
    background: {primary}; border: 1px solid {primary}; image: url({icons}/check.svg);
}}
QCheckBox[role="switch"]::indicator {{
    width: 34px; height: 20px; border: none; border-radius: 0; background: transparent;
    image: url({icons}/{switch_off});
}}
QCheckBox[role="switch"]::indicator:checked {{ image: url({icons}/switch-on.svg); }}

QProgressBar {{
    background: {track}; border: none; border-radius: 2px;
    max-height: 4px; min-height: 4px; text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background: {primary}; border-radius: 2px; }}

QToolTip {{
    background: {surface}; color: {ink}; border: 1px solid {hairline};
    border-radius: 6px; padding: 6px;
}}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {indicator}; border-radius: 3px; min-height: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
"""


def theme() -> dict[str, str]:
    """지금 적용 중인 색 토큰. 직접 그리는 위젯(대기열 행 등)이 쓴다."""
    return _current


def _palette(t: dict[str, str]) -> QPalette:
    """Fusion이 직접 그리는 부분(포커스 테두리, 메뉴 등)이 토큰 색을 따르도록 팔레트를 맞춘다."""
    p = QPalette()
    for role, key in (
        (QPalette.Window, "canvas"),
        (QPalette.Base, "surface"),
        (QPalette.AlternateBase, "canvas"),
        (QPalette.Button, "button"),
        (QPalette.WindowText, "ink"),
        (QPalette.Text, "ink"),
        (QPalette.ButtonText, "ink"),
        (QPalette.ToolTipBase, "surface"),
        (QPalette.ToolTipText, "ink"),
        (QPalette.Highlight, "primary"),
        (QPalette.Link, "primary"),
        (QPalette.PlaceholderText, "muted"),
        (QPalette.Mid, "hairline"),
    ):
        p.setColor(role, QColor(t[key]))
    p.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, QColor(t["muted"]))
    return p


def stylesheet(t: dict[str, str]) -> str:
    return QSS.format(icons=ICONS, **t)


def set_theme(app: QApplication, t: dict[str, str]) -> None:
    global _current
    _current = t
    app.setPalette(_palette(t))
    app.setStyleSheet(stylesheet(t))


def apply_style(app: QApplication) -> None:
    """시스템 라이트/다크 모드에 맞춰 스타일을 적용하고, 모드가 바뀌면 다시 적용한다."""
    app.setStyle(QStyleFactory.create("Fusion"))  # 네이티브 macOS 스타일은 QSS 일부를 무시한다

    def refresh() -> None:
        dark = app.styleHints().colorScheme() == Qt.ColorScheme.Dark
        set_theme(app, DARK if dark else LIGHT)

    refresh()
    app.styleHints().colorSchemeChanged.connect(refresh)
