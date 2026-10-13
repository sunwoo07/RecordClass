"""Settings 저장/불러오기와 환경설정 창 검사."""
import unittest
from unittest import mock

from PySide6.QtCore import QSettings

from tests import clear_settings, qt_app
from sttgui import settings as settings_mod
from sttgui.settings import DEFAULT_FORMATS, Settings, SettingsDialog


class SettingsTest(unittest.TestCase):
    def setUp(self) -> None:
        qt_app()
        clear_settings()

    def test_defaults_when_empty(self) -> None:
        self.assertEqual(Settings.load(), Settings())
        self.assertEqual(Settings().formats, DEFAULT_FORMATS)

    def test_round_trip_all_fields(self) -> None:
        s = Settings(
            model="mlx-community/whisper-small-mlx",
            language="en",
            formats=["md"],
            output_dir="/tmp/out",
            initial_prompt="미적분,\n고유벡터",
            no_condition_prev=False,
            dedupe=False,
            skip_silence=False,
            preprocess=True,
            paragraph_gap=3.5,
            txt_timestamps=False,
            correct=True,
            llm_model="mlx-community/other-llm",
        )
        s.save()
        self.assertEqual(Settings.load(), s)

    def test_bad_values_fall_back_to_default(self) -> None:
        qs = QSettings()
        qs.setValue("paragraph_gap", "not-a-number")
        qs.setValue("dedupe", "false")  # 문자열로 저장된 bool
        qs.sync()
        loaded = Settings.load()
        self.assertIsInstance(loaded.paragraph_gap, float)
        self.assertIs(loaded.dedupe, False)

    def test_summary(self) -> None:
        text = Settings(formats=["txt", "md"]).summary()
        self.assertIn("large-v3-turbo", text)
        self.assertIn("TXT, MD", text)
        self.assertIn("⌘,", text)
        self.assertNotIn("LLM 교정", text)
        self.assertIn("LLM 교정", Settings(correct=True).summary())


class SettingsDialogTest(unittest.TestCase):
    def setUp(self) -> None:
        qt_app()

    def test_dialog_reflects_and_returns_settings(self) -> None:
        s = Settings(language="en", formats=["srt", "md"], initial_prompt="용어", paragraph_gap=4.0,
                     correct=True, llm_model="직접/입력한-모델")
        self.assertEqual(SettingsDialog(s).settings(), s)

    def test_dialog_edits(self) -> None:
        dlg = SettingsDialog(Settings())
        dlg.dedupe_check.setChecked(False)
        dlg.skip_silence_check.setChecked(False)
        dlg.preprocess_check.setChecked(True)
        dlg.format_checks["md"].setChecked(True)
        dlg.gap_spin.setValue(1.5)
        dlg.correct_check.setChecked(True)
        dlg.llm_combo.setCurrentText("  ")  # 비우면 기본 모델
        out = dlg.settings()
        self.assertTrue(out.correct)
        self.assertEqual(out.llm_model, Settings().llm_model)
        self.assertFalse(out.dedupe)
        self.assertFalse(out.skip_silence)
        self.assertTrue(out.preprocess)
        self.assertIn("md", out.formats)
        self.assertEqual(out.paragraph_gap, 1.5)

    def test_accept_refuses_no_format(self) -> None:
        dlg = SettingsDialog(Settings())
        for check in dlg.format_checks.values():
            check.setChecked(False)
        with mock.patch.object(settings_mod.QMessageBox, "warning") as warn:
            dlg.accept()
        warn.assert_called_once()
        self.assertNotEqual(dlg.result(), SettingsDialog.Accepted)


if __name__ == "__main__":
    unittest.main()
