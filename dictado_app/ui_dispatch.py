"""Thread-safe bridge for UI callbacks.

Tkinter may only be touched from the thread that created the root.  Background
threads (model loading, transcription, RPC, hotkey) submit work here; the main
thread drains the queue from a Tk `after` callback.
"""
from __future__ import annotations

import queue
from typing import Any, Callable


class UiDispatcher:
    def __init__(self, logger: Callable[[str], None] | None = None) -> None:
        self._queue: queue.Queue[tuple[Callable[..., Any], tuple[Any, ...]]] = (
            queue.Queue())
        self._logger = logger
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def submit(self, fn: Callable[..., Any], *args: Any) -> None:
        if self._closed:
            return
        self._queue.put((fn, args))

    def drain(self) -> None:
        while True:
            try:
                fn, args = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                fn(*args)
            except Exception as exc:
                if self._logger is not None:
                    self._logger(f"ui: erro em callback: {exc!r}")

    def close(self) -> None:
        self._closed = True
