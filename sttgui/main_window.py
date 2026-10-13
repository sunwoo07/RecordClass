from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import QPoint, QProcess, Qt, QTimer
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
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
    QVBoxLayout,
    QWidget,
)

from sttgui.settings import Settings, SettingsDialog

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
STATUS_PREFIX = {
    "pending": "대기",
    "running": "진행",
    "summarizing": "요약",
    "done": "완료",
    "failed": "실패",
}
# 요약 원본으로 쓸 결과 파일 우선순위: 교정본 > 원본, 문단형(TXT/MD) > 자막형
SUMMARY_SOURCE_SUFFIXES = [
    ".corrected.txt", ".corrected.md", ".corrected.vtt", ".corrected.srt",
    ".txt", ".md", ".vtt", ".srt",
]
WORKER_SCRIPT = str(Path(__file__).parent / "transcribe_worker.py")


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


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("강의 녹음 STT (mlx-whisper)")
        self.resize(760, 620)
        self.setAcceptDrops(True)

        self.current_item: QListWidgetItem | None = None
        self._cancelled = False
        self.process: QProcess | None = None
        self.total_duration: float | None = None
        self.settings = Settings.load()
        self.output_dir: Path | None = None  # 마지막으로 사용한 저장 폴더 (결과 폴더 열기용)
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

    # ---------- UI ----------
    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(12)

        # 파일 선택
        file_group = QGroupBox("1. 강의 녹음 파일 (대기 큐 — 드래그하거나 '파일 추가')")
        file_layout = QHBoxLayout(file_group)
        self.queue_list = QListWidget()
        self.queue_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.queue_list.setMaximumHeight(120)
        self.queue_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.queue_list.customContextMenuRequested.connect(self._on_queue_menu)
        file_btn_layout = QVBoxLayout()
        browse_btn = QPushButton("파일 추가")
        browse_btn.clicked.connect(self._on_browse)
        remove_btn = QPushButton("선택 삭제")
        remove_btn.clicked.connect(self._on_remove_selected)
        clear_done_btn = QPushButton("완료 항목 정리")
        clear_done_btn.clicked.connect(self._on_clear_finished)
        for btn in (browse_btn, remove_btn, clear_done_btn):
            file_btn_layout.addWidget(btn)
        file_btn_layout.addStretch()
        file_layout.addWidget(self.queue_list, stretch=1)
        file_layout.addLayout(file_btn_layout)
        layout.addWidget(file_group)

        # 현재 설정 요약 (변경은 환경설정 창에서)
        self.settings_label = QLabel(self.settings.summary())
        self.settings_label.setWordWrap(True)
        self.settings_label.setProperty("role", "muted")
        layout.addWidget(self.settings_label)

        # 컨트롤
        control_layout = QHBoxLayout()
        self.start_btn = QPushButton("전사 시작")
        self.start_btn.clicked.connect(self._on_start)
        self.start_btn.setEnabled(False)
        self.start_btn.setProperty("role", "primary")
        self.cancel_btn = QPushButton("취소")
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.cancel_btn.setEnabled(False)
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.cancel_btn)
        layout.addLayout(control_layout)

        # 진행률
        progress_layout = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.status_label = QLabel("대기 중")
        self.status_label.setProperty("role", "muted")
        progress_layout.addWidget(self.progress_bar, stretch=1)
        progress_layout.addWidget(self.status_label)
        layout.addLayout(progress_layout)

        # 로그 / 미리보기
        preview_label = QLabel("실시간 결과 미리보기")
        preview_label.setProperty("role", "heading")
        layout.addWidget(preview_label)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        layout.addWidget(self.log_view, stretch=1)

        # 완료 후 액션
        result_layout = QHBoxLayout()
        self.open_folder_btn = QPushButton("결과 폴더 열기")
        self.open_folder_btn.clicked.connect(self._on_open_folder)
        self.open_folder_btn.setEnabled(False)
        result_layout.addWidget(self.open_folder_btn)
        layout.addLayout(result_layout)

        self.setCentralWidget(central)

    def _build_menu(self) -> None:
        # macOS에서는 PreferencesRole 덕분에 앱 메뉴의 '환경설정…'(⌘,)으로 이동한다
        prefs_action = QAction("환경설정…", self)
        prefs_action.setShortcut(QKeySequence.Preferences)
        prefs_action.setMenuRole(QAction.PreferencesRole)
        prefs_action.triggered.connect(self._on_preferences)
        self.menuBar().addMenu("설정").addAction(prefs_action)

    def _on_preferences(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() == SettingsDialog.Accepted:
            # 진행 중인 파일에는 영향 없음 — 다음 파일부터 반영
            self.settings = dialog.settings()
            self.settings.save()
            self.settings_label.setText(self.settings.summary())

    # ---------- 파일 선택 / 드래그앤드롭 ----------
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
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
        item.setText(f"[{STATUS_PREFIX[status]}] {item.data(PATH_ROLE).name}")

    def _is_running(self) -> bool:
        return self.current_item is not None

    def _update_start_btn(self) -> None:
        has_pending = any(i.data(STATUS_ROLE) == "pending" for i in self._queue_items())
        self.start_btn.setEnabled(has_pending and not self._is_running())

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
            self._set_status(item, "pending")
            self.queue_list.addItem(item)
        self._update_start_btn()

    def _on_remove_selected(self) -> None:
        for item in self.queue_list.selectedItems():
            if item is not self.current_item:
                self.queue_list.takeItem(self.queue_list.row(item))
        self._update_start_btn()

    def _on_clear_finished(self) -> None:
        for item in self._queue_items():
            if item.data(STATUS_ROLE) in ("done", "failed"):
                self.queue_list.takeItem(self.queue_list.row(item))

    # ---------- 전사 실행 ----------
    def _on_start(self) -> None:
        self._cancelled = False
        self.log_view.clear()
        self.cancel_btn.setEnabled(True)
        self.open_folder_btn.setEnabled(False)
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

        self.current_item = item
        self._set_status(item, "running")
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

        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self._phase = ""
        self._progress_current = 0.0
        self._progress_total = None
        self._start_time = time.monotonic()
        self._elapsed_timer.start()

        self.process.start()

    # ---------- 요약 (완료 항목 우클릭) ----------
    def _on_queue_menu(self, pos: QPoint) -> None:
        item = self.queue_list.itemAt(pos)
        if item is None or item.data(STATUS_ROLE) != "done":
            return
        menu = QMenu(self)
        action = menu.addAction("요약 만들기")
        action.setEnabled(not self._is_running())
        if menu.exec(self.queue_list.viewport().mapToGlobal(pos)) == action:
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
        if self._phase:
            # LLM 단계: 진행 단위가 오디오 초가 아니라 묶음 수
            done = f" {int(self._progress_current)}/{self._progress_total}" if self._progress_total else ""
            self.status_label.setText(
                f"{self._queue_position()}{self._phase} 중{done}... (경과 {format_hms(elapsed)})"
            )
            return
        text = f"{self._queue_position()}처리 중... (경과 {format_hms(elapsed)}"
        if self._progress_total and self._progress_current > 0 and elapsed > 1:
            speed = self._progress_current / elapsed  # 오디오 초 / 실제 초
            remaining_audio = max(0.0, self._progress_total - self._progress_current)
            if speed > 0:
                eta = remaining_audio / speed
                text += f" / 남은 시간 약 {format_hms(eta)} / {speed:.1f}배속"
        text += ")"
        self.status_label.setText(text)

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

    def _handle_message(self, obj: dict) -> None:
        msg_type = obj.get("type")
        if msg_type == "start":
            self.total_duration = obj.get("total")
            if self.total_duration:
                self._log(f"오디오 길이: {format_hms(self.total_duration)}")
        elif msg_type == "segment":
            start = format_hms(obj.get("start", 0))
            end = format_hms(obj.get("end", 0))
            text = obj.get("text", "")
            self._log(f"[{start} --> {end}] {text}")
        elif msg_type == "progress":
            current = obj.get("current", 0)
            total = obj.get("total") or self.total_duration
            self._progress_current = current
            self._progress_total = total
            if total:
                pct = max(0, min(100, int(current / total * 100)))
                self.progress_bar.setValue(pct)
        elif msg_type == "phase":
            self._phase = obj.get("label", "")
            self._progress_current, self._progress_total = 0.0, None
            self.progress_bar.setValue(0)
            self._log(f"{self._phase} 시작 (LLM 모델 로딩 — 최초 실행 시 다운로드로 시간이 걸릴 수 있습니다)")
        elif msg_type == "llm_progress":
            current, total = obj.get("current", 0), obj.get("total", 0)
            self._progress_current, self._progress_total = current, total
            if total:
                self.progress_bar.setValue(max(0, min(100, int(current / total * 100))))
        elif msg_type == "notice":
            self._log(obj.get("message", ""))
        elif msg_type == "error":
            self._log("[오류] " + obj.get("message", ""))
        elif msg_type == "done":
            self.progress_bar.setValue(100)
            self._log("요약 완료." if self._job == "summary" else "전사 완료.")
            files = obj.get("output_files", [])
            if self._job == "transcribe" and self.current_item is not None:
                self.current_item.setData(OUTPUT_ROLE, files)
            for f in files:
                self._log(f"저장됨: {f}")

    def _on_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        self._elapsed_timer.stop()
        item, self.current_item = self.current_item, None
        if item is None:
            return
        if self._job == "summary":
            # 요약은 큐와 별개: 성공·실패·취소 모두 항목을 '완료'로 되돌린다
            self._set_status(item, "done")
            if self._cancelled:
                self._log("취소됨.")
                self.status_label.setText("취소됨")
            elif exit_code == 0 and exit_status == QProcess.NormalExit:
                self.status_label.setText("요약 완료")
                self.open_folder_btn.setEnabled(True)
            else:
                self.status_label.setText("요약 실패")
                self._log("[오류] 요약에 실패했습니다.")
            self._cancelled = False
            self.cancel_btn.setEnabled(False)
            self._update_start_btn()
            return
        if self._cancelled:
            self._set_status(item, "pending")
            self._log("취소됨.")
            self.status_label.setText("취소됨")
            self.cancel_btn.setEnabled(False)
            self._update_start_btn()
            return
        if exit_code == 0 and exit_status == QProcess.NormalExit:
            self._set_status(item, "done")
            self.open_folder_btn.setEnabled(True)
        else:
            self._set_status(item, "failed")
            self._log("[오류] 이 파일의 전사에 실패했습니다. 다음 파일로 넘어갑니다.")
        self._start_next()

    def _finish_queue(self) -> None:
        self.cancel_btn.setEnabled(False)
        self._update_start_btn()
        statuses = [i.data(STATUS_ROLE) for i in self._queue_items()]
        done, failed = statuses.count("done"), statuses.count("failed")
        self.status_label.setText(f"완료 {done}개 / 실패 {failed}개")
        if failed:
            QMessageBox.warning(
                self, "일부 실패", f"완료 {done}개, 실패 {failed}개. 로그를 확인하세요."
            )
        else:
            QMessageBox.information(self, "완료", f"대기 큐의 전사가 모두 완료되었습니다. ({done}개)")

    def _on_process_error(self, error: QProcess.ProcessError) -> None:
        self._log("[오류] 프로세스를 실행할 수 없습니다.")
        # 시작 자체가 실패하면 finished 시그널이 오지 않으므로 직접 다음으로 넘긴다
        if error == QProcess.FailedToStart:
            self._on_finished(1, QProcess.CrashExit)

    def _on_open_folder(self) -> None:
        if self.output_dir is not None:
            subprocess.run(["open", str(self.output_dir)])

    def _log(self, text: str) -> None:
        self.log_view.appendPlainText(text)
