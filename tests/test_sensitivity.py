import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audio_fx
import widget_ui


class SensitivityTests(unittest.TestCase):
    def test_default_factor_is_one(self):
        self.assertEqual(audio_fx.sensitivity_factor(4), 1.0)

    def test_higher_level_is_more_sensitive(self):
        s4, v4 = audio_fx.effective_thresholds(0.006, 0.02, 4)
        s7, v7 = audio_fx.effective_thresholds(0.006, 0.02, 7)
        self.assertLess(s7, s4)
        self.assertLess(v7, v4)
        self.assertGreaterEqual(v7, s7 * 1.5)

    def test_gate_sensitivity_is_negative_at_high_level(self):
        self.assertEqual(audio_fx.gate_sensitivity_db(4), 0.0)
        self.assertEqual(audio_fx.gate_sensitivity_db(7), -6.0)
        self.assertEqual(audio_fx.gate_sensitivity_db(1), 6.0)

    def test_wheel_changes_one_level(self):
        self.assertEqual(audio_fx.next_sensitivity_level(4, 120), 5)
        self.assertEqual(audio_fx.next_sensitivity_level(4, -120), 3)


class SliderStateTests(unittest.TestCase):
    def test_set_sensitivity_stores_level_and_visibility(self):
        w = widget_ui.NativeWidget.__new__(widget_ui.NativeWidget)
        w.sens_level = 4
        w.sens_levels = 7
        w.sens_visible = False
        w._dirty = False
        widget_ui.NativeWidget.set_sensitivity(w, 6, 7, True)
        self.assertEqual(w.sens_level, 6)
        self.assertEqual(w.sens_levels, 7)
        self.assertTrue(w.sens_visible)
        self.assertTrue(w._dirty)


if __name__ == "__main__":
    unittest.main()
