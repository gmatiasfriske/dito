import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dictado_app import ui_dispatch


class UiDispatcherTests(unittest.TestCase):
    def test_submit_is_deferred_until_drain(self):
        seen = []
        dispatcher = ui_dispatch.UiDispatcher()
        dispatcher.submit(seen.append, "a")
        self.assertEqual(seen, [])
        dispatcher.drain()
        self.assertEqual(seen, ["a"])

    def test_drain_runs_callbacks_in_order(self):
        seen = []
        dispatcher = ui_dispatch.UiDispatcher()
        dispatcher.submit(seen.append, 1)
        dispatcher.submit(seen.append, 2)
        dispatcher.drain()
        self.assertEqual(seen, [1, 2])

    def test_exception_is_logged_and_next_callback_runs(self):
        seen = []
        logs = []
        dispatcher = ui_dispatch.UiDispatcher(logger=logs.append)

        def fail():
            raise RuntimeError("boom")

        dispatcher.submit(fail)
        dispatcher.submit(seen.append, "depois")
        dispatcher.drain()
        self.assertEqual(seen, ["depois"])
        self.assertTrue(any("boom" in line for line in logs))

    def test_closed_dispatcher_ignores_submit(self):
        seen = []
        dispatcher = ui_dispatch.UiDispatcher()
        dispatcher.close()
        dispatcher.submit(seen.append, "x")
        dispatcher.drain()
        self.assertEqual(seen, [])

    def test_submit_from_worker_thread_is_thread_safe(self):
        seen = []
        dispatcher = ui_dispatch.UiDispatcher()
        workers = [
            threading.Thread(target=dispatcher.submit, args=(seen.append, i))
            for i in range(20)
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        dispatcher.drain()
        self.assertEqual(sorted(seen), list(range(20)))


if __name__ == "__main__":
    unittest.main()

