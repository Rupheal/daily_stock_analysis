# -*- coding: utf-8 -*-
"""Regression tests for cooperative task cancellation."""

import sys
import threading
import types
import unittest
from concurrent.futures import Future
from unittest.mock import patch

# Keep this unit test on the TaskQueue seam: avoid importing the real market-data
# package (and pandas) when cancellation behavior does not depend on it.
_data_provider = types.ModuleType("data_provider")
_data_provider.__path__ = []
_data_provider_base = types.ModuleType("data_provider.base")
_data_provider_base.canonical_stock_code = lambda code: str(code)
_data_provider_base.normalize_stock_code = lambda code: str(code)
sys.modules.setdefault("data_provider", _data_provider)
sys.modules.setdefault("data_provider.base", _data_provider_base)

from src.services.cancellation import CancellationRequested
from src.services.task_queue import AnalysisTaskQueue, TaskInfo, TaskStatus


class TaskQueueCancellationTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.original_instance = AnalysisTaskQueue._instance
        AnalysisTaskQueue._instance = None
        self.queue = AnalysisTaskQueue(max_workers=1)
        self.events = []
        self.queue._broadcast_event = lambda event_type, data: self.events.append((event_type, data))

    def tearDown(self) -> None:
        if self.queue._executor is not None:
            self.queue._executor.shutdown(wait=False, cancel_futures=True)
        AnalysisTaskQueue._instance = self.original_instance

    def _insert_task(self, task: TaskInfo, future: Future | None = None) -> None:
        task.dedupe_key = task.dedupe_key or task.stock_code
        with self.queue._data_lock:
            self.queue._tasks[task.task_id] = task
            self.queue._analyzing_stocks[task.dedupe_key] = task.task_id
            if future is not None:
                self.queue._futures[task.task_id] = future

    def test_cancellation_signal_bypasses_fail_open_exception_handlers(self) -> None:
        swallowed = False
        try:
            try:
                raise CancellationRequested("stop")
            except Exception:
                swallowed = True
        except CancellationRequested:
            pass

        self.assertFalse(swallowed)

    def test_cancel_requested_task_remains_inflight_for_queue_reconfiguration(self) -> None:
        task = TaskInfo(
            task_id="cancel-inflight",
            stock_code="600000",
            status=TaskStatus.CANCEL_REQUESTED,
        )
        self._insert_task(task)

        with self.queue._data_lock:
            self.assertTrue(self.queue._has_inflight_tasks_locked())

    def test_pending_task_cancels_immediately(self) -> None:
        future = Future()
        task = TaskInfo(task_id="pending-1", stock_code="600519", status=TaskStatus.PENDING)
        self._insert_task(task, future)

        result = self.queue.request_cancel(task.task_id)

        self.assertIsNotNone(result)
        self.assertEqual(result.status, TaskStatus.CANCELLED)
        self.assertTrue(future.cancelled())
        self.assertNotIn(task.dedupe_key, self.queue._analyzing_stocks)
        self.assertEqual(self.events[-1][0], "task_cancelled")

    def test_processing_task_enters_cancel_requested_and_is_idempotent(self) -> None:
        future = Future()
        self.assertTrue(future.set_running_or_notify_cancel())
        task = TaskInfo(task_id="running-1", stock_code="000001", status=TaskStatus.PROCESSING)
        self._insert_task(task, future)

        first = self.queue.request_cancel(task.task_id)
        second = self.queue.request_cancel(task.task_id)

        self.assertEqual(first.status, TaskStatus.CANCEL_REQUESTED)
        self.assertEqual(second.status, TaskStatus.CANCEL_REQUESTED)
        self.assertFalse(future.cancelled())
        with self.assertRaises(CancellationRequested):
            self.queue.raise_if_cancel_requested(task.task_id)
        self.assertEqual(
            [event for event, _ in self.events if event == "task_cancel_requested"],
            ["task_cancel_requested"],
        )

    def test_processing_analysis_acknowledges_cooperative_cancel(self) -> None:
        task = TaskInfo(task_id="analysis-1", stock_code="600519", status=TaskStatus.PENDING)
        self._insert_task(task)
        entered = threading.Event()
        release = threading.Event()
        worker_result = []

        fake_module = types.ModuleType("src.services.analysis_service")

        class FakeAnalysisService:
            last_error = None

            def analyze_stock(self, **kwargs):
                entered.set()
                self.assert_release(release)
                kwargs["cancel_check"]()
                return {"stock_name": "should-not-publish"}

            @staticmethod
            def assert_release(event):
                if not event.wait(timeout=2):
                    raise AssertionError("test worker did not receive release")

        fake_module.AnalysisService = FakeAnalysisService

        with patch.dict(sys.modules, {"src.services.analysis_service": fake_module}):
            thread = threading.Thread(
                target=lambda: worker_result.append(
                    self.queue._execute_task(
                        task.task_id,
                        task.stock_code,
                        "detailed",
                        False,
                        False,
                    )
                ),
                daemon=True,
            )
            thread.start()
            self.assertTrue(entered.wait(timeout=2))

            requested = self.queue.request_cancel(task.task_id)
            self.assertEqual(requested.status, TaskStatus.CANCEL_REQUESTED)
            release.set()
            thread.join(timeout=2)

        self.assertFalse(thread.is_alive())
        final = self.queue.get_task(task.task_id)
        self.assertIsNotNone(final)
        self.assertEqual(final.status, TaskStatus.CANCELLED)
        self.assertIsNone(final.result)
        self.assertEqual(worker_result, [None])
        event_types = [event for event, _ in self.events]
        self.assertIn("task_cancel_requested", event_types)
        self.assertIn("task_cancelled", event_types)
        self.assertNotIn("task_completed", event_types)

    def test_running_background_result_is_fenced_after_cancel(self) -> None:
        task = TaskInfo(task_id="background-1", stock_code="MARKET", status=TaskStatus.PENDING)
        self._insert_task(task)
        entered = threading.Event()
        release = threading.Event()
        worker_result = []

        def run_task():
            entered.set()
            self.assertTrue(release.wait(timeout=2))
            return {"should_not_publish": True}

        thread = threading.Thread(
            target=lambda: worker_result.append(
                self.queue._execute_background_task(task.task_id, run_task)
            ),
            daemon=True,
        )
        thread.start()
        self.assertTrue(entered.wait(timeout=2))

        requested = self.queue.request_cancel(task.task_id)
        self.assertEqual(requested.status, TaskStatus.CANCEL_REQUESTED)
        release.set()
        thread.join(timeout=2)

        self.assertFalse(thread.is_alive())
        final = self.queue.get_task(task.task_id)
        self.assertIsNotNone(final)
        self.assertEqual(final.status, TaskStatus.CANCELLED)
        self.assertIsNone(final.result)
        self.assertEqual(worker_result, [None])
        self.assertNotIn("task_completed", [event for event, _ in self.events])
        self.assertIn("task_cancelled", [event for event, _ in self.events])

    def test_cancelling_one_task_does_not_cancel_another(self) -> None:
        future_a = Future()
        future_b = Future()
        task_a = TaskInfo(task_id="a", stock_code="600519", status=TaskStatus.PENDING)
        task_b = TaskInfo(task_id="b", stock_code="000001", status=TaskStatus.PENDING)
        self._insert_task(task_a, future_a)
        self._insert_task(task_b, future_b)

        self.queue.request_cancel(task_a.task_id)

        self.assertEqual(self.queue.get_task(task_a.task_id).status, TaskStatus.CANCELLED)
        self.assertEqual(self.queue.get_task(task_b.task_id).status, TaskStatus.PENDING)
        self.assertFalse(future_b.cancelled())


if __name__ == "__main__":
    unittest.main()
