"""
mlx-whisper를 사용해 오디오 파일을 텍스트로 변환하는 독립 실행 워커.

GUI(PySide6)와는 QProcess로 연결된다. 진행 상황과 결과는 stdout으로
한 줄에 하나씩 JSON을 출력해 전달하고(NDJSON), 사람이 읽는 로그나
mlx_whisper 자체의 verbose 출력은 절대 실제 stdout으로 새어나가지
않도록 가로챈다. 에러/경고는 stderr에 그대로 남긴다.

사용법:
    python transcribe_worker.py --audio PATH --model REPO_ID \
        --language ko|en|auto --outdir DIR --formats txt,srt,vtt
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

TIMESTAMP_RE = re.compile(r"^\[([\d:.]+)\s*-->\s*([\d:.]+)\]\s?(.*)$")


def emit(stream, obj: dict) -> None:
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

    def __init__(self, on_line):
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


def write_txt(segments, path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for seg in segments:
            f.write(seg["text"].strip() + "\n")


def write_srt(segments, path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, start=1):
            f.write(f"{i}\n")
            f.write(
                f"{format_srt_timestamp(seg['start'])} --> {format_srt_timestamp(seg['end'])}\n"
            )
            f.write(seg["text"].strip() + "\n\n")


def write_vtt(segments, path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write("WEBVTT\n\n")
        for seg in segments:
            f.write(
                f"{format_vtt_timestamp(seg['start'])} --> {format_vtt_timestamp(seg['end'])}\n"
            )
            f.write(seg["text"].strip() + "\n\n")


WRITERS = {"txt": write_txt, "srt": write_srt, "vtt": write_vtt}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--language", default="auto")
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--formats", default="txt,srt,vtt")
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
        )
    except Exception as exc:  # noqa: BLE001
        sys.stdout = real_stdout
        emit(real_stdout, {"type": "error", "message": f"{exc}\n{traceback.format_exc()}"})
        return 1
    finally:
        sys.stdout = real_stdout

    segments = result.get("segments", [])
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    base = Path(args.audio).stem
    output_files = []
    for fmt in [f.strip() for f in args.formats.split(",") if f.strip()]:
        writer = WRITERS.get(fmt)
        if writer is None:
            continue
        out_path = outdir / f"{base}.{fmt}"
        writer(segments, out_path)
        output_files.append(str(out_path))

    emit(
        real_stdout,
        {
            "type": "done",
            "language": result.get("language"),
            "text": result.get("text", ""),
            "output_files": output_files,
        },
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
