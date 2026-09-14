from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import QProcess, Qt, QTimer
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

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

MODEL_OPTIONS = [
    ("large-v3-turbo (권장, 빠름)", "mlx-community/whisper-large-v3-turbo"),
    ("large-v3 (최고 정확도, 느림)", "mlx-community/whisper-large-v3-mlx"),
    ("medium (중간)", "mlx-community/whisper-medium-mlx"),
    ("small (가장 빠름, 정확도 낮음)", "mlx-community/whisper-small-mlx"),
]

LANGUAGE_OPTIONS = [
    ("한국어", "ko"),
    ("자동 감지", "auto"),
    ("영어", "en"),
]


def format_hms(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("강의 녹음 STT (mlx-whisper)")
        self.resize(760, 620)
        self.setAcceptDrops(True)

        self.audio_path: Path | None = None
        self.process: QProcess | None = None
        self.total_duration: float | None = None
        self.output_dir: Path | None = None
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)
        self._start_time: float = 0.0

        self._build_ui()

    # ---------- UI ----------
    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)

        # 파일 선택
        file_group = QGroupBox("1. 강의 녹음 파일")
        file_layout = QHBoxLayout(file_group)
        self.file_edit = QLineEdit()
        self.file_edit.setReadOnly(True)
        self.file_edit.setPlaceholderText("파일을 드래그하거나 '찾아보기'를 클릭하세요")
        browse_btn = QPushButton("찾아보기")
        browse_btn.clicked.connect(self._on_browse)
        file_layout.addWidget(self.file_edit)
        file_layout.addWidget(browse_btn)
        layout.addWidget(file_group)

        # 옵션
        options_group = QGroupBox("2. 옵션")
        options_layout = QHBoxLayout(options_group)

        options_layout.addWidget(QLabel("모델:"))
        self.model_combo = QComboBox()
        for label, _ in MODEL_OPTIONS:
            self.model_combo.addItem(label)
        options_layout.addWidget(self.model_combo)

        options_layout.addWidget(QLabel("언어:"))
        self.lang_combo = QComboBox()
        for label, _ in LANGUAGE_OPTIONS:
            self.lang_combo.addItem(label)
        options_layout.addWidget(self.lang_combo)

        options_layout.addWidget(QLabel("출력 형식:"))
        self.txt_check = QPushButton("TXT")
        self.srt_check = QPushButton("SRT")
        self.vtt_check = QPushButton("VTT")
        for btn in (self.txt_check, self.srt_check, self.vtt_check):
            btn.setCheckable(True)
            btn.setChecked(True)
            options_layout.addWidget(btn)

        layout.addWidget(options_group)

        # 출력 폴더
        outdir_group = QGroupBox("3. 저장 위치")
        outdir_layout = QHBoxLayout(outdir_group)
        self.outdir_edit = QLineEdit()
        self.outdir_edit.setReadOnly(True)
        outdir_btn = QPushButton("폴더 선택")
        outdir_btn.clicked.connect(self._on_choose_outdir)
        outdir_layout.addWidget(self.outdir_edit)
        outdir_layout.addWidget(outdir_btn)
        layout.addWidget(outdir_group)

        # 컨트롤
        control_layout = QHBoxLayout()
        self.start_btn = QPushButton("전사 시작")
        self.start_btn.clicked.connect(self._on_start)
        self.start_btn.setEnabled(False)
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
        progress_layout.addWidget(self.progress_bar, stretch=1)
        progress_layout.addWidget(self.status_label)
        layout.addLayout(progress_layout)

        # 로그 / 미리보기
        layout.addWidget(QLabel("실시간 결과 미리보기:"))
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

    # ---------- 파일 선택 / 드래그앤드롭 ----------
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        if not urls:
            return
        path = Path(urls[0].toLocalFile())
        if path.suffix.lower() not in AUDIO_EXTENSIONS:
            QMessageBox.warning(self, "지원하지 않는 형식", f"{path.suffix} 형식은 지원하지 않습니다.")
            return
        self._set_audio_path(path)

    def _on_browse(self) -> None:
        filter_str = "오디오/비디오 파일 (*" + " *".join(sorted(AUDIO_EXTENSIONS)) + ")"
        path_str, _ = QFileDialog.getOpenFileName(self, "강의 녹음 파일 선택", "", filter_str)
        if path_str:
            self._set_audio_path(Path(path_str))

    def _set_audio_path(self, path: Path) -> None:
        self.audio_path = path
        self.file_edit.setText(str(path))
        if not self.outdir_edit.text():
            self.output_dir = path.parent
            self.outdir_edit.setText(str(self.output_dir))
        self.start_btn.setEnabled(True)

    def _on_choose_outdir(self) -> None:
        start_dir = str(self.output_dir) if self.output_dir else str(Path.home())
        dir_str = QFileDialog.getExistingDirectory(self, "저장 폴더 선택", start_dir)
        if dir_str:
            self.output_dir = Path(dir_str)
            self.outdir_edit.setText(dir_str)

    # ---------- 전사 실행 ----------
    def _selected_formats(self) -> list[str]:
        formats = []
        if self.txt_check.isChecked():
            formats.append("txt")
        if self.srt_check.isChecked():
            formats.append("srt")
        if self.vtt_check.isChecked():
            formats.append("vtt")
        return formats

    def _on_start(self) -> None:
        if self.audio_path is None:
            return
        formats = self._selected_formats()
        if not formats:
            QMessageBox.warning(self, "출력 형식 없음", "최소 하나의 출력 형식을 선택하세요.")
            return
        if self.output_dir is None:
            self.output_dir = self.audio_path.parent

        model_repo = MODEL_OPTIONS[self.model_combo.currentIndex()][1]
        language = LANGUAGE_OPTIONS[self.lang_combo.currentIndex()][1]

        self.log_view.clear()
        self.progress_bar.setValue(0)
        self.total_duration = None
        self.status_label.setText("모델 로딩 중... (최초 실행 시 다운로드로 시간이 걸릴 수 있습니다)")
        self._log(f"파일: {self.audio_path}")
        self._log(f"모델: {model_repo} / 언어: {language} / 형식: {', '.join(formats)}")

        worker_script = str(Path(__file__).parent / "transcribe_worker.py")
        self.process = QProcess(self)
        self.process.setProgram(sys.executable)
        self.process.setArguments(
            [
                worker_script,
                "--audio",
                str(self.audio_path),
                "--model",
                model_repo,
                "--language",
                language,
                "--outdir",
                str(self.output_dir),
                "--formats",
                ",".join(formats),
            ]
        )
        self.process.readyReadStandardOutput.connect(self._on_stdout)
        self.process.readyReadStandardError.connect(self._on_stderr)
        self.process.finished.connect(self._on_finished)
        self.process.errorOccurred.connect(self._on_process_error)

        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.open_folder_btn.setEnabled(False)
        self._start_time = time.monotonic()
        self._elapsed_timer.start()

        self.process.start()

    def _on_cancel(self) -> None:
        if self.process is not None and self.process.state() != QProcess.NotRunning:
            self.process.kill()
        self.status_label.setText("취소됨")
        self._elapsed_timer.stop()
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)

    def _tick_elapsed(self) -> None:
        elapsed = time.monotonic() - self._start_time
        self.status_label.setText(f"처리 중... (경과 {format_hms(elapsed)})")

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
            if total:
                pct = max(0, min(100, int(current / total * 100)))
                self.progress_bar.setValue(pct)
        elif msg_type == "error":
            self._log("[오류] " + obj.get("message", ""))
        elif msg_type == "done":
            self.progress_bar.setValue(100)
            self._log("전사 완료.")
            for f in obj.get("output_files", []):
                self._log(f"저장됨: {f}")

    def _on_finished(self, exit_code: int, _exit_status) -> None:
        self._elapsed_timer.stop()
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        if exit_code == 0:
            self.status_label.setText("완료")
            self.open_folder_btn.setEnabled(True)
            QMessageBox.information(self, "완료", "전사가 완료되었습니다.")
        else:
            self.status_label.setText("실패")
            QMessageBox.critical(self, "실패", "전사 중 오류가 발생했습니다. 로그를 확인하세요.")

    def _on_process_error(self, _error) -> None:
        self._log("[오류] 프로세스를 실행할 수 없습니다.")

    def _on_open_folder(self) -> None:
        if self.output_dir is not None:
            subprocess.run(["open", str(self.output_dir)])

    def _log(self, text: str) -> None:
        self.log_view.appendPlainText(text)
