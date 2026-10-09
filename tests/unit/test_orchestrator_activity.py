from __future__ import annotations

import io
import json
import os
import sys
import threading
import time
from pathlib import Path

from nyan_shop_bot.orchestrator.activity import normalize_stream_line, redact_text
from nyan_shop_bot.orchestrator.adapters import _run_monitored, process_identity
from nyan_shop_bot.orchestrator.models import DesiredState, TaskSpec, WorkerKind
from nyan_shop_bot.orchestrator.service import RunnerService
from nyan_shop_bot.orchestrator.store import StateStore
from nyan_shop_bot.orchestrator.viewer import watch_activity


def _task() -> TaskSpec:
    return TaskSpec.model_validate(
        {
            "schema_version": 1,
            "task_id": "NSB-041",
            "issue_number": 15,
            "issue_url": "https://github.com/nyanduong/nyan-shop-bot/issues/15",
            "repository": "nyanduong/nyan-shop-bot",
            "title": "Viewer fixture",
            "base_ref": "main",
            "pr_base": "main",
            "branch": "nyan/nsb-041-viewer-fixture",
            "worker": "codex",
            "role": "backend",
            "risk": "low",
            "queue_phase": "demo",
            "queue_eligible": False,
            "trusted_prompt": "Create only the deterministic viewer fixture document.",
            "acceptance_criteria": ["Expose a real live event."],
            "allowed_paths": ["docs/viewer-fixture.md"],
            "required_checks": ["ci-gate"],
            "dependencies": [],
            "auto_merge_eligible": False,
        }
    )


def test_live_event_arrives_before_worker_exits(tmp_path: Path) -> None:
    seen = threading.Event()
    finished = threading.Event()
    errors: list[BaseException] = []

    def stream(channel: str, line: str, sequence: int) -> None:
        assert sequence >= 1
        if channel == "stdout" and "thread.started" in line:
            seen.set()

    script = (
        "import json,time; "
        "print(json.dumps({'type':'thread.started','thread_id':'live-session'}), flush=True); "
        "time.sleep(1.0)"
    )

    def run() -> None:
        try:
            _run_monitored(
                [sys.executable, "-c", script],
                cwd=tmp_path,
                stdin_text=None,
                stdout_path=tmp_path / "events.jsonl",
                stderr_path=tmp_path / "stderr.log",
                control=lambda: DesiredState.RUNNING,
                timeout_seconds=10,
                on_stream_line=stream,
            )
        except BaseException as error:
            errors.append(error)
        finally:
            finished.set()

    thread = threading.Thread(target=run)
    thread.start()
    assert seen.wait(timeout=3)
    assert not finished.is_set(), "the live event was only delivered after worker exit"
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert errors == []


def test_visibility_failure_and_slow_consumer_do_not_change_worker_outcome(
    tmp_path: Path,
) -> None:
    calls = 0

    def failing_slow_sink(channel: str, line: str, sequence: int) -> None:
        nonlocal calls
        del channel, line, sequence
        calls += 1
        time.sleep(0.02)
        raise RuntimeError("synthetic visibility failure")

    script = "for i in range(2000): print(i, flush=True)"
    started = time.monotonic()
    report = _run_monitored(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        stdin_text=None,
        stdout_path=tmp_path / "burst.events.jsonl",
        stderr_path=tmp_path / "burst.stderr.log",
        control=lambda: DesiredState.RUNNING,
        timeout_seconds=10,
        on_stream_line=failing_slow_sink,
    )

    assert time.monotonic() - started < 4
    assert calls > 0
    assert report.degraded
    assert report.errors > 0 or report.dropped > 0
    assert (tmp_path / "burst.events.jsonl").read_text(encoding="utf-8").count("\n") == 2000


def test_activity_projection_redacts_secrets_and_keeps_real_tool_data(tmp_path: Path) -> None:
    synthetic_token = "gh" + "p_" + "abcdefghijklmnopqrstuvwxyz123456"
    line = json.dumps(
        {
            "type": "item.completed",
            "item": {
                "type": "command_execution",
                "status": "completed",
                "command": f"pytest TOKEN={synthetic_token}",
                "exit_code": 0,
                "aggregated_output": "must not be persisted",
            },
        }
    )

    event = normalize_stream_line(
        line,
        channel="stdout",
        worker=WorkerKind.CODEX,
        worktree=tmp_path,
    )

    assert event is not None
    rendered = json.dumps(event)
    assert "command_execution" in rendered
    assert "pytest" in rendered
    assert "arguments omitted" in rendered
    assert synthetic_token not in rendered
    assert "must not be persisted" not in rendered


def test_usage_projection_accepts_only_terminal_provider_events(tmp_path: Path) -> None:
    codex_started = normalize_stream_line(
        json.dumps(
            {
                "type": "turn.started",
                "usage": {"input_tokens": 999, "output_tokens": 999},
            }
        ),
        channel="stdout",
        worker=WorkerKind.CODEX,
        worktree=tmp_path,
    )
    codex_completed = normalize_stream_line(
        json.dumps(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 10,
                    "cached_input_tokens": 4,
                    "output_tokens": 3,
                    "reasoning_output_tokens": 2,
                },
            }
        ),
        channel="stdout",
        worker=WorkerKind.CODEX,
        worktree=tmp_path,
    )
    antigravity_step = normalize_stream_line(
        json.dumps(
            {
                "event": "step_update",
                "step_update": {
                    "step_type": "agent_response",
                    "usage": {"total_tokens": 999},
                },
            }
        ),
        channel="stdout",
        worker=WorkerKind.ANTIGRAVITY,
        worktree=tmp_path,
    )
    antigravity_result = normalize_stream_line(
        json.dumps(
            {
                "event": "result",
                "result": {"status": "SUCCESS", "usage": {"total_tokens": 16}},
            }
        ),
        channel="stdout",
        worker=WorkerKind.ANTIGRAVITY,
        worktree=tmp_path,
    )

    assert codex_started is not None and "usage" not in codex_started
    assert codex_completed is not None
    assert codex_completed["usage"] == {
        "raw_input_tokens": 10,
        "cached_input_tokens": 4,
        "raw_output_tokens": 3,
        "reasoning_tokens": 2,
    }
    assert antigravity_step is not None and "usage" not in antigravity_step
    assert antigravity_result is not None
    assert antigravity_result["usage"] == {"raw_provider_total": 16}


def test_redaction_covers_headers_flags_dsns_cloud_keys_and_stderr(tmp_path: Path) -> None:
    values = [
        "Authorization: Bearer " + "synthetic-secret-value",
        "tool --token " + "synthetic-secret-value",
        'password="correct horse battery staple" trailing-safe-text',
        "postgresql://user:" + "synthetic-secret-value" + "@db.invalid/name",
        "AK" + "IA" + "1234567890ABCDEF",
    ]
    rendered = " ".join(redact_text(value) for value in values)
    assert "synthetic-secret-value" not in rendered
    assert "correct horse battery staple" not in rendered
    assert "trailing-safe-text" in rendered
    assert "AK" + "IA" + "1234567890ABCDEF" not in rendered

    stderr = normalize_stream_line(
        "unclassified secret-shaped diagnostic",
        channel="stderr",
        worker=WorkerKind.CODEX,
        worktree=tmp_path,
    )
    assert stderr is not None
    assert "unclassified" not in json.dumps(stderr)


def test_raw_activity_catch_up_is_idempotent(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    task = _task()
    service = RunnerService(tmp_path, state_dir)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    service.store.create_run(
        run_id="catch-up-run",
        task=task,
        task_path=tmp_path / "task.json",
        base_sha="a" * 40,
        worktree_path=worktree,
        max_workers=2,
    )
    events_path = tmp_path / "events.jsonl"
    stderr_path = tmp_path / "stderr.log"
    events_path.write_text(
        json.dumps({"type": "thread.started", "thread_id": "catch-up-session"}) + "\n",
        encoding="utf-8",
    )
    stderr_path.write_text("private diagnostic\n", encoding="utf-8")

    for _ in range(2):
        service._replay_invocation_activity(
            "catch-up-run",
            task,
            role="worker",
            invocation_name="worker-initial",
            worktree=worktree,
            events_path=events_path,
            stderr_path=stderr_path,
        )

    activity = [
        event
        for event in service.store.events("catch-up-run", limit=20)
        if event["kind"] == "agent.activity"
    ]
    assert len(activity) == 2
    assert service.store.get_run("catch-up-run")["worker_session_id"] == "catch-up-session"

    events_path.write_text(
        json.dumps({"type": "turn.started"}) + "\n",
        encoding="utf-8",
    )
    service._replay_invocation_activity(
        "catch-up-run",
        task,
        role="worker",
        invocation_name="worker-initial-attempt-2",
        worktree=worktree,
        events_path=events_path,
        stderr_path=stderr_path,
    )
    activity = [
        event
        for event in service.store.events("catch-up-run", limit=20)
        if event["kind"] == "agent.activity"
    ]
    assert len(activity) == 4
    assert any(
        event["payload"].get("invocation") == "worker-initial-attempt-2" for event in activity
    )


def test_catch_up_preserves_raw_line_identity_across_live_queue_gaps(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    task = _task()
    service = RunnerService(tmp_path, state_dir)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    service.store.create_run(
        run_id="gap-run",
        task=task,
        task_path=tmp_path / "task.json",
        base_sha="a" * 40,
        worktree_path=worktree,
        max_workers=2,
    )
    lines = [
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "status": "completed",
                    "command": f"pytest case-{index}",
                    "exit_code": 0,
                },
            }
        )
        for index in range(1, 51)
    ]
    events_path = tmp_path / "gap.events.jsonl"
    stderr_path = tmp_path / "gap.stderr.log"
    events_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    stderr_path.write_text("", encoding="utf-8")
    for sequence in (*range(1, 11), *range(21, 31)):
        service._record_activity_line(
            "gap-run",
            task,
            role="worker",
            invocation="worker-initial-attempt-1",
            worktree=worktree,
            commit_sha="a" * 40,
            channel="stdout",
            line=lines[sequence - 1],
            sequence=sequence,
        )

    service._replay_invocation_activity(
        "gap-run",
        task,
        role="worker",
        invocation_name="worker-initial-attempt-1",
        worktree=worktree,
        events_path=events_path,
        stderr_path=stderr_path,
    )

    activity = [
        event
        for event in service.store.events("gap-run", limit=100)
        if event["kind"] == "agent.activity"
    ]
    sequences = [event["payload"].get("stream_sequence") for event in activity]
    assert len(activity) == 50
    assert sorted(sequences) == list(range(1, 51))


def test_viewer_reopens_from_cursor_without_controlling_runner(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    store = StateStore(state_dir)
    task = _task()
    store.create_run(
        run_id="viewer-run",
        task=task,
        task_path=tmp_path / "task.json",
        base_sha="a" * 40,
        worktree_path=tmp_path / "worktree",
        max_workers=2,
    )
    identity = process_identity(os.getpid())
    assert identity is not None
    store.acquire_process_lease(
        "viewer-run",
        pid=os.getpid(),
        identity=identity,
        token="viewer-fixture-token",
    )
    store.append_event(
        "viewer-run",
        "agent.activity",
        {
            "role": "worker",
            "session_id": "session-1",
            "kind": "turn.started",
            "summary": "real persisted event",
        },
    )
    event_count_before = len(store.events("viewer-run", limit=100))

    first = io.StringIO()
    cursor = watch_activity(
        state_dir,
        run_id="viewer-run",
        role="all",
        history=100,
        after_cursor=None,
        follow=False,
        poll_seconds=0.01,
        idle_seconds=0.01,
        output=first,
    )
    store.append_event(
        "viewer-run",
        "agent.activity",
        {
            "role": "worker",
            "session_id": "session-1",
            "kind": "turn.completed",
            "summary": "second real persisted event",
        },
    )
    event_count_after_insert = len(store.events("viewer-run", limit=100))
    second = io.StringIO()
    reopened_cursor = watch_activity(
        state_dir,
        run_id="viewer-run",
        role="all",
        history=100,
        after_cursor=cursor,
        follow=False,
        poll_seconds=0.01,
        idle_seconds=0.01,
        output=second,
    )
    third = io.StringIO()
    final_cursor = watch_activity(
        state_dir,
        run_id="viewer-run",
        role="all",
        history=100,
        after_cursor=reopened_cursor,
        follow=False,
        poll_seconds=0.01,
        idle_seconds=0.01,
        output=third,
    )

    assert "controller=alive" in first.getvalue()
    assert "real persisted event" in first.getvalue()
    assert "second real persisted event" in second.getvalue()
    assert "turn.started" not in second.getvalue()
    assert "second real persisted event" not in third.getvalue()
    assert "no runner control was changed" in second.getvalue()
    assert reopened_cursor > cursor
    assert final_cursor == reopened_cursor
    assert process_identity(os.getpid()) == identity
    assert event_count_after_insert == event_count_before + 1
    assert len(store.events("viewer-run", limit=100)) == event_count_after_insert


def test_read_only_viewer_does_not_create_missing_state(tmp_path: Path) -> None:
    state_dir = tmp_path / "missing"
    output = io.StringIO()

    try:
        watch_activity(
            state_dir,
            run_id=None,
            role="all",
            history=0,
            after_cursor=None,
            follow=False,
            poll_seconds=0.01,
            idle_seconds=0.01,
            output=output,
        )
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("missing state must fail instead of being created")

    assert not state_dir.exists()


def test_zero_history_starts_at_current_cursor_without_replay(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    store = StateStore(state_dir)
    task = _task()
    store.create_run(
        run_id="live-only-run",
        task=task,
        task_path=tmp_path / "task.json",
        base_sha="a" * 40,
        worktree_path=tmp_path / "worktree",
        max_workers=2,
    )
    store.append_event("live-only-run", "agent.activity", {"summary": "old event"})
    output = io.StringIO()

    cursor = watch_activity(
        state_dir,
        run_id="live-only-run",
        role="all",
        history=0,
        after_cursor=None,
        follow=False,
        poll_seconds=0.01,
        idle_seconds=0.01,
        output=output,
    )

    assert cursor > 0
    assert "old event" not in output.getvalue()
