#!/usr/bin/env python3
"""Test script to verify Dead Letter Queue implementation.

This script runs basic DLQ tests without requiring full pytest setup.
"""

import asyncio
from datetime import datetime, timedelta, timezone
import sys

# Add project root to path
sys.path.insert(0, "/Users/les/Projects/mahavishnu")

from mahavishnu.core.dead_letter_queue import (
    DeadLetterQueue,
    DeadLetterStatus,
    FailedTask,
    RetryPolicy,
)


async def test_basic_enqueue():
    """Test basic task enqueue."""
    print("Testing basic enqueue...")

    dlq = DeadLetterQueue(max_size=100)

    task = await dlq.enqueue(
        task_id="wf_123",
        task={"type": "test"},
        repos=["/path/to/repo"],
        error="Test error",
        retry_policy=RetryPolicy.EXPONENTIAL,
        max_retries=3,
    )

    assert task.task_id == "wf_123"
    assert task.status == DeadLetterStatus.PENDING
    assert task.retry_count == 0

    print("✓ Basic enqueue test passed")


async def test_queue_full():
    """Test queue full error."""
    print("Testing queue full...")

    dlq = DeadLetterQueue(max_size=5)

    # Fill the queue
    for i in range(5):
        await dlq.enqueue(
            task_id=f"wf_{i}",
            task={"type": "test"},
            repos=["/path/to/repo"],
            error=f"Error {i}",
        )

    # Try to enqueue one more
    try:
        await dlq.enqueue(
            task_id="wf_overflow",
            task={"type": "test"},
            repos=["/path/to/repo"],
            error="Overflow",
        )
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "full" in str(e).lower()

    print("✓ Queue full test passed")


async def test_get_task():
    """Test retrieving a specific task."""
    print("Testing get task...")

    dlq = DeadLetterQueue(max_size=100)

    await dlq.enqueue(
        task_id="wf_123",
        task={"type": "test"},
        repos=["/path/to/repo"],
        error="Test error",
    )

    task = await dlq.get_task("wf_123")
    assert task is not None
    assert task.task_id == "wf_123"

    task = await dlq.get_task("wf_nonexistent")
    assert task is None

    print("✓ Get task test passed")


async def test_retry_policies():
    """Test retry policy calculations."""
    print("Testing retry policies...")

    dlq = DeadLetterQueue(max_size=100)
    now = datetime.now(timezone.utc)

    # NEVER policy
    next_retry = dlq._calculate_next_retry(RetryPolicy.NEVER, 0)
    assert next_retry is None

    # IMMEDIATE policy
    next_retry = dlq._calculate_next_retry(RetryPolicy.IMMEDIATE, 0)
    assert next_retry is not None
    assert abs((next_retry - now).total_seconds()) < 1

    # LINEAR policy
    next_retry = dlq._calculate_next_retry(RetryPolicy.LINEAR, 0)
    assert abs((next_retry - now).total_seconds() - 300) < 1  # 5 minutes

    # EXPONENTIAL policy
    next_retry = dlq._calculate_next_retry(RetryPolicy.EXPONENTIAL, 0)
    assert abs((next_retry - now).total_seconds() - 60) < 1  # 1 minute

    next_retry = dlq._calculate_next_retry(RetryPolicy.EXPONENTIAL, 1)
    assert abs((next_retry - now).total_seconds() - 120) < 1  # 2 minutes

    # Capped at 60 minutes
    next_retry = dlq._calculate_next_retry(RetryPolicy.EXPONENTIAL, 10)
    assert abs((next_retry - now).total_seconds() - 3600) < 1  # 60 minutes

    print("✓ Retry policies test passed")


async def test_statistics():
    """Test getting queue statistics."""
    print("Testing statistics...")

    dlq = DeadLetterQueue(max_size=100)

    # Enqueue some tasks
    for i in range(5):
        await dlq.enqueue(
            task_id=f"wf_{i}",
            task={"type": "test"},
            repos=["/path/to/repo"],
            error=f"Error {i}",
            error_category="transient" if i % 2 == 0 else "permanent",
        )

    stats = await dlq.get_statistics()

    assert stats["queue_size"] == 5
    assert stats["max_size"] == 100
    assert stats["utilization_percent"] == 5.0
    assert stats["status_breakdown"]["pending"] == 5
    assert stats["error_categories"]["transient"] == 3
    assert stats["error_categories"]["permanent"] == 2
    assert stats["lifetime_stats"]["enqueued_total"] == 5

    print("✓ Statistics test passed")


async def test_archive_task():
    """Test archiving a task."""
    print("Testing archive task...")

    dlq = DeadLetterQueue(max_size=100)

    await dlq.enqueue(
        task_id="wf_123",
        task={"type": "test"},
        repos=["/path/to/repo"],
        error="Test error",
    )

    # Archive the task
    result = await dlq.archive_task("wf_123")
    assert result is True

    # Task should be removed from queue
    task = await dlq.get_task("wf_123")
    assert task is None

    # Stats should be updated
    assert dlq._stats["archived"] == 1

    print("✓ Archive task test passed")


async def test_clear_all():
    """Test clearing all tasks."""
    print("Testing clear all...")

    dlq = DeadLetterQueue(max_size=100)

    # Enqueue some tasks
    for i in range(10):
        await dlq.enqueue(
            task_id=f"wf_{i}",
            task={"type": "test"},
            repos=["/path/to/repo"],
            error=f"Error {i}",
        )

    # Clear all
    count = await dlq.clear_all()
    assert count == 10

    # Queue should be empty
    stats = await dlq.get_statistics()
    assert stats["queue_size"] == 0

    print("✓ Clear all test passed")


async def test_failed_task_serialization():
    """Test FailedTask to_dict and from_dict."""
    print("Testing FailedTask serialization...")

    now = datetime.now(timezone.utc)

    task = FailedTask(
        task_id="wf_123",
        task={"type": "test"},
        repos=["/path/to/repo"],
        error="Test error",
        failed_at=now,
        retry_policy=RetryPolicy.EXPONENTIAL,
    )

    # Convert to dict
    task_dict = task.to_dict()
    assert task_dict["task_id"] == "wf_123"
    assert task_dict["retry_policy"] == "exponential"
    assert task_dict["status"] == "pending"

    # Convert back from dict
    task2 = FailedTask.from_dict(task_dict)
    assert task2.task_id == "wf_123"
    assert task2.retry_policy == RetryPolicy.EXPONENTIAL
    assert task2.status == DeadLetterStatus.PENDING

    print("✓ FailedTask serialization test passed")


async def test_retry_processor_mock():
    """Test retry processor with mock callback."""
    print("Testing retry processor...")

    dlq = DeadLetterQueue(max_size=100)

    # Mock callback that succeeds
    async def mock_callback(task, repos):
        return {"status": "success"}

    # Enqueue a task ready for immediate retry
    await dlq.enqueue(
        task_id="wf_123",
        task={"type": "test"},
        repos=["/path/to/repo"],
        error="Test error",
        retry_policy=RetryPolicy.IMMEDIATE,
        max_retries=3,
    )

    # Start processor
    await dlq.start_retry_processor(mock_callback, check_interval_seconds=1)

    # Wait for processing
    await asyncio.sleep(2)

    # Stop processor
    await dlq.stop_retry_processor()

    # Task should be removed (successful retry)
    task = await dlq.get_task("wf_123")
    assert task is None

    # Stats should show success
    assert dlq._stats["retry_success"] == 1

    print("✓ Retry processor test passed")


async def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("Dead Letter Queue Test Suite")
    print("=" * 60 + "\n")

    tests = [
        test_basic_enqueue,
        test_queue_full,
        test_get_task,
        test_retry_policies,
        test_statistics,
        test_archive_task,
        test_clear_all,
        test_failed_task_serialization,
        test_retry_processor_mock,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            await test()
            passed += 1
        except Exception as e:
            print(f"✗ {test.__name__} failed: {e}")
            failed += 1
            import traceback

            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60 + "\n")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
