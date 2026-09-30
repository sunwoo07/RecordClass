"""transcribe_worker의 순수 함수(후처리·타임스탬프·출력 작성기) 검사."""
import io
import tempfile
import unittest
from pathlib import Path

from sttgui.transcribe_worker import (
    VerboseLineCapture,
    dedupe_segments,
    format_hms_timestamp,
    format_srt_timestamp,
    format_vtt_timestamp,
    group_paragraphs,
    parse_timestamp,
    write_md,
    write_srt,
    write_txt,
    write_vtt,
)


def seg(start, end, text):
    return {"start": start, "end": end, "text": text}


def render(writer, segments, name="강의1", ext="txt", **kwargs) -> str:
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / f"{name}.{ext}"
        writer(segments, path, **kwargs)
        return path.read_text(encoding="utf-8")


class DedupeTest(unittest.TestCase):
    def test_consecutive_dupes_merged(self):
        out = dedupe_segments([seg(0, 1, "안녕"), seg(1, 2, "안녕"), seg(2, 3, "안녕"), seg(3, 4, "다음")])
        self.assertEqual(out, [seg(0, 3, "안녕"), seg(3, 4, "다음")])

    def test_non_consecutive_kept(self):
        out = dedupe_segments([seg(0, 1, "A"), seg(1, 2, "B"), seg(2, 3, "A")])
        self.assertEqual([s["text"] for s in out], ["A", "B", "A"])

    def test_normalization(self):
        out = dedupe_segments([seg(0, 1, " Hello  World"), seg(1, 2, "hello world ")])
        self.assertEqual(out, [seg(0, 2, " Hello  World")])

    def test_empty_dropped_and_input_untouched(self):
        segs = [seg(0, 1, "A"), seg(1, 2, "  "), seg(2, 3, "A"), seg(3, 4, "")]
        self.assertEqual(dedupe_segments(segs), [seg(0, 3, "A")])
        self.assertEqual(segs[0]["end"], 1)


class ParagraphTest(unittest.TestCase):
    def test_split_on_gap(self):
        # 무음이 정확히 gap이면 분리
        self.assertEqual(group_paragraphs([seg(0, 1, "A"), seg(3, 4, "B")], 2.0), [(0, "A"), (3, "B")])

    def test_no_split_below_gap(self):
        self.assertEqual(group_paragraphs([seg(0, 1, "A"), seg(2.9, 4, "B")], 2.0), [(0, "A B")])

    def test_text_join(self):
        out = group_paragraphs([seg(5, 6, " 안녕 "), seg(6, 7, "  "), seg(7, 8, "하세요")], 2.0)
        self.assertEqual(out, [(5, "안녕 하세요")])

    def test_empty(self):
        self.assertEqual(group_paragraphs([], 2.0), [])


class TimestampTest(unittest.TestCase):
    def test_hms(self):
        self.assertEqual(format_hms_timestamp(0), "00:00:00")
        self.assertEqual(format_hms_timestamp(750.9), "00:12:30")
        self.assertEqual(format_hms_timestamp(3725), "01:02:05")

    def test_srt_vtt(self):
        self.assertEqual(format_srt_timestamp(3725.5), "01:02:05,500")
        self.assertEqual(format_vtt_timestamp(3725.5), "01:02:05.500")
        # 반올림이 초 경계를 넘어도 999ms가 1000ms로 새지 않아야 함
        self.assertEqual(format_srt_timestamp(59.9996), "00:01:00,000")

    def test_parse(self):
        self.assertEqual(parse_timestamp("01:02.500"), 62.5)
        self.assertEqual(parse_timestamp("01:00:01.000"), 3601.0)


class VerboseCaptureTest(unittest.TestCase):
    def test_lines_split_across_writes(self):
        lines = []
        cap = VerboseLineCapture(lines.append)
        cap.write("[00:00.000 --> 00:02")
        cap.write(".000] 안녕\n\nnext")
        self.assertEqual(lines, ["[00:00.000 --> 00:02.000] 안녕"])
        cap.write("\n")
        self.assertEqual(lines[-1], "next")


class WriterTest(unittest.TestCase):
    SEGS = [seg(0, 1, " A "), seg(1.5, 2, "B"), seg(3725, 3726, "C")]

    def test_txt_paragraphs_with_timestamps(self):
        out = render(write_txt, self.SEGS, gap=2.0)
        self.assertEqual(out, "[00:00:00] A B\n\n[01:02:05] C\n")

    def test_txt_without_timestamps(self):
        out = render(write_txt, self.SEGS, gap=2.0, timestamps=False)
        self.assertEqual(out, "A B\n\nC\n")

    def test_md(self):
        out = render(write_md, self.SEGS, ext="md", gap=2.0)
        self.assertEqual(out, "# 강의1\n\n## 00:00:00\n\nA B\n\n## 01:02:05\n\nC\n\n")

    def test_md_empty(self):
        self.assertEqual(render(write_md, [], ext="md"), "# 강의1\n\n")

    def test_srt(self):
        out = render(write_srt, self.SEGS[:2], ext="srt")
        self.assertEqual(
            out,
            "1\n00:00:00,000 --> 00:00:01,000\nA\n\n2\n00:00:01,500 --> 00:00:02,000\nB\n\n",
        )

    def test_vtt(self):
        out = render(write_vtt, self.SEGS[:1], ext="vtt")
        self.assertEqual(out, "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nA\n\n")


if __name__ == "__main__":
    unittest.main()
