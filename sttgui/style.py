"""앱 전역 스타일. DESIGN-apple.md 토큰(Action Blue 단일 강조색, Parchment 배경, hairline, pill 버튼)을 QSS로 옮긴다."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

ICONS = (Path(__file__).parent / "icons").as_posix()

LIGHT = {
    "canvas": "#f5f5f7",  # 창 배경 (parchment)
    "surface": "#ffffff",  # 카드·입력칸
    "ink": "#1d1d1f",
    "muted": "#7a7a7a",
    "hairline": "#e0e0e0",
    "primary": "#0066cc",
    "primary_hover": "#0071e3",
    "button": "#ffffff",
    "button_hover": "#fafafc",
    "selection": "#d6e6f8",
    "track": "#e8e8ed",
    "indicator": "#c7c7cc",
}
DARK = {
    "canvas": "#1d1d1f",
    "surface": "#272729",
    "ink": "#f5f5f7",
    "muted": "#a1a1a6",
    "hairline": "#3a3a3c",
    "primary": "#0071e3",
    "primary_hover": "#2997ff",
    "button": "#2a2a2c",
    "button_hover": "#333336",
    "selection": "#1f3a5c",
    "track": "#3a3a3c",
    "indicator": "#5a5a5e",
}

QSS = """
QWidget {{ color: {ink}; font-size: 13px; }}
QMainWindow, QDialog {{ background: {canvas}; }}

QGroupBox {{
    background: {surface}; border: 1px solid {hairline}; border-radius: 12px;
    margin-top: 24px; padding: 6px 12px 12px 12px;
}}
QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top left;
    left: 4px; padding: 0 0 6px 0; font-size: 13px; font-weight: 600;
}}

QLabel[role="muted"] {{ color: {muted}; font-size: 12px; }}
QLabel[role="heading"] {{ font-size: 13px; font-weight: 600; }}

QPushButton {{
    background: {button}; color: {ink}; border: 1px solid {hairline};
    border-radius: 8px; padding: 6px 14px; min-height: 18px;
}}
QPushButton:hover {{ background: {button_hover}; }}
QPushButton:pressed {{ background: {hairline}; }}
QPushButton:disabled {{ color: {muted}; }}
QPushButton:focus {{ border: 1px solid {primary_hover}; }}
QPushButton[role="primary"] {{
    background: {primary}; color: #ffffff; border: none;
    border-radius: 16px; padding: 8px 22px; font-weight: 600;
}}
QPushButton[role="primary"]:hover {{ background: {primary_hover}; }}
QPushButton[role="primary"]:disabled {{ background: {track}; color: {muted}; }}

QListWidget, QPlainTextEdit, QLineEdit, QComboBox, QDoubleSpinBox {{
    background: {surface}; border: 1px solid {hairline}; border-radius: 8px;
    selection-background-color: {selection}; selection-color: {ink};
}}
QListWidget {{ padding: 4px; outline: none; }}
QListWidget::item {{ padding: 5px 6px; border-radius: 6px; }}
QListWidget::item:selected {{ background: {selection}; color: {ink}; }}
QPlainTextEdit {{ padding: 8px; }}
QLineEdit, QComboBox, QDoubleSpinBox {{ padding: 4px 8px; min-height: 18px; }}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {primary_hover};
}}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url({icons}/chevron-down.svg); width: 10px; height: 10px; }}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ border: none; width: 18px; }}
QDoubleSpinBox::up-arrow {{ image: url({icons}/chevron-up.svg); width: 9px; height: 9px; }}
QDoubleSpinBox::down-arrow {{ image: url({icons}/chevron-down.svg); width: 9px; height: 9px; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 14px; height: 14px; border: 1px solid {indicator}; border-radius: 4px; background: {surface};
}}
QCheckBox::indicator:checked {{
    background: {primary}; border: 1px solid {primary}; image: url({icons}/check.svg);
}}
QComboBox QAbstractItemView {{
    background: {surface}; border: 1px solid {hairline}; selection-background-color: {selection};
}}

QProgressBar {{
    background: {track}; border: none; border-radius: 3px;
    max-height: 6px; min-height: 6px; text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background: {primary}; border-radius: 3px; }}

QToolTip {{
    background: {surface}; color: {ink}; border: 1px solid {hairline};
    border-radius: 6px; padding: 6px;
}}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {hairline}; border-radius: 3px; min-height: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
"""


def _palette(t: dict[str, str]) -> QPalette:
    """Fusion이 직접 그리는 체크박스·콤보 화살표 등이 토큰 색을 따르도록 팔레트를 맞춘다."""
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
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(t["muted"]))
    p.setColor(QPalette.Disabled, QPalette.WindowText, QColor(t["muted"]))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(t["muted"]))
    return p


def apply_style(app: QApplication) -> None:
    """시스템 라이트/다크 모드에 맞춰 스타일을 적용하고, 모드가 바뀌면 다시 적용한다."""
    app.setStyle(QStyleFactory.create("Fusion"))  # 네이티브 macOS 스타일은 QSS 일부를 무시한다

    def refresh() -> None:
        t = DARK if app.styleHints().colorScheme() == Qt.ColorScheme.Dark else LIGHT
        app.setPalette(_palette(t))
        app.setStyleSheet(QSS.format(icons=ICONS, **t))

    refresh()
    app.styleHints().colorSchemeChanged.connect(refresh)
