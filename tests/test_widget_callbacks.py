import queue
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import widget_ui


class NativeWidgetCallbackTests(unittest.TestCase):
    def _bare_widget(self):
        widget = widget_ui.NativeWidget.__new__(widget_ui.NativeWidget)
        widget._callbacks = queue.Queue()
        widget._dead = False
        return widget

    def test_call_defers_callback_until_drain(self):
        seen = []
        widget = self._bare_widget()
        widget._call(lambda: seen.append("ok"))
        self.assertEqual(seen, [])
        widget._drain_callbacks()
        self.assertEqual(seen, ["ok"])

    def test_call_from_worker_thread_is_thread_safe(self):
        seen = []
        widget = self._bare_widget()
        worker = threading.Thread(
            target=widget._call, args=(lambda: seen.append("ok"),))
        worker.start()
        worker.join()
        widget._drain_callbacks()
        self.assertEqual(seen, ["ok"])

    def test_dead_widget_ignores_callbacks(self):
        seen = []
        widget = self._bare_widget()
        widget._dead = True
        widget._call(lambda: seen.append("ok"))
        widget._drain_callbacks()
        self.assertEqual(seen, [])

    def test_global_wheel_over_content_queues_sensitivity(self):
        seen = []
        widget = self._bare_widget()
        widget._hwnd = 123
        widget.on_sensitivity = seen.append
        widget.rect = lambda: (100, 100, 58, 58)
        widget._hit_local = lambda x, y: "content"
        self.assertTrue(widget._handle_global_wheel(120, 120, 120))
        self.assertEqual(seen, [])
        widget._drain_callbacks()
        self.assertEqual(seen, [120])

    def test_global_wheel_outside_content_is_ignored(self):
        seen = []
        widget = self._bare_widget()
        widget._hwnd = 123
        widget.on_sensitivity = seen.append
        widget.rect = lambda: (100, 100, 58, 58)
        widget._hit_local = lambda x, y: "content"
        self.assertFalse(widget._handle_global_wheel(500, 500, 120))
        widget._drain_callbacks()
        self.assertEqual(seen, [])


if __name__ == "__main__":
    unittest.main()
