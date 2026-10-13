"""
사용자 설정(메인 창의 '설정' 탭)과 QSettings 저장/불러오기.

새 설정을 추가하려면:
  1. Settings에 기본값이 있는 필드를 추가한다 (load/save는 필드를 자동으로 순회).
  2. SettingsPanel에 행을 만들고, __init__에서 값을 채우고 settings()에서 읽는다.
     값이 바뀌면 changed 시그널을 내보낸다 (메인 창이 바로 저장).
  3. MainWindow._start_next에서 워커 CLI 인자로 넘긴다.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
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

# 교정·요약용 mlx-lm 모델 (콤보박스에서 직접 입력도 가능)
LLM_MODEL_OPTIONS = ["mlx-community/Qwen3.5-9B-MLX-4bit"]

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
    correct: bool = False  # 전사 후 로컬 LLM으로 원문 교정 (.corrected 파일 추가 저장)
    llm_model: str = LLM_MODEL_OPTIONS[0]  # 교정·요약에 쓸 mlx-lm 모델

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
        correct = " · LLM 교정" if self.correct else ""
        return f"{model.split(' (')[0]} · {lang} · {fmts}{correct}\n저장: {outdir}"


class _Card(QFrame):
    """시스템 설정처럼 제목·설명과 컨트롤이 한 줄씩 놓이고 hairline으로 나뉘는 카드."""

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("role", "card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 2, 16, 2)
        self._layout.setSpacing(0)

    def add_row(self, title: str, control: QWidget, desc: str = "", stacked: bool = False) -> None:
        if self._layout.count():
            line = QFrame()
            line.setProperty("role", "separator")
            line.setFixedHeight(1)
            self._layout.addWidget(line)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(QLabel(title))
        if desc:
            desc_label = QLabel(desc)
            desc_label.setProperty("role", "muted")
            desc_label.setWordWrap(True)
            text.addWidget(desc_label)
        row = QWidget()
        if stacked:  # 넓은 입력칸은 제목 아래에 둔다
            layout = QVBoxLayout(row)
            layout.addLayout(text)
            layout.addWidget(control)
        else:
            layout = QHBoxLayout(row)
            layout.addLayout(text, stretch=1)
            layout.addSpacing(16)
            layout.addWidget(control, alignment=Qt.AlignVCenter)
        layout.setContentsMargins(0, 10, 0, 10)
        self._layout.addWidget(row)


def _switch(checked: bool) -> QCheckBox:
    check = QCheckBox()
    check.setProperty("role", "switch")
    check.setChecked(checked)
    check.setCursor(Qt.PointingHandCursor)
    return check


def _display_dir(path: str) -> str:
    return path.replace(str(Path.home()), "~", 1) if path else "원본 파일과 같은 폴더"


class SettingsPanel(QScrollArea):
    """메인 창 '설정' 탭. 값이 바뀌면 changed 시그널을 내보내고 메인 창이 바로 저장한다."""

    changed = Signal()

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        body.setProperty("role", "page")
        outer = QHBoxLayout(body)  # 넓은 창에서도 설명이 한눈에 읽히도록 폭을 제한하고 가운데 둔다
        outer.setContentsMargins(4, 0, 12, 24)
        column = QWidget()
        column.setMaximumWidth(720)
        outer.addWidget(column)
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        def section(title: str) -> _Card:
            label = QLabel(title)
            label.setProperty("role", "section")
            layout.addWidget(label)
            card = _Card()
            layout.addWidget(card)
            return card

        # 전사
        stt = section("전사")
        self.model_combo = QComboBox()
        for label, repo in MODEL_OPTIONS:
            self.model_combo.addItem(label, repo)
        self.model_combo.setCurrentIndex(max(0, self.model_combo.findData(settings.model)))
        self.model_combo.setMinimumWidth(220)
        stt.add_row("Whisper 모델", self.model_combo, "큰 모델일수록 정확하지만 느립니다.")
        self.lang_combo = QComboBox()
        for label, code in LANGUAGE_OPTIONS:
            self.lang_combo.addItem(label, code)
        self.lang_combo.setCurrentIndex(max(0, self.lang_combo.findData(settings.language)))
        self.lang_combo.setMinimumWidth(220)
        stt.add_row("강의 언어", self.lang_combo)
        self.prompt_edit = QPlainTextEdit(settings.initial_prompt)
        self.prompt_edit.setPlaceholderText("예: 미적분, 라그랑주 승수, 고유벡터")
        self.prompt_edit.setFixedHeight(self.prompt_edit.fontMetrics().lineSpacing() * 3 + 16)
        stt.add_row(
            "전문 용어 힌트",
            self.prompt_edit,
            "강의에 나오는 과목명·전문 용어를 쉼표로 적어 두면 인식률이 올라갑니다. LLM 교정의 용어집으로도 쓰입니다.",
            stacked=True,
        )

        # 인식 품질
        quality = section("인식 품질")
        self.no_prev_check = _switch(settings.no_condition_prev)
        quality.add_row(
            "이전 문맥 참조 끄기", self.no_prev_check,
            "긴 녹음에서 같은 문장이 끝없이 반복되는 오류를 줄입니다. 구간 사이 어투 일관성은 약간 떨어질 수 있어요.",
        )
        self.dedupe_check = _switch(settings.dedupe)
        quality.add_row(
            "반복 문장 제거", self.dedupe_check,
            "연속으로 똑같이 반복된 문장을 하나로 합쳐 저장합니다. 실시간 미리보기에는 적용되지 않아요.",
        )
        self.skip_silence_check = _switch(settings.skip_silence)
        quality.add_row(
            "무음 구간 환각 건너뛰기", self.skip_silence_check,
            "말이 없는 구간에서 지어낸 글자가 나오는 것을 줄입니다. 전사가 조금 느려집니다.",
        )
        self.preprocess_check = _switch(settings.preprocess)
        quality.add_row(
            "음성 전처리", self.preprocess_check,
            "잡음을 줄이고 음량을 고르게 맞춘 뒤 전사합니다. 작게 말하거나 시끄러운 녹음에 도움이 됩니다.",
        )

        # 출력
        out = section("저장")
        fmt_row = QWidget()
        fmt_layout = QHBoxLayout(fmt_row)
        fmt_layout.setContentsMargins(0, 0, 0, 0)
        fmt_layout.setSpacing(6)
        self.format_checks: dict[str, QPushButton] = {}
        for label, fmt in FORMAT_OPTIONS:
            chip = QPushButton(label)
            chip.setProperty("role", "chip")
            chip.setCheckable(True)
            chip.setChecked(fmt in settings.formats)
            chip.setCursor(Qt.PointingHandCursor)
            chip.toggled.connect(self._on_format_toggled)
            self.format_checks[fmt] = chip
            fmt_layout.addWidget(chip)
        fmt_layout.addStretch()
        out.add_row("파일 형식", fmt_row, "TXT·Markdown은 문단으로, SRT·VTT는 자막 형식으로 저장됩니다.", stacked=True)
        self._output_dir = settings.output_dir
        outdir_row = QWidget()
        outdir_layout = QHBoxLayout(outdir_row)
        outdir_layout.setContentsMargins(0, 0, 0, 0)
        self.outdir_label = QLabel(_display_dir(self._output_dir))
        self.outdir_label.setProperty("role", "muted")
        self.outdir_label.setToolTip(self._output_dir)
        outdir_btn = QPushButton("변경…")
        outdir_btn.clicked.connect(self._on_choose_outdir)
        outdir_layout.addWidget(self.outdir_label)
        outdir_layout.addWidget(outdir_btn)
        out.add_row("저장 위치", outdir_row)
        self.gap_spin = QDoubleSpinBox()
        self.gap_spin.setRange(0.5, 30.0)
        self.gap_spin.setSingleStep(0.5)
        self.gap_spin.setDecimals(1)
        self.gap_spin.setSuffix(" 초")
        self.gap_spin.setValue(settings.paragraph_gap)
        self.gap_spin.setMinimumWidth(90)
        out.add_row("문단 나누기", self.gap_spin, "말이 이 시간 이상 끊기면 TXT·Markdown에서 새 문단을 시작합니다.")
        self.txt_ts_check = _switch(settings.txt_timestamps)
        out.add_row("TXT 문단에 시각 표시", self.txt_ts_check, "문단 앞에 [00:12:34]처럼 강의 시각을 붙입니다.")

        # LLM
        llm = section("LLM 후처리")
        self.correct_check = _switch(settings.correct)
        llm.add_row(
            "전사 후 원문 교정", self.correct_check,
            "로컬 LLM이 잘못 인식된 단어·맞춤법·띄어쓰기를 고쳐 '.corrected' 파일로 따로 저장합니다. "
            "첫 실행 시 모델(약 6GB)을 내려받고, 강의 1시간당 수 분~10여 분이 더 걸립니다.",
        )
        self.llm_combo = QComboBox()
        self.llm_combo.setEditable(True)
        self.llm_combo.addItems(LLM_MODEL_OPTIONS)
        self.llm_combo.setCurrentText(settings.llm_model)
        llm.add_row("LLM 모델", self.llm_combo, "교정과 요약에 쓰는 Hugging Face mlx-lm 모델 이름입니다.", stacked=True)

        layout.addStretch()
        self.setWidget(body)

        for combo in (self.model_combo, self.lang_combo):
            combo.currentIndexChanged.connect(self.changed)
        self.llm_combo.currentTextChanged.connect(self.changed)
        self.prompt_edit.textChanged.connect(self.changed)
        self.gap_spin.valueChanged.connect(self.changed)
        for check in (self.no_prev_check, self.dedupe_check, self.skip_silence_check,
                      self.preprocess_check, self.txt_ts_check, self.correct_check):
            check.toggled.connect(self.changed)

    def _on_format_toggled(self, checked: bool) -> None:
        # 형식이 하나도 없으면 저장할 게 없으므로 마지막 하나는 끌 수 없다
        if not checked and not any(c.isChecked() for c in self.format_checks.values()):
            chip = self.sender()
            chip.blockSignals(True)
            chip.setChecked(True)
            chip.blockSignals(False)
            return
        self.changed.emit()

    def _on_choose_outdir(self) -> None:
        start_dir = self._output_dir or str(Path.home())
        dir_str = QFileDialog.getExistingDirectory(self, "저장 폴더 선택", start_dir)
        if dir_str:
            self._output_dir = dir_str
            self.outdir_label.setText(_display_dir(dir_str))
            self.outdir_label.setToolTip(dir_str)
            self.changed.emit()

    def settings(self) -> Settings:
        """현재 위젯 값으로 새 Settings를 만든다."""
        return Settings(
            model=self.model_combo.currentData(),
            language=self.lang_combo.currentData(),
            formats=[f for f, c in self.format_checks.items() if c.isChecked()],
            output_dir=self._output_dir,
            initial_prompt=self.prompt_edit.toPlainText().strip(),
            no_condition_prev=self.no_prev_check.isChecked(),
            dedupe=self.dedupe_check.isChecked(),
            skip_silence=self.skip_silence_check.isChecked(),
            preprocess=self.preprocess_check.isChecked(),
            paragraph_gap=self.gap_spin.value(),
            txt_timestamps=self.txt_ts_check.isChecked(),
            correct=self.correct_check.isChecked(),
            llm_model=self.llm_combo.currentText().strip() or LLM_MODEL_OPTIONS[0],
        )
