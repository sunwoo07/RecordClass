"""
mlx-whisper를 사용해 오디오 파일을 텍스트로 변환하는 독립 실행 워커.

GUI(PySide6)와는 QProcess로 연결된다. 진행 상황과 결과는 stdout으로
한 줄에 하나씩 JSON을 출력해 전달하고(NDJSON), 사람이 읽는 로그나
mlx_whisper 자체의 verbose 출력은 절대 실제 stdout으로 새어나가지
않도록 가로챈다. 에러/경고는 stderr에 그대로 남긴다.

사용법:
    python transcribe_worker.py --audio PATH --model REPO_ID \
        --language ko|en|auto --outdir DIR --formats txt,srt,vtt,md \
        [--initial-prompt "전문 용어, ..."] [--no-condition-prev] [--dedupe] [--skip-silence] [--preprocess] \
        [--paragraph-gap 2.0] [--no-txt-timestamps] [--correct --llm-model REPO_ID]

    요약 모드 (전사 없이 기존 결과 파일을 요약해 <audio 이름>.summary.md로 저장):
    python transcribe_worker.py --summarize RESULT_FILE --audio PATH --outdir DIR --llm-model REPO_ID
"""
from __future__ import annotations

import argparse
import contextlib
import difflib
import io
import json
import os
import re
import subprocess
import sys
import traceback

import numpy as np
from pathlib import Path
from typing import Any, Callable, TextIO

# mlx_whisper 결과 세그먼트 (start/end/text 외에 id, tokens 등 여러 키가 있음)
Segment = dict[str, Any]

TIMESTAMP_RE = re.compile(r"^\[([\d:.]+)\s*-->\s*([\d:.]+)\]\s?(.*)$")
SAMPLE_RATE = 16000  # Whisper 입력 샘플레이트
# 저음 웅웅거림(80Hz 이하) 제거 → FFT 잡음 제거 → 음량 정규화
PREPROCESS_FILTER = "highpass=f=80,afftdn,loudnorm"
# 환각 의심 세그먼트 앞뒤 무음이 이 길이(초)보다 길면 건너뛴다
SILENCE_THRESHOLD = 2.0
# 공백으로 구분된 1~5단어 묶음이 4번 이상 연속 반복되는 패턴 ("아 아 아 아 ...")
REPEAT_RE = re.compile(r"(?<!\S)(\S+(?:\s+\S+){0,4}?)(?:\s+\1){3,}(?!\S)")


def emit(stream: TextIO, obj: dict[str, Any]) -> None:
    stream.write(json.dumps(obj, ensure_ascii=False) + "\n")
    stream.flush()


def parse_timestamp(s: str) -> float:
    parts = [float(p) for p in s.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    h, m, sec = parts
    return h * 3600 + m * 60 + sec


def format_srt_timestamp(seconds: float) -> str:
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def format_vtt_timestamp(seconds: float) -> str:
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def format_hms_timestamp(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def get_duration_seconds(path: str) -> float | None:
    try:
        out = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            stderr=subprocess.DEVNULL,
        )
        return float(out.strip())
    except Exception:
        return None


def load_preprocessed_audio(path: str) -> np.ndarray:
    """ffmpeg 필터를 거친 16kHz 모노 float32 파형을 돌려준다 (mlx_whisper.load_audio와 같은 형식)."""
    out = subprocess.run(
        ["ffmpeg", "-nostdin", "-threads", "0", "-i", path, "-af", PREPROCESS_FILTER,
         "-f", "s16le", "-ac", "1", "-acodec", "pcm_s16le", "-ar", str(SAMPLE_RATE), "-"],
        capture_output=True,
        check=True,
    ).stdout
    return np.frombuffer(out, np.int16).astype(np.float32) / 32768.0


class VerboseLineCapture(io.TextIOBase):
    """mlx_whisper의 verbose print()를 가로채 콜백으로 라인 단위 전달."""

    def __init__(self, on_line: Callable[[str], None]) -> None:
        super().__init__()
        self._on_line = on_line
        self._buf = ""

    def write(self, s: str) -> int:
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line:
                self._on_line(line)
        return len(s)

    def flush(self) -> None:
        pass


def group_paragraphs(segments: list[Segment], gap: float) -> list[tuple[float, str]]:
    """세그먼트 사이 무음(next.start - prev.end)이 gap초 이상이면 문단을 나눈다.

    출력 형식과 무관하게 [(문단 시작 시각, 공백으로 이은 텍스트), ...]를 돌려준다.
    빈 텍스트 세그먼트는 건너뛴다.
    """
    paragraphs: list[tuple[float, list[str]]] = []
    prev_end = None
    for seg in segments:
        text = seg["text"].strip()
        if not text:
            continue
        if prev_end is None or seg["start"] - prev_end >= gap:
            paragraphs.append((seg["start"], []))
        paragraphs[-1][1].append(text)
        prev_end = seg["end"]
    return [(start, " ".join(texts)) for start, texts in paragraphs]


def write_txt(segments: list[Segment], path: Path, gap: float = 2.0, timestamps: bool = True) -> None:
    paragraphs = group_paragraphs(segments, gap)
    with open(path, "w", encoding="utf-8") as f:
        f.write(
            "\n\n".join(
                (f"[{format_hms_timestamp(start)}] " if timestamps else "") + text
                for start, text in paragraphs
            )
            + "\n"
        )


def write_md(segments: list[Segment], path: Path, gap: float = 2.0) -> None:
    # 제목은 출력 파일명(= 오디오 파일명)에서, 문단마다 ## HH:MM:SS 제목을 붙인다
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# {path.stem}\n\n")
        for start, text in group_paragraphs(segments, gap):
            f.write(f"## {format_hms_timestamp(start)}\n\n{text}\n\n")


def write_srt(segments: list[Segment], path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, start=1):
            f.write(f"{i}\n")
            f.write(
                f"{format_srt_timestamp(seg['start'])} --> {format_srt_timestamp(seg['end'])}\n"
            )
            f.write(seg["text"].strip() + "\n\n")


def write_vtt(segments: list[Segment], path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write("WEBVTT\n\n")
        for seg in segments:
            f.write(
                f"{format_vtt_timestamp(seg['start'])} --> {format_vtt_timestamp(seg['end'])}\n"
            )
            f.write(seg["text"].strip() + "\n\n")


def collapse_repeats(text: str) -> str:
    """한 세그먼트 안에서 같은 단어(묶음)가 4번 이상 연달아 나오면 한 번만 남긴다."""
    return REPEAT_RE.sub(r"\1", text)


def dedupe_segments(segments: list[Segment]) -> list[Segment]:
    """세그먼트 안의 반복 루프를 접고, 연속으로 반복된 세그먼트(정규화한 텍스트가 같음)를 첫 세그먼트로 합친다.

    Whisper가 긴 녹음에서 같은 문장을 반복 출력하는 환각을 줄이기 위한 후처리.
    남긴 세그먼트의 end를 마지막 중복의 end로 늘려 타임스탬프가 끊기지 않게 하고,
    빈 텍스트 세그먼트는 버린다. 떨어져서 다시 나온 문장은 그대로 둔다.
    """
    kept: list[Segment] = []
    prev_key = None
    for seg in segments:
        text = collapse_repeats(seg["text"])
        key = " ".join(text.split()).lower()
        if not key:
            continue
        if key == prev_key:
            kept[-1]["end"] = seg["end"]
            continue
        kept.append({**seg, "text": text})
        prev_key = key
    return kept


WRITERS = {"txt": write_txt, "srt": write_srt, "vtt": write_vtt, "md": write_md}


def write_outputs(
    segments: list[Segment], outdir: Path, name: str, formats: list[str], gap: float, timestamps: bool
) -> list[str]:
    """선택한 형식마다 outdir/name.<형식> 파일을 쓰고 경로 목록을 돌려준다."""
    output_files = []
    for fmt in formats:
        writer = WRITERS.get(fmt)
        if writer is None:
            continue
        out_path = outdir / f"{name}.{fmt}"
        if fmt == "txt":
            writer(segments, out_path, gap=gap, timestamps=timestamps)
        elif fmt == "md":
            writer(segments, out_path, gap=gap)
        else:
            writer(segments, out_path)
        output_files.append(str(out_path))
    return output_files


# ---------- 로컬 LLM 후처리 (mlx-lm) ----------

# (system, user, max_tokens) -> 응답 텍스트
Generate = Callable[[str, str, int], str]
CountTokens = Callable[[str], int]

CORRECT_CHUNK_TOKENS = 1000  # 교정 한 번에 넣는 묶음 크기. 길면 줄 누락·요약이 잦아진다
CORRECT_CONTEXT_LINES = 3  # 앞 묶음에서 문맥으로만 보여 주는 줄 수
SUMMARY_CHUNK_TOKENS = 16000  # 이보다 긴 전사본은 나눠 정리한 뒤 합친다
SUMMARY_MAX_TOKENS = 4096
NUMBERED_RE = re.compile(r"^\s*(\d+)\s*\|\s?(.*)$")
THINK_RE = re.compile(r"<think>.*?</think>", re.S)

CORRECT_SYSTEM = """너는 한국어 강의 음성 인식(STT) 결과에서 잘못 인식된 단어만 고친다.
- 발음이 비슷해 잘못 적힌 단어(예: 방점식→방정식, 오아 함수→OR 함수)와 명백한 오타만 고친다.
- 확실하지 않으면 원문을 그대로 둔다. 추측해서 바꾸지 않는다.
- 단어를 추가·삭제하거나 순서를 바꾸지 않는다. 요약·의역하지 않고 구어체 말투도 그대로 둔다.
- 띄어쓰기는 바꾸지 않는다. 숫자·영문 뒤 조사는 붙여 쓴다(예: 0.1이, true가).
- 입력의 각 줄은 '번호|문장' 형식이다. 같은 번호, 같은 줄 수로 '번호|교정한 문장'만 출력하고 다른 말은 쓰지 않는다."""

SUMMARY_SYSTEM = """너는 한국어 대학 강의 전사본을 강의 노트로 정리한다.
수강생이 강의를 듣지 않아도 내용을 이해할 수 있게 Markdown으로 쓴다.
구성:
## 한 줄 요약
## 핵심 내용 (주제별 ### 소제목과 설명, 예시·수식 포함)
## 주요 용어
## 공지·과제·시험 관련 (언급이 없으면 이 절은 생략)
전사본에 없는 내용은 지어내지 않는다."""

SUMMARY_MERGE_SYSTEM = """다음은 한 강의를 여러 부분으로 나눠 정리한 노트들이다.
같은 구성(## 한 줄 요약 / ## 핵심 내용 / ## 주요 용어 / ## 공지·과제·시험 관련)의 노트 하나로 합친다.
중복은 합치고 내용은 빠뜨리지 않는다. 노트에 없는 내용은 지어내지 않는다."""


def chunk_by_tokens(texts: list[str], max_tokens: int, count: CountTokens) -> list[list[int]]:
    """texts를 순서대로 묶어 묶음마다 토큰 합이 max_tokens를 넘지 않게 나눈 인덱스 목록.

    한 줄이 max_tokens보다 길면 그 줄만으로 한 묶음이 된다.
    """
    chunks: list[list[int]] = []
    current: list[int] = []
    current_tokens = 0
    for i, text in enumerate(texts):
        n = count(text)
        if current and current_tokens + n > max_tokens:
            chunks.append(current)
            current, current_tokens = [], 0
        current.append(i)
        current_tokens += n
    if current:
        chunks.append(current)
    return chunks


def parse_numbered_lines(reply: str, expected: int) -> list[str] | None:
    """'번호|문장' 응답을 1..expected 순서의 문장 목록으로 바꾼다. 번호가 빠지거나 남으면 None."""
    found: dict[int, str] = {}
    for line in reply.splitlines():
        m = NUMBERED_RE.match(line)
        if m:
            found[int(m.group(1))] = m.group(2).strip()
    if set(found) != set(range(1, expected + 1)):
        return None
    return [found[i] for i in range(1, expected + 1)]


def keep_original_spacing(original: str, corrected: str) -> str:
    """교정문에서 원문과 글자가 같은 구간은 원문의 띄어쓰기를 되살린다.

    LLM이 '0.1이'를 '0.1 이'로 떼는 식으로 띄어쓰기를 망치는 경향이 있어서,
    공백을 뺀 글자끼리 비교해 실제로 바뀐 글자 구간만 교정문의 띄어쓰기를 따른다.
    """

    def split(text: str) -> tuple[str, set[int]]:
        # 공백을 뺀 글자열과, 뒤에 공백이 오는 글자의 위치
        chars: list[str] = []
        space_after: set[int] = set()
        for ch in text.strip():
            if ch.isspace():
                if chars:
                    space_after.add(len(chars) - 1)
            else:
                chars.append(ch)
        return "".join(chars), space_after

    old, old_spaces = split(original)
    new, new_spaces = split(corrected)
    out: list[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        chars, spaces, start = (old, old_spaces, i1) if tag == "equal" else (new, new_spaces, j1)
        end = i2 if tag == "equal" else j2
        for k in range(start, end):
            out.append(chars[k])
            if k in spaces:
                out.append(" ")
    return "".join(out).strip()


def correct_segments(
    segments: list[Segment],
    generate: Generate,
    count: CountTokens,
    glossary: str = "",
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[list[Segment], int]:
    """세그먼트 텍스트를 묶음 단위로 LLM 교정한다. 타임스탬프는 그대로 둔다.

    응답 줄 수가 맞지 않는 묶음은 원문을 유지하고, 빈 줄로 돌아온 문장도 원문을 쓴다.
    (교정한 세그먼트, 원문을 유지한 묶음 수)를 돌려준다.
    """
    texts = [seg["text"].strip() for seg in segments]
    fixed = list(texts)
    system = CORRECT_SYSTEM + (f"\n- 강의 용어(표기 참고): {glossary}" if glossary else "")
    chunks = chunk_by_tokens(texts, CORRECT_CHUNK_TOKENS, count)
    failed = 0
    for n, idx in enumerate(chunks, start=1):
        # 앞 문맥은 이미 교정된 문장으로 보여 줘 용어 표기를 이어 가게 한다
        context = fixed[max(0, idx[0] - CORRECT_CONTEXT_LINES) : idx[0]]
        user = ""
        if context:
            user += "[앞 문맥 — 참고만 하고 출력하지 말 것]\n" + "\n".join(context) + "\n\n"
        user += "[교정할 줄]\n" + "\n".join(f"{k}|{texts[i]}" for k, i in enumerate(idx, start=1))
        # 줄 번호와 여유분까지 출력 길이를 넉넉히 잡는다
        max_tokens = sum(count(texts[i]) for i in idx) * 2 + 100
        lines = parse_numbered_lines(generate(system, user, max_tokens), len(idx))
        if lines is None:
            failed += 1
        else:
            for i, line in zip(idx, lines):
                if line:
                    fixed[i] = keep_original_spacing(texts[i], line)
        if on_progress:
            on_progress(n, len(chunks))
    return [{**seg, "text": text} for seg, text in zip(segments, fixed)], failed


def summarize_text(
    text: str,
    generate: Generate,
    count: CountTokens,
    on_progress: Callable[[int, int], None] | None = None,
) -> str:
    """전사본을 Markdown 강의 노트로 정리한다. 길면 나눠 정리한 뒤 하나로 합친다."""
    lines = [line for line in text.splitlines() if line.strip()]
    chunks = chunk_by_tokens(lines, SUMMARY_CHUNK_TOKENS, count)
    steps = len(chunks) + (1 if len(chunks) > 1 else 0)
    parts = []
    for n, idx in enumerate(chunks, start=1):
        parts.append(generate(SUMMARY_SYSTEM, "\n".join(lines[i] for i in idx), SUMMARY_MAX_TOKENS))
        if on_progress:
            on_progress(n, steps)
    if len(parts) == 1:
        return parts[0]
    merged = generate(SUMMARY_MERGE_SYSTEM, "\n\n---\n\n".join(parts), SUMMARY_MAX_TOKENS)
    if on_progress:
        on_progress(steps, steps)
    return merged


def read_transcript(path: Path) -> str:
    """TXT/MD/SRT/VTT 결과 파일에서 본문 줄만 뽑는다 (번호·시각 줄, 머리글 제외)."""
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line == "WEBVTT" or line.isdigit() or "-->" in line or line.startswith("#"):
            continue
        lines.append(line)
    return "\n".join(lines)


def release_whisper() -> None:
    """전사가 끝난 whisper 모델을 메모리에서 내려 LLM이 쓸 자리를 비운다."""
    import mlx.core as mx
    from mlx_whisper.transcribe import ModelHolder

    ModelHolder.model = None
    ModelHolder.model_path = None
    mx.clear_cache()


def load_llm(repo: str) -> tuple[Generate, CountTokens]:
    """mlx-lm 모델을 불러와 (generate, count_tokens) 함수 쌍을 돌려준다. 최초 실행 시 다운로드한다."""
    from mlx_lm import generate as lm_generate
    from mlx_lm import load

    model, tokenizer = load(repo)

    def generate(system: str, user: str, max_tokens: int) -> str:
        prompt = tokenizer.apply_chat_template(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            add_generation_prompt=True,
            enable_thinking=False,  # Qwen3.5 등은 기본값이 사고 모드
        )
        reply = lm_generate(model, tokenizer, prompt, max_tokens=max_tokens)
        return THINK_RE.sub("", reply).strip()

    return generate, lambda s: len(tokenizer.encode(s))


def run_summary(args: argparse.Namespace, out: TextIO) -> int:
    """요약 모드: 결과 파일 하나를 읽어 <audio 이름>.summary.md로 저장한다."""
    text = read_transcript(Path(args.summarize))
    if not text:
        emit(out, {"type": "error", "message": f"요약할 내용이 없습니다: {args.summarize}"})
        return 1
    emit(out, {"type": "phase", "label": "요약"})

    def on_progress(current: int, total: int) -> None:
        emit(out, {"type": "llm_progress", "current": current, "total": total})

    try:
        # mlx-lm의 print가 NDJSON stdout에 섞이지 않게 stderr로 돌린다
        with contextlib.redirect_stdout(sys.stderr):
            generate, count = load_llm(args.llm_model)
            summary = summarize_text(text, generate, count, on_progress)
    except Exception as exc:  # noqa: BLE001
        emit(out, {"type": "error", "message": f"{exc}\n{traceback.format_exc()}"})
        return 1
    out_path = Path(args.outdir) / f"{Path(args.audio).stem}.summary.md"
    out_path.write_text(summary + "\n", encoding="utf-8")
    emit(out, {"type": "done", "text": summary, "output_files": [str(out_path)]})
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", required=True)
    parser.add_argument("--model", default="", help="whisper 모델 (요약 모드에서는 불필요)")
    parser.add_argument("--language", default="auto")
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--formats", default="txt,srt,vtt")
    parser.add_argument(
        "--initial-prompt", default="", help="전문 용어 힌트 (비어 있으면 사용 안 함)"
    )
    parser.add_argument(
        "--no-condition-prev",
        action="store_true",
        help="condition_on_previous_text=False (반복 환각 감소)",
    )
    parser.add_argument("--dedupe", action="store_true", help="연속 중복 세그먼트 제거")
    parser.add_argument(
        "--skip-silence", action="store_true", help="무음 구간 환각 건너뛰기 (단어 타임스탬프 사용)"
    )
    parser.add_argument(
        "--preprocess", action="store_true", help="ffmpeg 잡음 제거·음량 정규화 후 전사"
    )
    parser.add_argument(
        "--paragraph-gap", type=float, default=2.0, help="TXT/MD 문단을 나누는 무음 간격(초)"
    )
    parser.add_argument(
        "--no-txt-timestamps", action="store_true", help="TXT 문단 앞 [HH:MM:SS] 생략"
    )
    parser.add_argument(
        "--correct", action="store_true", help="전사 후 LLM으로 원문 교정 (<이름>.corrected.<형식> 추가 저장)"
    )
    parser.add_argument("--llm-model", default="", help="교정·요약에 쓸 mlx-lm 모델")
    parser.add_argument("--summarize", default="", help="전사 없이 이 결과 파일을 요약")
    args = parser.parse_args()
    if (args.correct or args.summarize) and not args.llm_model:
        parser.error("--correct/--summarize에는 --llm-model이 필요합니다")
    if not args.summarize and not args.model:
        parser.error("--model이 필요합니다")

    real_stdout = sys.stdout
    if args.summarize:
        return run_summary(args, real_stdout)
    total_duration = get_duration_seconds(args.audio)
    emit(real_stdout, {"type": "start", "total": total_duration})

    def on_verbose_line(line: str) -> None:
        m = TIMESTAMP_RE.match(line)
        if not m:
            return
        start = parse_timestamp(m.group(1))
        end = parse_timestamp(m.group(2))
        text = m.group(3)
        emit(real_stdout, {"type": "segment", "start": start, "end": end, "text": text})
        if total_duration:
            emit(real_stdout, {"type": "progress", "current": end, "total": total_duration})

    try:
        import mlx_whisper
    except ImportError:
        emit(
            real_stdout,
            {
                "type": "error",
                "message": "mlx_whisper 모듈을 찾을 수 없습니다. `pip install -r requirements.txt`를 실행했는지 확인하세요.",
            },
        )
        return 1

    language = None if args.language == "auto" else args.language

    sys.stdout = VerboseLineCapture(on_verbose_line)
    try:
        audio = load_preprocessed_audio(args.audio) if args.preprocess else args.audio
        result = mlx_whisper.transcribe(
            audio,
            path_or_hf_repo=args.model,
            verbose=True,
            language=language,
            initial_prompt=args.initial_prompt.strip() or None,
            # 플래그가 없으면 라이브러리 기본값(True)
            **({"condition_on_previous_text": False} if args.no_condition_prev else {}),
            # hallucination_silence_threshold는 word_timestamps=True일 때만 동작
            **(
                {"word_timestamps": True, "hallucination_silence_threshold": SILENCE_THRESHOLD}
                if args.skip_silence
                else {}
            ),
        )
    except Exception as exc:  # noqa: BLE001
        sys.stdout = real_stdout
        emit(real_stdout, {"type": "error", "message": f"{exc}\n{traceback.format_exc()}"})
        return 1
    finally:
        sys.stdout = real_stdout

    segments = result.get("segments", [])
    text = result.get("text", "")
    if args.dedupe:
        segments = dedupe_segments(segments)
        text = "".join(seg["text"] for seg in segments)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    base = Path(args.audio).stem
    formats = [f.strip() for f in args.formats.split(",") if f.strip()]
    gap, timestamps = args.paragraph_gap, not args.no_txt_timestamps
    output_files = write_outputs(segments, outdir, base, formats, gap, timestamps)

    if args.correct:
        # 원본 결과는 이미 저장됨 — 교정이 실패해도 원본은 남기고 정상 종료한다
        emit(real_stdout, {"type": "phase", "label": "교정"})

        def on_progress(current: int, total: int) -> None:
            emit(real_stdout, {"type": "llm_progress", "current": current, "total": total})

        try:
            with contextlib.redirect_stdout(sys.stderr):
                release_whisper()
                generate, count = load_llm(args.llm_model)
                corrected, failed = correct_segments(
                    segments, generate, count, args.initial_prompt.strip(), on_progress
                )
            output_files += write_outputs(
                corrected, outdir, f"{base}.corrected", formats, gap, timestamps
            )
            if failed:
                emit(
                    real_stdout,
                    {"type": "notice", "message": f"교정 응답이 어긋난 {failed}개 묶음은 원문을 유지했습니다."},
                )
        except Exception as exc:  # noqa: BLE001
            emit(
                real_stdout,
                {"type": "error", "message": f"교정 실패 (원본 결과는 저장됨): {exc}\n{traceback.format_exc()}"},
            )

    emit(
        real_stdout,
        {
            "type": "done",
            "language": result.get("language"),
            "text": text,
            "output_files": output_files,
        },
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
