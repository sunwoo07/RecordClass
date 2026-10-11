"""
사용자 설정(환경설정 창, ⌘,)과 QSettings 저장/불러오기.

새 설정을 추가하려면:
  1. Settings에 기본값이 있는 필드를 추가한다 (load/save는 필드를 자동으로 순회).
  2. SettingsDialog에 위젯을 만들고, __init__에서 값을 채우고 settings()에서 읽는다.
  3. MainWindow._start_next에서 워커 CLI 인자로 넘긴다.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output"

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

FORMAT_OPTIONS = [("TXT", "txt"), ("SRT", "srt"), ("VTT", "vtt"), ("Markdown", "md")]
DEFAULT_FORMATS = ["txt", "srt", "vtt"]  # Markdown은 기본 꺼짐


@dataclass
class Settings:
    model: str = MODEL_OPTIONS[0][1]
    language: str = "ko"
    formats: list[str] = field(default_factory=lambda: list(DEFAULT_FORMATS))
    output_dir: str = str(DEFAULT_OUTPUT_DIR)
    initial_prompt: str = ""  # 전문 용어 힌트 (mlx_whisper initial_prompt)
    no_condition_prev: bool = True  # condition_on_previous_text=False (반복 환각 감소)
    dedupe: bool = True  # 연속 중복 세그먼트 제거 후처리
    skip_silence: bool = True  # 무음 구간 환각 건너뛰기 (hallucination_silence_threshold)
    preprocess: bool = False  # ffmpeg 잡음 제거·음량 정규화 후 전사
    paragraph_gap: float = 2.0  # TXT/MD 문단을 나누는 무음 간격(초)
    txt_timestamps: bool = True  # TXT 문단 앞에 [HH:MM:SS] 표시

    @classmethod
    def load(cls) -> Settings:
        # 키가 없거나 타입이 맞지 않으면 기본값을 쓴다
        qs = QSettings()
        s = cls()
        for f in fields(cls):
            default = getattr(s, f.name)
            try:
                value = qs.value(f.name, default, type=type(default))
            except (TypeError, ValueError):
                value = default
            setattr(s, f.name, default if value is None else value)
        return s

    def save(self) -> None:
        qs = QSettings()
        for f in fields(self):
            qs.setValue(f.name, getattr(self, f.name))
        qs.sync()

    def summary(self) -> str:
        """메인 창에 보여줄 한 줄 요약."""
        model = next((l for l, r in MODEL_OPTIONS if r == self.model), self.model)
        lang = next((l for l, c in LANGUAGE_OPTIONS if c == self.language), self.language)
        fmts = ", ".join(f.upper() for f in self.formats)
        outdir = self.output_dir.replace(str(Path.home()), "~", 1) or "원본 파일 폴더"
        return f"모델: {model.split(' (')[0]} · {lang} · {fmts} · 저장: {outdir} — ⌘, 로 변경"


class SettingsDialog(QDialog):
    """Settings를 편집하는 환경설정 창. 섹션(QGroupBox + QFormLayout) 단위로 추가한다."""

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("환경설정")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)

        # 전사
        stt_group = QGroupBox("전사")
        stt_form = QFormLayout(stt_group)
        self.model_combo = QComboBox()
        for label, repo in MODEL_OPTIONS:
            self.model_combo.addItem(label, repo)
        self.model_combo.setCurrentIndex(max(0, self.model_combo.findData(settings.model)))
        stt_form.addRow("모델:", self.model_combo)
        self.lang_combo = QComboBox()
        for label, code in LANGUAGE_OPTIONS:
            self.lang_combo.addItem(label, code)
        self.lang_combo.setCurrentIndex(max(0, self.lang_combo.findData(settings.language)))
        stt_form.addRow("언어:", self.lang_combo)
        self.prompt_edit = QPlainTextEdit(settings.initial_prompt)
        self.prompt_edit.setPlaceholderText(
            "예: 미적분, 라그랑주 승수, 고유벡터 — 강의에 나오는 과목명·전문 용어를 쉼표로 입력"
        )
        self.prompt_edit.setToolTip("입력한 용어를 모델에 미리 알려 주어 전문 용어 인식률을 높입니다.")
        self.prompt_edit.setFixedHeight(self.prompt_edit.fontMetrics().lineSpacing() * 3 + 12)
        stt_form.addRow("전문 용어 힌트:", self.prompt_edit)
        self.no_prev_check = QCheckBox("이전 문맥 참조 끄기 (반복 오류 감소)")
        self.no_prev_check.setChecked(settings.no_condition_prev)
        self.no_prev_check.setToolTip(
            "앞 구간의 결과를 다음 구간의 힌트로 쓰지 않아, 긴 녹음에서 같은 문장이 반복되는 오류를 줄입니다.\n"
            "대신 구간 사이의 표기·어투 일관성이 약간 떨어질 수 있습니다."
        )
        stt_form.addRow("", self.no_prev_check)
        self.dedupe_check = QCheckBox("반복 문장 제거 후처리")
        self.dedupe_check.setChecked(settings.dedupe)
        self.dedupe_check.setToolTip(
            "연속으로 똑같이 반복된 문장을 하나로 합쳐 저장합니다. (실시간 미리보기에는 적용되지 않음)"
        )
        stt_form.addRow("", self.dedupe_check)
        self.skip_silence_check = QCheckBox("무음 구간 환각 건너뛰기")
        self.skip_silence_check.setChecked(settings.skip_silence)
        self.skip_silence_check.setToolTip(
            "말이 없는 구간에서 '아 아 아…'처럼 지어낸 글자가 나오는 것을 줄입니다.\n"
            "단어 단위 시각을 계산하므로 전사가 조금 느려집니다."
        )
        stt_form.addRow("", self.skip_silence_check)
        self.preprocess_check = QCheckBox("음성 전처리 (잡음 제거·음량 정규화)")
        self.preprocess_check.setChecked(settings.preprocess)
        self.preprocess_check.setToolTip(
            "ffmpeg로 저음 웅웅거림과 배경 잡음을 줄이고 음량을 고르게 맞춘 뒤 전사합니다.\n"
            "작게 말하거나 잡음이 많은 녹음에 도움이 되지만, 깨끗한 녹음에서는 효과가 없을 수 있습니다."
        )
        stt_form.addRow("", self.preprocess_check)
        layout.addWidget(stt_group)

        # 출력
        out_group = QGroupBox("출력")
        out_form = QFormLayout(out_group)
        fmt_row = QHBoxLayout()
        self.format_checks: dict[str, QCheckBox] = {}
        for label, fmt in FORMAT_OPTIONS:
            check = QCheckBox(label)
            check.setChecked(fmt in settings.formats)
            self.format_checks[fmt] = check
            fmt_row.addWidget(check)
        fmt_row.addStretch()
        out_form.addRow("출력 형식:", fmt_row)
        outdir_row = QHBoxLayout()
        self.outdir_edit = QLineEdit(settings.output_dir)
        self.outdir_edit.setReadOnly(True)
        outdir_btn = QPushButton("폴더 선택")
        outdir_btn.clicked.connect(self._on_choose_outdir)
        outdir_row.addWidget(self.outdir_edit, stretch=1)
        outdir_row.addWidget(outdir_btn)
        out_form.addRow("저장 위치:", outdir_row)
        self.gap_spin = QDoubleSpinBox()
        self.gap_spin.setRange(0.5, 30.0)
        self.gap_spin.setSingleStep(0.5)
        self.gap_spin.setDecimals(1)
        self.gap_spin.setSuffix(" 초")
        self.gap_spin.setValue(settings.paragraph_gap)
        self.gap_spin.setToolTip("말이 이 시간 이상 끊기면 TXT·Markdown에서 새 문단으로 나눕니다.")
        out_form.addRow("문단 구분 간격 (TXT/MD):", self.gap_spin)
        self.txt_ts_check = QCheckBox("TXT 문단에 타임스탬프 표시")
        self.txt_ts_check.setChecked(settings.txt_timestamps)
        out_form.addRow("", self.txt_ts_check)
        layout.addWidget(out_group)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_choose_outdir(self) -> None:
        start_dir = self.outdir_edit.text() or str(Path.home())
        dir_str = QFileDialog.getExistingDirectory(self, "저장 폴더 선택", start_dir)
        if dir_str:
            self.outdir_edit.setText(dir_str)

    def accept(self) -> None:
        if not self.settings().formats:
            QMessageBox.warning(self, "출력 형식 없음", "최소 하나의 출력 형식을 선택하세요.")
            return
        super().accept()

    def settings(self) -> Settings:
        """현재 위젯 값으로 새 Settings를 만든다."""
        return Settings(
            model=self.model_combo.currentData(),
            language=self.lang_combo.currentData(),
            formats=[f for f, c in self.format_checks.items() if c.isChecked()],
            output_dir=self.outdir_edit.text(),
            initial_prompt=self.prompt_edit.toPlainText().strip(),
            no_condition_prev=self.no_prev_check.isChecked(),
            dedupe=self.dedupe_check.isChecked(),
            skip_silence=self.skip_silence_check.isChecked(),
            preprocess=self.preprocess_check.isChecked(),
            paragraph_gap=self.gap_spin.value(),
            txt_timestamps=self.txt_ts_check.isChecked(),
        )
