from __future__ import annotations

import logging
from collections.abc import Callable
from threading import Lock

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


LOGGER = logging.getLogger(__name__)


class _TaskSignals(QObject):
    result = Signal(str, object)
    failed = Signal(str, object)
    finished = Signal(str)


class _ServiceTask(QRunnable):
    def __init__(self, key: str, operation: Callable[[], object]) -> None:
        super().__init__()
        self.key = key
        self.operation = operation
        self.signals = _TaskSignals()
        self._state_lock = Lock()
        self._started = False
        self._cancelled = False
        self.setAutoDelete(True)

    def cancel(self) -> None:
        with self._state_lock:
            self._cancelled = True

    def has_started(self) -> bool:
        with self._state_lock:
            return self._started

    def run(self) -> None:
        with self._state_lock:
            if self._cancelled:
                skipped = True
            else:
                self._started = True
                skipped = False
        if skipped:
            self.signals.finished.emit(self.key)
            return
        try:
            result = self.operation()
        except Exception as exc:
            LOGGER.exception("Background operation failed: %s", self.key)
            self.signals.failed.emit(self.key, exc)
        else:
            self.signals.result.emit(self.key, result)
        finally:
            self.signals.finished.emit(self.key)


class OperationController(QObject):
    """Bounded background executor for UI-facing application service calls."""

    operation_started = Signal(str)
    operation_finished = Signal(str)
    operation_failed = Signal(str, object)

    def __init__(self, parent: QObject | None = None, max_threads: int = 4) -> None:
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(max(2, min(int(max_threads), 8)))
        self._active: set[str] = set()
        self._callbacks: dict[
            str,
            tuple[
                Callable[[object], None] | None,
                Callable[[Exception], None] | None,
            ],
        ] = {}
        self._tasks: dict[str, _ServiceTask] = {}
        self._suppressed: set[str] = set()
        self._state_lock = Lock()
        self._accepting = True

    def submit(
        self,
        key: str,
        operation: Callable[[], object],
        on_result: Callable[[object], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> bool:
        with self._state_lock:
            if not self._accepting or key in self._active:
                return False
            self._active.add(key)
            self._callbacks[key] = (on_result, on_error)
        task = _ServiceTask(key, operation)
        with self._state_lock:
            self._tasks[key] = task
        task.signals.result.connect(self._on_result)
        task.signals.failed.connect(self._on_failed)
        task.signals.finished.connect(self._on_finished)
        try:
            self._pool.start(task)
        except RuntimeError:
            LOGGER.exception("Could not queue background operation: %s", key)
            with self._state_lock:
                self._active.discard(key)
                self._callbacks.pop(key, None)
                self._tasks.pop(key, None)
            return False
        self.operation_started.emit(key)
        return True

    def is_running(self, key: str) -> bool:
        with self._state_lock:
            return key in self._active

    def stop_accepting(self) -> None:
        with self._state_lock:
            self._accepting = False

    def cancel_pending(self, discard_callbacks: bool = True) -> None:
        with self._state_lock:
            tasks = list(self._tasks.items())
            if discard_callbacks:
                self._suppressed.update(key for key, _task in tasks)
            for _key, task in tasks:
                task.cancel()
        self._pool.clear()

        # QThreadPool.clear() drops queued runnables without emitting signals.
        # Remove their keys here so a canceled operation cannot block that key
        # forever or retain UI callbacks.
        finished: list[str] = []
        with self._state_lock:
            for key, task in tasks:
                if task.has_started():
                    continue
                self._active.discard(key)
                self._callbacks.pop(key, None)
                self._tasks.pop(key, None)
                self._suppressed.discard(key)
                finished.append(key)
        for key in finished:
            self.operation_finished.emit(key)

    def shutdown(self, wait_ms: int = 1000) -> None:
        self.stop_accepting()
        self.cancel_pending(discard_callbacks=True)
        self._pool.waitForDone(max(0, int(wait_ms)))

    @Slot(str, object)
    def _on_result(self, key: str, result: object) -> None:
        with self._state_lock:
            callback = (
                None
                if key in self._suppressed
                else self._callbacks.get(key, (None, None))[0]
            )
        if callback is not None and not self._invoke_callback(key, callback, result):
            self.operation_failed.emit(
                key,
                RuntimeError("Background result callback failed."),
            )

    @Slot(str, object)
    def _on_failed(self, key: str, error: Exception) -> None:
        with self._state_lock:
            callback = (
                None
                if key in self._suppressed
                else self._callbacks.get(key, (None, None))[1]
            )
        if callback is not None:
            self._invoke_callback(key, callback, error)
        with self._state_lock:
            suppressed = key in self._suppressed
        if not suppressed:
            self.operation_failed.emit(key, error)

    @Slot(str)
    def _on_finished(self, key: str) -> None:
        with self._state_lock:
            was_active = key in self._active
            self._active.discard(key)
            self._callbacks.pop(key, None)
            self._tasks.pop(key, None)
            self._suppressed.discard(key)
        if was_active:
            self.operation_finished.emit(key)

    def _invoke_callback(self, key: str, callback: Callable, value: object) -> bool:
        try:
            callback(value)
        except Exception:
            LOGGER.exception("Background callback failed: %s", key)
            return False
        return True
