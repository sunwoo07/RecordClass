"""메인 창의 대기 큐, 워커 인자 구성, 메시지 처리 검사 (워커 프로세스는 실제로 띄우지 않음)."""
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QProcess

from tests import clear_settings, qt_app
from sttgui import main_window as mw
from sttgui.settings import Settings


class MainWindowTest(unittest.TestCase):
    def setUp(self) -> None:
        qt_app()
        clear_settings()
        # 실제 워커 실행과 모달 메시지 상자는 막는다
        patches = [
            mock.patch.object(QProcess, "start"),
            mock.patch.object(mw.QMessageBox, "information"),
            mock.patch.object(mw.QMessageBox, "warning"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.win = mw.MainWindow()
        self.addCleanup(self.win.deleteLater)

    def statuses(self) -> list[str]:
        return [i.data(mw.STATUS_ROLE) for i in self.win._queue_items()]

    def test_add_files_skips_active_duplicates(self) -> None:
        self.assertFalse(self.win.start_btn.isEnabled())
        self.win._add_files([Path("/a.mp3"), Path("/b.mp3"), Path("/a.mp3")])
        self.assertEqual(self.win.queue_list.count(), 2)
        self.assertTrue(self.win.start_btn.isEnabled())

    def test_worker_arguments_follow_settings(self) -> None:
        self.win.settings = Settings(
            model="m", language="en", formats=["txt", "md"], output_dir="/out",
            initial_prompt="-용어", no_condition_prev=True, dedupe=False, skip_silence=True,
            paragraph_gap=1.5, txt_timestamps=False,
        )
        self.win._add_files([Path("/x/lec.m4a")])
        self.win._on_start()
        args = self.win.process.arguments()
        self.assertTrue(args[0].endswith("transcribe_worker.py"))
        for expected in (["--audio", "/x/lec.m4a"], ["--model", "m"], ["--language", "en"],
                         ["--outdir", "/out"], ["--formats", "txt,md"]):
            i = args.index(expected[0])
            self.assertEqual(args[i:i + 2], expected)
        self.assertIn("--initial-prompt=-용어", args)
        self.assertIn("--no-condition-prev", args)
        self.assertNotIn("--dedupe", args)
        self.assertIn("--skip-silence", args)
        self.assertNotIn("--preprocess", args)
        self.assertIn("--paragraph-gap=1.5", args)
        self.assertIn("--no-txt-timestamps", args)

    def test_empty_output_dir_uses_audio_folder(self) -> None:
        self.win.settings = Settings(output_dir="")
        self.win._add_files([Path("/x/lec.m4a")])
        self.win._on_start()
        self.assertEqual(self.win.output_dir, Path("/x"))

    def test_queue_runs_in_order_and_records_failures(self) -> None:
        self.win._add_files([Path("/a.mp3"), Path("/b.mp3")])
        self.win._on_start()
        self.assertEqual(self.statuses(), ["running", "pending"])
        self.win._on_finished(0, QProcess.NormalExit)
        self.assertEqual(self.statuses(), ["done", "running"])
        self.win._on_finished(1, QProcess.NormalExit)
        self.assertEqual(self.statuses(), ["done", "failed"])
        mw.QMessageBox.warning.assert_called_once()
        self.assertIn("완료 1개 / 실패 1개", self.win.status_label.text())

    def test_cancel_returns_item_to_pending(self) -> None:
        self.win._add_files([Path("/a.mp3")])
        self.win._on_start()
        self.win._on_cancel()
        self.win._on_finished(9, QProcess.CrashExit)
        self.assertEqual(self.statuses(), ["pending"])
        self.assertTrue(self.win.start_btn.isEnabled())

    def test_remove_and_clear_finished(self) -> None:
        self.win._add_files([Path("/a.mp3"), Path("/b.mp3")])
        self.win._on_start()  # /a 실행 중
        self.win.queue_list.selectAll()
        self.win._on_remove_selected()  # 실행 중인 항목은 남는다
        self.assertEqual(self.statuses(), ["running"])
        self.win._on_finished(0, QProcess.NormalExit)
        self.win._on_clear_finished()
        self.assertEqual(self.win.queue_list.count(), 0)

    def test_handle_messages(self) -> None:
        self.win._handle_message({"type": "start", "total": 100})
        self.win._handle_message({"type": "progress", "current": 25, "total": 100})
        self.assertEqual(self.win.progress_bar.value(), 25)
        self.win._handle_message({"type": "segment", "start": 0, "end": 2, "text": "안녕"})
        self.win._handle_message({"type": "done", "output_files": ["/o/a.txt"]})
        self.assertEqual(self.win.progress_bar.value(), 100)
        log = self.win.log_view.toPlainText()
        self.assertIn("안녕", log)
        self.assertIn("저장됨: /o/a.txt", log)

    def test_preferences_saved_and_summary_updated(self) -> None:
        new = Settings(formats=["md"])
        with mock.patch.object(mw, "SettingsDialog") as dlg_cls:
            dlg_cls.Accepted = 1
            dlg_cls.return_value.exec.return_value = 1
            dlg_cls.return_value.settings.return_value = new
            self.win._on_preferences()
        self.assertEqual(Settings.load(), new)
        self.assertIn("MD", self.win.settings_label.text())


if __name__ == "__main__":
    unittest.main()
