import sys
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import widget_ui


class TargetWidthTests(unittest.TestCase):
    def test_processing_is_circular(self):
        w = widget_ui.NativeWidget.__new__(widget_ui.NativeWidget)
        w.state = widget_ui.STATE_PROCESSING
        w.status = ""
        self.assertEqual(w._target_width(), widget_ui.IDLE_W)

    def test_status_is_expanded(self):
        w = widget_ui.NativeWidget.__new__(widget_ui.NativeWidget)
        w.state = widget_ui.STATE_READY
        w.status = "texto"
        self.assertEqual(w._target_width(), widget_ui.EXPANDED_W)


class RingTests(unittest.TestCase):
    def test_processing_draws_orange_pixels(self):
        r = widget_ui.Renderer(0.8)
        img = r.render(state=widget_ui.STATE_PROCESSING,
                       width=widget_ui.IDLE_W, progress=50)
        self.assertIsInstance(img, Image.Image)
        pixels = img.convert("RGBA").get_flattened_data()
        orange = sum(1 for r_, g_, b_, a_ in pixels
                     if r_ > 150 and g_ > 60 and b_ < 80 and a_ > 0)
        self.assertGreater(orange, 10)

    def test_recording_narrow_width_with_slider_does_not_raise(self):
        r = widget_ui.Renderer(0.8)
        img = r.render(state=widget_ui.STATE_RECORDING,
                       width=86, sens_visible=True)
        self.assertIsInstance(img, Image.Image)

    def test_ready_hover_does_not_expand(self):
        w = widget_ui.NativeWidget.__new__(widget_ui.NativeWidget)
        w.state = widget_ui.STATE_READY
        w.hover = 1.0
        w.status = ""
        self.assertEqual(w._target_width(), widget_ui.IDLE_W)

    def test_ready_circle_shows_sensitivity_dots(self):
        r = widget_ui.Renderer(0.8)

        def green_count(img):
            pixels = img.convert("RGBA").get_flattened_data()
            return sum(1 for r_, g_, b_, a_ in pixels
                       if g_ > 90 and r_ < 120 and b_ < 100 and a_ > 0)

        low = r.render(state=widget_ui.STATE_READY,
                       width=widget_ui.IDLE_W,
                       sens_level=1, sens_visible=True)
        high = r.render(state=widget_ui.STATE_READY,
                        width=widget_ui.IDLE_W,
                        sens_level=7, sens_visible=True)
        self.assertGreater(green_count(high), green_count(low) + 5)


if __name__ == "__main__":
    unittest.main()
