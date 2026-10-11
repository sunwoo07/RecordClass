"""샘플 녹음으로 워커를 실제 실행하는 종단 간 검사.

Apple Silicon + mlx-whisper + 캐시된 small 모델이 있을 때만 실행하고, 없으면 건너뛴다.
"""
import importlib.util
import json
import platform
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "samples" / "lecture_sample.mp3"
WORKER = ROOT / "sttgui" / "transcribe_worker.py"
MODEL = "mlx-community/whisper-small-mlx"
MODEL_CACHE = Path.home() / ".cache/huggingface/hub/models--mlx-community--whisper-small-mlx"


@unittest.skipUnless(
    platform.machine() == "arm64"
    and importlib.util.find_spec("mlx_whisper")
    and MODEL_CACHE.is_dir(),
    "Apple Silicon, mlx-whisper, 캐시된 small 모델 필요",
)
class WorkerE2ETest(unittest.TestCase):
    def test_transcribe_sample_all_formats(self) -> None:
        with tempfile.TemporaryDirectory() as out:
            proc = subprocess.run(
                [sys.executable, str(WORKER), "--audio", str(SAMPLE), "--model", MODEL,
                 "--language", "ko", "--outdir", out, "--formats", "txt,srt,vtt,md",
                 "--initial-prompt=데이터베이스, 정규화", "--no-condition-prev", "--dedupe", "--skip-silence",
                 "--paragraph-gap=0.5"],
                capture_output=True, text=True, timeout=300,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
            # stdout은 전부 NDJSON이어야 한다 (mlx_whisper verbose 출력이 새면 안 됨)
            events = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
            types = [e["type"] for e in events]
            self.assertEqual(types[0], "start")
            self.assertEqual(types[-1], "done")
            self.assertIn("segment", types)
            self.assertIn("progress", types)
            done = events[-1]
            self.assertTrue(done["text"].strip())
            self.assertEqual(len(done["output_files"]), 4)

            txt = Path(out, "lecture_sample.txt").read_text(encoding="utf-8")
            md = Path(out, "lecture_sample.md").read_text(encoding="utf-8")
            srt = Path(out, "lecture_sample.srt").read_text(encoding="utf-8")
            vtt = Path(out, "lecture_sample.vtt").read_text(encoding="utf-8")
            self.assertRegex(txt, r"^\[00:00:00\] \S")
            self.assertTrue(md.startswith("# lecture_sample\n\n## 00:00:00\n\n"))
            self.assertRegex(srt, r"^1\n00:00:\d\d,\d{3} --> ")
            self.assertTrue(vtt.startswith("WEBVTT\n\n"))

    def test_missing_audio_reports_error(self) -> None:
        with tempfile.TemporaryDirectory() as out:
            proc = subprocess.run(
                [sys.executable, str(WORKER), "--audio", str(Path(out, "nope.mp3")),
                 "--model", MODEL, "--outdir", out],
                capture_output=True, text=True, timeout=120,
            )
            self.assertNotEqual(proc.returncode, 0)
            last = json.loads(proc.stdout.splitlines()[-1])
            self.assertEqual(last["type"], "error")


if __name__ == "__main__":
    unittest.main()
