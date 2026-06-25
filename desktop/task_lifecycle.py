"""Small helpers for safely stopping interruptible desktop workers."""
from __future__ import annotations

from typing import Protocol


class InterruptibleTask(Protocol):
    def isRunning(self) -> bool: ...
    def requestInterruption(self) -> None: ...
    def wait(self, timeout_ms: int) -> bool: ...


def is_task_running(task: InterruptibleTask | None) -> bool:
    """Return whether an optional Qt-style worker is still active."""
    return bool(task is not None and task.isRunning())


def cancel_task(task: InterruptibleTask | None, timeout_ms: int = 5000) -> bool:
    """Request cooperative cancellation and wait for a bounded shutdown."""
    if not is_task_running(task):
        return True
    assert task is not None
    task.requestInterruption()
    return bool(task.wait(max(0, int(timeout_ms))))
