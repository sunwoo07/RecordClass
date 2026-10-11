"""
mlx-whisper를 사용해 오디오 파일을 텍스트로 변환하는 독립 실행 워커.

GUI(PySide6)와는 QProcess로 연결된다. 진행 상황과 결과는 stdout으로
한 줄에 하나씩 JSON을 출력해 전달하고(NDJSON), 사람이 읽는 로그나
mlx_whisper 자체의 verbose 출력은 절대 실제 stdout으로 새어나가지
않도록 가로챈다. 에러/경고는 stderr에 그대로 남긴다.

사용법:
    python transcribe_worker.py --audio PATH --model REPO_ID \
        --language ko|en|auto --outdir DIR --formats txt,srt,vtt,md \
        [--initial-prompt "전문 용어, ..."] [--no-condition-prev] [--dedupe] [--skip-silence] \
        [--paragraph-gap 2.0] [--no-txt-timestamps]
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any, Callable, TextIO

# mlx_whisper 결과 세그먼트 (start/end/text 외에 id, tokens 등 여러 키가 있음)
Segment = dict[str, Any]

TIMESTAMP_RE = re.compile(r"^\[([\d:.]+)\s*-->\s*([\d:.]+)\]\s?(.*)$")
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", required=True)
    parser.add_argument("--model", required=True)
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
        "--paragraph-gap", type=float, default=2.0, help="TXT/MD 문단을 나누는 무음 간격(초)"
    )
    parser.add_argument(
        "--no-txt-timestamps", action="store_true", help="TXT 문단 앞 [HH:MM:SS] 생략"
    )
    args = parser.parse_args()

    real_stdout = sys.stdout
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
        result = mlx_whisper.transcribe(
            args.audio,
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
    output_files = []
    for fmt in [f.strip() for f in args.formats.split(",") if f.strip()]:
        writer = WRITERS.get(fmt)
        if writer is None:
            continue
        out_path = outdir / f"{base}.{fmt}"
        if fmt == "txt":
            writer(
                segments, out_path, gap=args.paragraph_gap, timestamps=not args.no_txt_timestamps
            )
        elif fmt == "md":
            writer(segments, out_path, gap=args.paragraph_gap)
        else:
            writer(segments, out_path)
        output_files.append(str(out_path))

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
