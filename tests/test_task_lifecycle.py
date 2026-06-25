from __future__ import annotations

import unittest

from desktop.task_lifecycle import cancel_task, is_task_running


class FakeTask:
    def __init__(self, running: bool, wait_result: bool = True) -> None:
        self.running = running
        self.wait_result = wait_result
        self.interruptions = 0
        self.wait_timeout = None

    def isRunning(self) -> bool:
        return self.running

    def requestInterruption(self) -> None:
        self.interruptions += 1

    def wait(self, timeout_ms: int) -> bool:
        self.wait_timeout = timeout_ms
        return self.wait_result


class TaskLifecycleTests(unittest.TestCase):
    def test_missing_or_stopped_task_needs_no_cancellation(self) -> None:
        stopped = FakeTask(False)
        self.assertFalse(is_task_running(None))
        self.assertFalse(is_task_running(stopped))
        self.assertTrue(cancel_task(stopped))
        self.assertEqual(stopped.interruptions, 0)

    def test_running_task_is_interrupted_and_waited_for(self) -> None:
        task = FakeTask(True)
        self.assertTrue(is_task_running(task))
        self.assertTrue(cancel_task(task, 1250))
        self.assertEqual(task.interruptions, 1)
        self.assertEqual(task.wait_timeout, 1250)

    def test_timeout_is_reported_to_the_caller(self) -> None:
        task = FakeTask(True, wait_result=False)
        self.assertFalse(cancel_task(task, -1))
        self.assertEqual(task.wait_timeout, 0)


if __name__ == "__main__":
    unittest.main()
