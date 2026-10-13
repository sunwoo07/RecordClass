from __future__ import annotations

import html
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, QModelIndex, QPoint, QProcess, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDropEvent,
    QFont,
    QIcon,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QShortcut,
    QTextBlockFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from sttgui import style
from sttgui.settings import Settings, SettingsPanel

AUDIO_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".m4a",
    ".mp4",
    ".aac",
    ".flac",
    ".ogg",
    ".wma",
    ".mov",
    ".mkv",
}

VOICE_MEMOS_DIR = (
    Path.home()
    / "Library"
    / "Group Containers"
    / "group.com.apple.VoiceMemos.shared"
    / "Recordings"
)


PATH_ROLE = Qt.UserRole
STATUS_ROLE = Qt.UserRole + 1
OUTPUT_ROLE = Qt.UserRole + 2  # 워커가 저장한 결과 파일 경로 목록 (요약 원본 선택용)
DETAIL_ROLE = Qt.UserRole + 3  # 대기열 행 아래 줄 문구 (없으면 STATUS_LABEL)
PROGRESS_ROLE = Qt.UserRole + 4  # 진행 중일 때 0~100
TRANSCRIPT_ROLE = Qt.UserRole + 5  # 본문에 보여줄 전사 텍스트 (실시간 줄 또는 저장된 TXT)
SUMMARY_ROLE = Qt.UserRole + 6  # 요약 파일(.summary.md) 경로
STATUS_LABEL = {
    "pending": "대기 중",
    "running": "전사 중",
    "summarizing": "요약 중",
    "done": "완료",
    "failed": "실패 — 세부 로그를 확인하세요",
}
# 요약 원본으로 쓸 결과 파일 우선순위: 교정본 > 원본, 문단형(TXT/MD) > 자막형
SUMMARY_SOURCE_SUFFIXES = [
    ".corrected.txt", ".corrected.md", ".corrected.vtt", ".corrected.srt",
    ".txt", ".md", ".vtt", ".srt",
]
WORKER_SCRIPT = str(Path(__file__).parent / "transcribe_worker.py")
TIMESTAMP_RE = re.compile(r"^\[(\d{2}:\d{2}(?::\d{2})?)\]\s*")


def format_hms(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def pick_summary_source(files: list[str]) -> str | None:
    """결과 파일 중 요약에 쓸 파일 하나를 우선순위대로 고른다. 지금 없는 파일은 건너뛴다."""
    for suffix in SUMMARY_SOURCE_SUFFIXES:
        for f in files:
            if f.endswith(suffix) and Path(f).is_file():
                return f
    return None


def paragraph_html(text: str) -> str:
    """전사 문단 하나를 HTML로. 앞의 [시각]은 흐리게 표시한다."""
    stamp = ""
    m = TIMESTAMP_RE.match(text)
    if m:
        stamp = f'<span style="color:{style.theme()["muted"]}">{m.group(1)}</span>&nbsp;&nbsp;'
        text = text[m.end():]
    body = html.escape(text.strip()).replace("\n", "<br>")
    return f'<p style="line-height:165%; margin-bottom:8px">{stamp}{body}</p>'


def transcript_html(text: str) -> str:
    """빈 줄로 나뉜 전사 텍스트 전체를 HTML로."""
    return "".join(paragraph_html(p) for p in re.split(r"\n\s*\n", text) if p.strip())


class QueueDelegate(QStyledItemDelegate):
    """대기열 한 줄: 상태 점 · 파일 이름 · 상태 문구, 진행 중이면 얇은 진행 막대."""

    ROW_HEIGHT = 54

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(option.rect.width(), self.ROW_HEIGHT)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        t = style.theme()
        status = index.data(STATUS_ROLE)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        r = option.rect.adjusted(2, 2, -2, -2)
        painter.setPen(Qt.NoPen)
        if option.state & QStyle.State_Selected:
            painter.setBrush(QColor(t["selection"]))
            painter.drawRoundedRect(r, 8, 8)

        painter.setBrush(QColor(style.STATUS_COLORS[status]))
        painter.drawEllipse(QRect(r.left() + 12, r.top() + 14, 8, 8))

        left = r.left() + 30
        width = r.right() - left - 10
        font = QFont(option.font)
        font.setPixelSize(13)
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(t["ink"]))
        name = painter.fontMetrics().elidedText(index.data(Qt.DisplayRole) or "", Qt.ElideMiddle, width)
        painter.drawText(QRect(left, r.top() + 7, width, 20), Qt.AlignLeft | Qt.AlignVCenter, name)

        font.setPixelSize(11)
        font.setWeight(QFont.Normal)
        painter.setFont(font)
        painter.setPen(QColor(t["muted"]))
        detail = index.data(DETAIL_ROLE) or STATUS_LABEL[status]
        detail = painter.fontMetrics().elidedText(detail, Qt.ElideRight, width)
        painter.drawText(QRect(left, r.top() + 26, width, 16), Qt.AlignLeft | Qt.AlignVCenter, detail)

        progress = index.data(PROGRESS_ROLE)
        if status in ("running", "summarizing") and progress is not None:
            track = QRect(left, r.bottom() - 7, width, 3)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(t["track"]))
            painter.drawRoundedRect(track, 1.5, 1.5)
            painter.setBrush(QColor(t["primary"]))
            painter.drawRoundedRect(QRect(left, track.top(), int(width * progress / 100), 3), 1.5, 1.5)
        painter.restore()


class QueueList(QListWidget):
    """비어 있으면 끌어다 놓으라는 안내를 그리는 대기열."""

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if self.count() == 0:
            painter = QPainter(self.viewport())
            painter.setPen(QColor(style.theme()["muted"]))
            painter.drawText(
                self.viewport().rect().adjusted(16, 0, -16, 0),
                Qt.AlignCenter | Qt.TextWordWrap,
                "녹음 파일을 여기에\n끌어다 놓으세요",
            )


class ClickableLabel(QLabel):
    clicked = Signal()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self.clicked.emit()
        super().mouseReleaseEvent(event)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("RecordClass")
        self.resize(1040, 700)
        self.setMinimumSize(820, 560)
        self.setAcceptDrops(True)

        self.current_item: QListWidgetItem | None = None
        self._last_run_item: QListWidgetItem | None = None
        self._cancelled = False
        self.process: QProcess | None = None
        self.total_duration: float | None = None
        self.settings = Settings.load()
        self.output_dir: Path | None = None  # 마지막으로 사용한 저장 폴더
        self._progress_current: float = 0.0
        self._progress_total: float | None = None
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)
        self._start_time: float = 0.0
        self._job = "transcribe"  # 현재 워커 작업: "transcribe" | "summary"
        self._phase = ""  # LLM 단계 이름 ("교정"/"요약"). 비어 있으면 전사 단계

        self._build_ui()
        self._build_menu()
        self._update_start_btn()
        self._refresh_detail()

    # ---------- UI ----------
    def _build_ui(self) -> None:
        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_sidebar())
        layout.addWidget(self._build_content(), stretch=1)
        self.setCentralWidget(root)

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setProperty("role", "sidebar")
        sidebar.setFixedWidth(290)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 18, 12, 16)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(6, 0, 0, 0)
        title = QLabel("강의 녹음")
        title.setProperty("role", "title")
        self.clear_btn = QPushButton("정리")
        self.clear_btn.setProperty("role", "plain")
        self.clear_btn.setToolTip("완료·실패한 항목을 목록에서 지웁니다")
        self.clear_btn.clicked.connect(self._on_clear_finished)
        add_btn = QPushButton()
        add_btn.setProperty("role", "icon")
        add_btn.setIcon(QIcon(f"{style.ICONS}/plus.svg"))
        add_btn.setToolTip("파일 추가 (⌘O)")
        add_btn.clicked.connect(self._on_browse)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.clear_btn)
        header.addWidget(add_btn)
        layout.addLayout(header)

        self.queue_list = QueueList()
        self.queue_list.setProperty("role", "queue")
        self.queue_list.setItemDelegate(QueueDelegate(self.queue_list))
        self.queue_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.queue_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.queue_list.customContextMenuRequested.connect(self._on_queue_menu)
        self.queue_list.itemSelectionChanged.connect(self._refresh_detail)
        for key in (QKeySequence.Delete, QKeySequence(Qt.Key_Backspace)):
            QShortcut(key, self.queue_list, self._on_remove_selected, context=Qt.WidgetShortcut)
        layout.addWidget(self.queue_list, stretch=1)

        self.settings_label = ClickableLabel(self.settings.summary())
        self.settings_label.setProperty("role", "summary")
        self.settings_label.setWordWrap(True)
        self.settings_label.setCursor(Qt.PointingHandCursor)
        self.settings_label.setToolTip("눌러서 설정 바꾸기 (⌘,)")
        self.settings_label.clicked.connect(self._on_preferences)
        layout.addWidget(self.settings_label)

        self.status_label = QLabel("대기 중")
        self.status_label.setProperty("role", "muted")
        self.status_label.setWordWrap(True)
        self.status_label.setContentsMargins(4, 0, 4, 0)
        layout.addWidget(self.status_label)

        self.start_btn = QPushButton("전사 시작")
        self.start_btn.setProperty("role", "primary")
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.clicked.connect(self._on_start)
        self.cancel_btn = QPushButton("취소")
        self.cancel_btn.setProperty("role", "cancel")
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.clicked.connect(self._on_cancel)
        layout.addWidget(self.start_btn)
        layout.addWidget(self.cancel_btn)
        return sidebar

    def _build_content(self) -> QWidget:
        content = QWidget()
        content.setProperty("role", "content")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 14, 28, 20)
        layout.setSpacing(16)

        # 작업 / 설정 전환
        seg = QFrame()
        seg.setProperty("role", "segmented")
        seg_layout = QHBoxLayout(seg)
        seg_layout.setContentsMargins(2, 2, 2, 2)
        seg_layout.setSpacing(2)
        self.tab_group = QButtonGroup(self)
        for i, label in enumerate(("작업", "설정")):
            btn = QPushButton(label)
            btn.setProperty("role", "segment")
            btn.setCheckable(True)
            btn.setChecked(i == 0)
            btn.setCursor(Qt.PointingHandCursor)
            self.tab_group.addButton(btn, i)
            seg_layout.addWidget(btn)
        top = QHBoxLayout()
        top.addStretch()
        top.addWidget(seg)
        top.addStretch()
        layout.addLayout(top)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_work_page())
        self.settings_panel = SettingsPanel(self.settings)
        self.settings_panel.changed.connect(self._on_settings_changed)
        self.stack.addWidget(self.settings_panel)
        self.tab_group.idClicked.connect(self.stack.setCurrentIndex)
        layout.addWidget(self.stack, stretch=1)
        return content

    def _build_work_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        # 비어 있을 때: 무엇을 하면 되는지 안내
        self.empty_view = QWidget()
        empty = QVBoxLayout(self.empty_view)
        empty.addStretch()
        hero = QLabel("강의 녹음을 추가하세요")
        hero.setProperty("role", "hero")
        hero.setAlignment(Qt.AlignCenter)
        hint = QLabel(
            "파일을 창에 끌어다 놓거나 아래 버튼으로 고르면 차례대로 전사합니다.\n"
            "m4a · mp3 · wav · mp4 등, 음성 메모 앱의 녹음도 바로 고를 수 있어요."
        )
        hint.setProperty("role", "muted")
        hint.setAlignment(Qt.AlignCenter)
        pick_btn = QPushButton("파일 선택…")
        pick_btn.setProperty("role", "primary")
        pick_btn.setCursor(Qt.PointingHandCursor)
        pick_btn.clicked.connect(self._on_browse)
        empty.addWidget(hero)
        empty.addSpacing(6)
        empty.addWidget(hint)
        empty.addSpacing(18)
        empty.addWidget(pick_btn, alignment=Qt.AlignCenter)
        empty.addStretch(2)
        layout.addWidget(self.empty_view)

        # 선택한 파일의 상세
        self.detail_view = QWidget()
        detail = QVBoxLayout(self.detail_view)
        detail.setContentsMargins(0, 0, 0, 0)
        detail.setSpacing(10)
        self.title_label = QLabel()
        self.title_label.setProperty("role", "headline")
        self.info_label = QLabel()
        self.info_label.setProperty("role", "muted")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        detail.addWidget(self.title_label)
        detail.addWidget(self.info_label)
        detail.addWidget(self.progress_bar)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.open_folder_btn = QPushButton("Finder에서 보기")
        self.open_folder_btn.clicked.connect(self._on_open_folder)
        self.summary_btn = QPushButton("요약 만들기")
        self.summary_btn.setToolTip("LLM이 전사본으로 강의 노트를 만들어 '.summary.md'로 저장합니다")
        self.summary_btn.clicked.connect(self._on_summary_clicked)
        actions.addWidget(self.open_folder_btn)
        actions.addWidget(self.summary_btn)
        actions.addStretch()
        self.view_group = QButtonGroup(self)
        self.view_seg = QFrame()
        self.view_seg.setProperty("role", "segmented")
        view_layout = QHBoxLayout(self.view_seg)
        view_layout.setContentsMargins(2, 2, 2, 2)
        view_layout.setSpacing(2)
        for i, label in enumerate(("전사본", "요약")):
            btn = QPushButton(label)
            btn.setProperty("role", "segment")
            btn.setCheckable(True)
            btn.setChecked(i == 0)
            self.view_group.addButton(btn, i)
            view_layout.addWidget(btn)
        self.view_group.idClicked.connect(lambda _: self._render_reader())
        actions.addWidget(self.view_seg)
        detail.addLayout(actions)

        self.transcript_view = QTextBrowser()
        self.transcript_view.setProperty("role", "reader")
        self.transcript_view.setOpenExternalLinks(True)
        detail.addWidget(self.transcript_view, stretch=1)

        self.log_toggle = QPushButton("세부 로그 보기")
        self.log_toggle.setProperty("role", "plain")
        self.log_toggle.setCheckable(True)
        self.log_toggle.toggled.connect(self._on_log_toggled)
        detail.addWidget(self.log_toggle, alignment=Qt.AlignLeft)
        self.log_view = QPlainTextEdit()
        self.log_view.setProperty("role", "log")
        self.log_view.setReadOnly(True)
        self.log_view.setFixedHeight(150)
        self.log_view.hide()
        detail.addWidget(self.log_view)
        layout.addWidget(self.detail_view)
        return page

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("파일")
        add_action = QAction("파일 추가…", self)
        add_action.setShortcut(QKeySequence.Open)
        add_action.triggered.connect(self._on_browse)
        file_menu.addAction(add_action)
        # macOS에서는 PreferencesRole 덕분에 앱 메뉴의 '설정…'(⌘,)으로 이동한다
        prefs_action = QAction("설정…", self)
        prefs_action.setShortcut(QKeySequence.Preferences)
        prefs_action.setMenuRole(QAction.PreferencesRole)
        prefs_action.triggered.connect(self._on_preferences)
        file_menu.addAction(prefs_action)

    def _show_tab(self, index: int) -> None:
        self.tab_group.button(index).setChecked(True)
        self.stack.setCurrentIndex(index)

    def _on_preferences(self) -> None:
        self._show_tab(1)

    def _on_settings_changed(self) -> None:
        # 진행 중인 파일에는 영향 없음 — 다음 파일부터 반영
        self.settings = self.settings_panel.settings()
        self.settings.save()
        self.settings_label.setText(self.settings.summary())

    def _on_log_toggled(self, shown: bool) -> None:
        self.log_view.setVisible(shown)
        self.log_toggle.setText("세부 로그 숨기기" if shown else "세부 로그 보기")

    # ---------- 본문 (선택한 파일 상세) ----------
    def _focused_item(self) -> QListWidgetItem | None:
        """본문에 보여줄 항목: 하나만 골랐으면 그것, 아니면 진행 중인 파일, 그것도 없으면 첫 항목."""
        selected = self.queue_list.selectedItems()
        if len(selected) == 1:
            return selected[0]
        if self.current_item is not None:
            return self.current_item
        return self.queue_list.item(0)

    def _refresh_detail(self) -> None:
        item = self._focused_item()
        self.empty_view.setVisible(item is None)
        self.detail_view.setVisible(item is not None)
        if item is None:
            return
        status = item.data(STATUS_ROLE)
        self.title_label.setText(item.data(PATH_ROLE).stem)
        self.info_label.setText(item.data(DETAIL_ROLE) or STATUS_LABEL[status])
        self.progress_bar.setVisible(item is self.current_item)
        done = status == "done"
        self.open_folder_btn.setVisible(done)
        self.summary_btn.setVisible(done)
        self.summary_btn.setEnabled(not self._is_running())
        self.summary_btn.setText("요약 다시 만들기" if item.data(SUMMARY_ROLE) else "요약 만들기")
        self.view_seg.setVisible(bool(item.data(SUMMARY_ROLE)))
        if not item.data(SUMMARY_ROLE):
            self.view_group.button(0).setChecked(True)
        placeholder = {
            "pending": "전사를 시작하면 이곳에 내용이 실시간으로 나타납니다.",
            "running": "모델을 준비하는 중입니다. 첫 실행이라면 모델을 내려받느라 시간이 걸릴 수 있어요.",
            "failed": "전사에 실패했습니다. 아래 '세부 로그 보기'에서 원인을 확인하세요.",
        }.get(status, "")
        self.transcript_view.setPlaceholderText(placeholder)
        self._render_reader()

    def _render_reader(self) -> None:
        item = self._focused_item()
        if item is None:
            return
        summary = item.data(SUMMARY_ROLE)
        if summary and self.view_group.checkedId() == 1:
            try:
                self.transcript_view.setMarkdown(Path(summary).read_text(encoding="utf-8"))
            except OSError:
                self.transcript_view.setPlainText("요약 파일을 열 수 없습니다.")
                return
            self._space_out_blocks()
            return
        self.transcript_view.setHtml(transcript_html(item.data(TRANSCRIPT_ROLE) or ""))
        if item is self.current_item:
            self._scroll_reader_to_end()

    def _space_out_blocks(self) -> None:
        """Markdown 기본 렌더링은 줄 간격이 빽빽하다. 문단 사이를 띄우고 제목 위에 여백을 준다."""
        doc = self.transcript_view.document()
        cursor = QTextCursor(doc)
        block = doc.begin()
        while block.isValid():
            fmt = block.blockFormat()
            fmt.setLineHeight(150, QTextBlockFormat.ProportionalHeight.value)
            fmt.setBottomMargin(6)
            if fmt.headingLevel():
                fmt.setTopMargin(0 if block == doc.begin() else 16)
                fmt.setBottomMargin(8)
            cursor.setPosition(block.position())
            cursor.setBlockFormat(fmt)
            block = block.next()

    def _scroll_reader_to_end(self) -> None:
        bar = self.transcript_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _update_item(self, item: QListWidgetItem, **data: object) -> None:
        roles = {"detail": DETAIL_ROLE, "progress": PROGRESS_ROLE}
        for key, value in data.items():
            item.setData(roles[key], value)
        if item is self._focused_item():
            self.info_label.setText(item.data(DETAIL_ROLE) or STATUS_LABEL[item.data(STATUS_ROLE)])

    # ---------- 파일 선택 / 드래그앤드롭 ----------
    def _set_dropping(self, on: bool) -> None:
        self.queue_list.setProperty("dropping", on)
        self.queue_list.style().unpolish(self.queue_list)
        self.queue_list.style().polish(self.queue_list)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_dropping(True)

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._set_dropping(False)

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_dropping(False)
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls()]
        unsupported = [p.name for p in paths if p.suffix.lower() not in AUDIO_EXTENSIONS]
        if unsupported:
            QMessageBox.warning(
                self, "지원하지 않는 형식", "다음 파일은 제외됩니다:\n" + "\n".join(unsupported)
            )
        self._add_files([p for p in paths if p.suffix.lower() in AUDIO_EXTENSIONS])

    def _on_browse(self) -> None:
        filter_str = "오디오/비디오 파일 (*" + " *".join(sorted(AUDIO_EXTENSIONS)) + ")"
        start_dir = str(VOICE_MEMOS_DIR) if VOICE_MEMOS_DIR.is_dir() else ""
        path_strs, _ = QFileDialog.getOpenFileNames(
            self, "강의 녹음 파일 선택", start_dir, filter_str
        )
        self._add_files([Path(p) for p in path_strs])

    # ---------- 대기 큐 ----------
    def _queue_items(self) -> list[QListWidgetItem]:
        return [self.queue_list.item(i) for i in range(self.queue_list.count())]

    def _set_status(self, item: QListWidgetItem, status: str) -> None:
        item.setData(STATUS_ROLE, status)
        item.setData(DETAIL_ROLE, None)
        item.setData(PROGRESS_ROLE, None)
        item.setText(item.data(PATH_ROLE).name)
        if item is self._focused_item():
            self._refresh_detail()

    def _is_running(self) -> bool:
        return self.current_item is not None

    def _update_start_btn(self) -> None:
        running = self._is_running()
        pending = sum(i.data(STATUS_ROLE) == "pending" for i in self._queue_items())
        self.start_btn.setEnabled(pending > 0 and not running)
        self.start_btn.setText(f"{pending}개 전사 시작" if pending > 1 else "전사 시작")
        self.start_btn.setVisible(not running)
        self.cancel_btn.setVisible(running)
        self.cancel_btn.setEnabled(running)
        self.summary_btn.setEnabled(not running)

    def _add_files(self, paths: list[Path]) -> None:
        # 이미 큐에 있고 아직 처리 전/진행 중인 파일은 중복 추가하지 않는다
        active = {
            i.data(PATH_ROLE)
            for i in self._queue_items()
            if i.data(STATUS_ROLE) in ("pending", "running")
        }
        for path in paths:
            if path in active:
                continue
            active.add(path)
            item = QListWidgetItem()
            item.setData(PATH_ROLE, path)
            item.setToolTip(str(path))
            self.queue_list.addItem(item)
            self._set_status(item, "pending")
        self._update_start_btn()
        self._refresh_detail()

    def _on_remove_selected(self) -> None:
        for item in self.queue_list.selectedItems():
            if item is not self.current_item:
                self.queue_list.takeItem(self.queue_list.row(item))
        self._update_start_btn()
        self._refresh_detail()

    def _on_clear_finished(self) -> None:
        for item in self._queue_items():
            if item.data(STATUS_ROLE) in ("done", "failed"):
                self.queue_list.takeItem(self.queue_list.row(item))
        self._refresh_detail()

    # ---------- 전사 실행 ----------
    def _on_start(self) -> None:
        self._cancelled = False
        self.log_view.clear()
        self._show_tab(0)
        self._start_next()

    def _start_next(self) -> None:
        """큐에서 다음 대기 항목을 꺼내 실행. 없으면 전체 종료 처리."""
        item = next(
            (i for i in self._queue_items() if i.data(STATUS_ROLE) == "pending"), None
        )
        if item is None:
            self._finish_queue()
            return

        audio_path: Path = item.data(PATH_ROLE)
        # 설정은 파일마다 현재 값을 읽는다 (큐 진행 중 변경 시 다음 파일부터 반영)
        settings = self.settings
        self.output_dir = Path(settings.output_dir) if settings.output_dir else audio_path.parent
        formats = settings.formats or ["txt"]
        model_repo = settings.model
        language = settings.language

        # 사용자가 다른 파일을 보고 있지 않으면 진행 중인 파일을 따라간다
        selected = self.queue_list.selectedItems()
        self.current_item = item
        if not selected or selected == [self._last_run_item]:
            self.queue_list.setCurrentItem(item, QItemSelectionModel.ClearAndSelect)
        self._last_run_item = item
        item.setData(TRANSCRIPT_ROLE, "")
        self._set_status(item, "running")
        self._update_item(item, detail="모델 준비 중…", progress=0)
        self.queue_list.scrollToItem(item)
        self.progress_bar.setValue(0)
        self.total_duration = None
        self.status_label.setText(
            f"{self._queue_position()}모델 로딩 중... (최초 실행 시 다운로드로 시간이 걸릴 수 있습니다)"
        )
        self._log(f"\n===== {self._queue_position()}파일: {audio_path}")
        self._log(f"모델: {model_repo} / 언어: {language} / 형식: {', '.join(formats)}")

        self._job = "transcribe"
        self._launch(
            [
                "--audio",
                str(audio_path),
                "--model",
                model_repo,
                "--language",
                language,
                "--outdir",
                str(self.output_dir),
                "--formats",
                ",".join(formats),
                # '=' 형식: 값이 '-'로 시작해도 argparse가 옵션으로 오인하지 않게
                f"--initial-prompt={settings.initial_prompt.strip()}",
            ]
            + (["--no-condition-prev"] if settings.no_condition_prev else [])
            + (["--dedupe"] if settings.dedupe else [])
            + (["--skip-silence"] if settings.skip_silence else [])
            + (["--preprocess"] if settings.preprocess else [])
            + [f"--paragraph-gap={settings.paragraph_gap}"]
            + ([] if settings.txt_timestamps else ["--no-txt-timestamps"])
            + (["--correct", f"--llm-model={settings.llm_model}"] if settings.correct else [])
        )

    def _launch(self, worker_args: list[str]) -> None:
        """워커 프로세스를 띄우고 진행 표시를 초기화한다."""
        self.process = QProcess(self)
        self.process.setProgram(sys.executable)
        self.process.setArguments([WORKER_SCRIPT] + worker_args)
        self.process.readyReadStandardOutput.connect(self._on_stdout)
        self.process.readyReadStandardError.connect(self._on_stderr)
        self.process.finished.connect(self._on_finished)
        self.process.errorOccurred.connect(self._on_process_error)

        self._update_start_btn()
        self._refresh_detail()
        self._phase = ""
        self._progress_current = 0.0
        self._progress_total = None
        self._start_time = time.monotonic()
        self._elapsed_timer.start()

        self.process.start()

    # ---------- 요약 ----------
    def _on_queue_menu(self, pos: QPoint) -> None:
        item = self.queue_list.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        summary_action = reveal_action = None
        if item.data(STATUS_ROLE) == "done":
            summary_action = menu.addAction("요약 다시 만들기" if item.data(SUMMARY_ROLE) else "요약 만들기")
            summary_action.setEnabled(not self._is_running())
            reveal_action = menu.addAction("Finder에서 보기")
            menu.addSeparator()
        remove_action = menu.addAction("목록에서 제거")
        remove_action.setEnabled(item is not self.current_item)
        chosen = menu.exec(self.queue_list.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == summary_action:
            self._start_summary(item)
        elif chosen == reveal_action:
            self._reveal(item)
        elif chosen == remove_action:
            self.queue_list.takeItem(self.queue_list.row(item))
            self._update_start_btn()
            self._refresh_detail()

    def _on_summary_clicked(self) -> None:
        item = self._focused_item()
        if item is not None:
            self._start_summary(item)

    def _start_summary(self, item: QListWidgetItem) -> None:
        source = pick_summary_source(item.data(OUTPUT_ROLE) or [])
        if source is None:
            QMessageBox.warning(self, "요약 불가", "요약할 전사 결과 파일을 찾을 수 없습니다.")
            return
        audio_path: Path = item.data(PATH_ROLE)
        self.output_dir = Path(source).parent
        self.current_item = item
        self._set_status(item, "summarizing")
        self._update_item(item, detail="요약 모델 준비 중…", progress=0)
        self.progress_bar.setValue(0)
        self.status_label.setText("요약 모델 로딩 중... (최초 실행 시 다운로드로 시간이 걸릴 수 있습니다)")
        self._log(f"\n===== 요약: {source}")
        self._log(f"LLM 모델: {self.settings.llm_model}")
        self._job = "summary"
        self._launch(
            [
                "--summarize",
                source,
                "--audio",
                str(audio_path),
                "--outdir",
                str(self.output_dir),
                f"--llm-model={self.settings.llm_model}",
            ]
        )

    def _on_cancel(self) -> None:
        # 현재 파일은 중단 후 '대기'로 되돌리고, 나머지 큐는 그대로 둔다
        self._cancelled = True
        if self.process is not None and self.process.state() != QProcess.NotRunning:
            self.process.kill()  # -> _on_finished 에서 정리

    def _queue_position(self) -> str:
        if self.current_item is None:
            return ""
        row = self.queue_list.row(self.current_item) + 1
        return f"[{row}/{self.queue_list.count()}] "

    def _tick_elapsed(self) -> None:
        elapsed = time.monotonic() - self._start_time
        item = self.current_item
        if self._phase:
            # LLM 단계: 진행 단위가 오디오 초가 아니라 묶음 수
            done = f" {int(self._progress_current)}/{self._progress_total}" if self._progress_total else ""
            self.status_label.setText(
                f"{self._queue_position()}{self._phase} 중{done}... (경과 {format_hms(elapsed)})"
            )
            if item is not None:
                self._update_item(item, detail=f"{self._phase} 중{done} · 경과 {format_hms(elapsed)}")
            return
        text = f"{self._queue_position()}처리 중... (경과 {format_hms(elapsed)}"
        detail = f"전사 중 · 경과 {format_hms(elapsed)}"
        if self._progress_total and self._progress_current > 0 and elapsed > 1:
            speed = self._progress_current / elapsed  # 오디오 초 / 실제 초
            remaining_audio = max(0.0, self._progress_total - self._progress_current)
            if speed > 0:
                eta = remaining_audio / speed
                text += f" / 남은 시간 약 {format_hms(eta)} / {speed:.1f}배속"
                pct = int(self._progress_current / self._progress_total * 100)
                detail = f"{pct}% · 약 {format_hms(eta)} 남음 · {speed:.1f}배속"
        text += ")"
        self.status_label.setText(text)
        if item is not None:
            self._update_item(item, detail=detail)

    def _on_stdout(self) -> None:
        if self.process is None:
            return
        data = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        for line in data.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._handle_message(obj)

    def _on_stderr(self) -> None:
        if self.process is None:
            return
        data = bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace")
        if data.strip():
            self._log("[stderr] " + data.strip())

    def _set_progress(self, pct: int) -> None:
        self.progress_bar.setValue(pct)
        if self.current_item is not None:
            self._update_item(self.current_item, progress=pct)

    def _append_transcript(self, line: str) -> None:
        item = self.current_item
        if item is None:
            return
        prev = item.data(TRANSCRIPT_ROLE) or ""
        item.setData(TRANSCRIPT_ROLE, f"{prev}\n\n{line}" if prev else line)
        if item is self._focused_item() and self.view_group.checkedId() == 0:
            bar = self.transcript_view.verticalScrollBar()
            at_end = bar.value() >= bar.maximum() - 4  # 위로 올려 읽는 중이면 따라 내리지 않는다
            self.transcript_view.append(paragraph_html(line))
            if at_end:
                self._scroll_reader_to_end()

    def _handle_message(self, obj: dict) -> None:
        msg_type = obj.get("type")
        if msg_type == "start":
            self.total_duration = obj.get("total")
            if self.total_duration:
                self._log(f"오디오 길이: {format_hms(self.total_duration)}")
        elif msg_type == "segment":
            start = format_hms(obj.get("start", 0))
            text = obj.get("text", "").strip()
            self._append_transcript(f"[{start}] {text}")
        elif msg_type == "progress":
            current = obj.get("current", 0)
            total = obj.get("total") or self.total_duration
            self._progress_current = current
            self._progress_total = total
            if total:
                self._set_progress(max(0, min(100, int(current / total * 100))))
        elif msg_type == "phase":
            self._phase = obj.get("label", "")
            self._progress_current, self._progress_total = 0.0, None
            self._set_progress(0)
            self._log(f"{self._phase} 시작 (LLM 모델 로딩 — 최초 실행 시 다운로드로 시간이 걸릴 수 있습니다)")
        elif msg_type == "llm_progress":
            current, total = obj.get("current", 0), obj.get("total", 0)
            self._progress_current, self._progress_total = current, total
            if total:
                self._set_progress(max(0, min(100, int(current / total * 100))))
        elif msg_type == "notice":
            self._log(obj.get("message", ""))
        elif msg_type == "error":
            self._log("[오류] " + obj.get("message", ""))
        elif msg_type == "done":
            self._set_progress(100)
            self._log("요약 완료." if self._job == "summary" else "전사 완료.")
            files = obj.get("output_files", [])
            if self.current_item is not None:
                if self._job == "transcribe":
                    self.current_item.setData(OUTPUT_ROLE, files)
                else:
                    summary = next((f for f in files if f.endswith(".summary.md")), files[0] if files else None)
                    self.current_item.setData(SUMMARY_ROLE, summary)
            for f in files:
                self._log(f"저장됨: {f}")

    def _load_saved_transcript(self, item: QListWidgetItem) -> None:
        """저장된 TXT(교정본 우선)가 있으면 실시간 줄 대신 문단으로 정리된 본문을 보여준다."""
        for suffix in (".corrected.txt", ".txt"):
            path = next((f for f in item.data(OUTPUT_ROLE) or [] if f.endswith(suffix)), None)
            if path and Path(path).is_file():
                item.setData(TRANSCRIPT_ROLE, Path(path).read_text(encoding="utf-8"))
                return

    def _on_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        self._elapsed_timer.stop()
        item, self.current_item = self.current_item, None
        if item is None:
            return
        ok = exit_code == 0 and exit_status == QProcess.NormalExit
        if self._job == "summary":
            # 요약은 큐와 별개: 성공·실패·취소 모두 항목을 '완료'로 되돌린다
            self._set_status(item, "done")
            if self._cancelled:
                self._log("취소됨.")
                self.status_label.setText("취소됨")
            elif ok:
                self.status_label.setText("요약 완료")
                if item is self._focused_item():
                    self.view_group.button(1).setChecked(True)
                QApplication.alert(self)
            else:
                self.status_label.setText("요약 실패")
                self._log("[오류] 요약에 실패했습니다.")
            self._cancelled = False
            self._update_start_btn()
            self._refresh_detail()
            return
        if self._cancelled:
            self._set_status(item, "pending")
            self._log("취소됨.")
            self.status_label.setText("취소됨")
            self._update_start_btn()
            self._refresh_detail()
            return
        if ok:
            self._load_saved_transcript(item)
            self._set_status(item, "done")
            count = len(item.data(OUTPUT_ROLE) or [])
            self._update_item(item, detail=f"완료 · 파일 {count}개 저장" if count else None)
        else:
            self._set_status(item, "failed")
            self._log("[오류] 이 파일의 전사에 실패했습니다. 다음 파일로 넘어갑니다.")
        self._start_next()

    def _finish_queue(self) -> None:
        self._update_start_btn()
        self._refresh_detail()
        statuses = [i.data(STATUS_ROLE) for i in self._queue_items()]
        done, failed = statuses.count("done"), statuses.count("failed")
        self.status_label.setText(f"완료 {done}개 / 실패 {failed}개")
        QApplication.alert(self)  # 다른 앱을 보고 있으면 Dock 아이콘으로 알린다

    def _on_process_error(self, error: QProcess.ProcessError) -> None:
        self._log("[오류] 프로세스를 실행할 수 없습니다.")
        # 시작 자체가 실패하면 finished 시그널이 오지 않으므로 직접 다음으로 넘긴다
        if error == QProcess.FailedToStart:
            self._on_finished(1, QProcess.CrashExit)

    def _reveal(self, item: QListWidgetItem) -> None:
        files = [f for f in item.data(OUTPUT_ROLE) or [] if Path(f).exists()]
        if files:
            subprocess.run(["open", "-R", files[0]])
        elif self.output_dir is not None:
            subprocess.run(["open", str(self.output_dir)])

    def _on_open_folder(self) -> None:
        item = self._focused_item()
        if item is not None:
            self._reveal(item)

    def _log(self, text: str) -> None:
        self.log_view.appendPlainText(text)
