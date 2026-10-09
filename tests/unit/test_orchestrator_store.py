from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from nyan_shop_bot.orchestrator.adapters import process_identity
from nyan_shop_bot.orchestrator.models import DesiredState, RunPhase, TaskSpec
from nyan_shop_bot.orchestrator.service import RunnerService
from nyan_shop_bot.orchestrator.store import StateStore
from tests.unit.test_orchestrator_models import task_data


def make_task(issue: int, task_id: str, branch: str) -> TaskSpec:
    value = task_data()
    value.update(
        {
            "issue_number": issue,
            "issue_url": f"https://github.com/nyanduong/nyan-shop-bot/issues/{issue}",
            "task_id": task_id,
            "branch": branch,
        }
    )
    return TaskSpec.model_validate(value)


def create(store: StateStore, run_id: str, task: TaskSpec, tmp_path: Path) -> None:
    store.create_run(
        run_id=run_id,
        task=task,
        task_path=tmp_path / f"{task.task_id}.json",
        base_sha="b" * 40,
        worktree_path=tmp_path / run_id,
        max_workers=2,
    )


def test_state_and_claim_survive_store_reopen(tmp_path: Path) -> None:
    task = make_task(15, "NSB-041", "nyan/nsb-041-runner-proof")
    store = StateStore(tmp_path / "state")
    create(store, "run-one", task, tmp_path)
    store.set_desired_state("run-one", DesiredState.PAUSED)

    reopened = StateStore(tmp_path / "state")

    assert reopened.get_run("run-one")["desired_state"] == "PAUSED"
    assert reopened.active_claims()[0]["run_id"] == "run-one"


def test_duplicate_issue_claim_is_rejected(tmp_path: Path) -> None:
    task = make_task(15, "NSB-041", "nyan/nsb-041-runner-proof")
    store = StateStore(tmp_path / "state")
    create(store, "run-one", task, tmp_path)

    with pytest.raises(RuntimeError, match="already has active run"):
        create(store, "run-two", task, tmp_path)


def test_global_writer_limit_is_two(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state")
    create(
        store,
        "run-one",
        make_task(15, "NSB-041", "nyan/nsb-041-runner-proof"),
        tmp_path,
    )
    create(
        store,
        "run-two",
        make_task(16, "NSB-042", "nyan/nsb-042-second"),
        tmp_path,
    )

    with pytest.raises(RuntimeError, match="writer limit reached"):
        create(
            store,
            "run-three",
            make_task(17, "NSB-043", "nyan/nsb-043-third"),
            tmp_path,
        )


def test_pause_stop_resume_do_not_create_another_claim(tmp_path: Path) -> None:
    task = make_task(15, "NSB-041", "nyan/nsb-041-runner-proof")
    store = StateStore(tmp_path / "state")
    create(store, "run-one", task, tmp_path)

    store.set_desired_state("run-one", DesiredState.PAUSED)
    store.set_desired_state("run-one", DesiredState.STOPPED)
    store.set_desired_state("run-one", DesiredState.RUNNING)

    assert store.get_run("run-one")["desired_state"] == "RUNNING"
    assert len(store.active_claims()) == 1


def test_process_lease_allows_only_one_runner(tmp_path: Path) -> None:
    task = make_task(15, "NSB-041", "nyan/nsb-041-runner-proof")
    store = StateStore(tmp_path / "state")
    create(store, "run-one", task, tmp_path)

    identity = process_identity(os.getpid())
    assert identity is not None
    store.acquire_process_lease("run-one", pid=os.getpid(), identity=identity, token="owner-one")
    with pytest.raises(RuntimeError, match="active process lease"):
        store.acquire_process_lease(
            "run-one", pid=os.getpid(), identity=identity, token="owner-two"
        )

    store.release_process_lease("run-one", "owner-one")
    assert store.get_run("run-one")["pid"] is None


def test_process_lease_cannot_release_while_agent_is_active(tmp_path: Path) -> None:
    task = make_task(15, "NSB-041", "nyan/nsb-041-runner-proof")
    store = StateStore(tmp_path / "state")
    create(store, "run-one", task, tmp_path)
    identity = process_identity(os.getpid())
    assert identity is not None
    store.acquire_process_lease("run-one", pid=os.getpid(), identity=identity, token="owner-one")
    store.set_active_agent(
        "run-one",
        token="owner-one",
        pid=os.getpid(),
        identity=identity,
        completion_path=str(tmp_path / "state" / "runs" / "run-one.launcher-contained"),
        nonce="test-nonce",
    )

    with pytest.raises(RuntimeError, match="agent is active"):
        store.release_process_lease("run-one", "owner-one")

    assert store.get_run("run-one")["process_token"] == "owner-one"


def test_stop_is_terminal_and_releases_claim_when_runner_is_idle(tmp_path: Path) -> None:
    task = make_task(15, "NSB-041", "nyan/nsb-041-runner-proof")
    service = RunnerService(tmp_path, tmp_path / "state")
    create(service.store, "run-one", task, tmp_path)

    service.set_control("run-one", DesiredState.STOPPED)

    assert service.store.get_run("run-one")["phase"] == RunPhase.STOPPED
    assert service.store.active_claims() == []


def test_task_snapshot_is_immutable_after_claim(tmp_path: Path) -> None:
    task = make_task(15, "NSB-041", "nyan/nsb-041-runner-proof")
    task_path = tmp_path / "NSB-041.json"
    task_path.write_text(task.model_dump_json(), encoding="utf-8")
    service = RunnerService(tmp_path, tmp_path / "state")
    service.store.create_run(
        run_id="run-one",
        task=task,
        task_path=task_path,
        base_sha="b" * 40,
        worktree_path=tmp_path / "worktree",
        max_workers=2,
    )
    mutated = task.model_copy(update={"pr_base": "main", "auto_merge_eligible": True})
    task_path.write_text(mutated.model_dump_json(), encoding="utf-8")

    frozen = service.task_for_run(service.store.get_run("run-one"))

    assert frozen.pr_base == "nyan/nsb-040-agent-runner"
    assert frozen.auto_merge_eligible is False
    assert service.store.get_run("run-one")["deadline_at"] is not None


def test_existing_state_adds_usage_schema_without_rewriting_history(tmp_path: Path) -> None:
    state_dir = tmp_path / "legacy-state"
    state_dir.mkdir()
    database = state_dir / "state.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE runs (
                run_id TEXT PRIMARY KEY,
                total_tokens INTEGER NOT NULL,
                worker_cumulative_tokens INTEGER NOT NULL,
                worker_accounted_events_sha256 TEXT,
                reviewer_accounted_events_sha256 TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO runs (
                run_id, total_tokens, worker_cumulative_tokens,
                worker_accounted_events_sha256, reviewer_accounted_events_sha256
            ) VALUES ('historical-run', 42424, 777, 'worker-old', 'reviewer-old')
            """
        )

    store = StateStore(state_dir)
    reopened = StateStore(state_dir)
    run = reopened.get_run("historical-run")

    assert run["total_tokens"] == 42_424
    assert run["worker_cumulative_tokens"] == 777
    assert run["worker_accounted_events_sha256"] == "worker-old"
    assert run["reviewer_accounted_events_sha256"] == "reviewer-old"
    assert run["worker_enforceable_tokens"] is None
    assert run["reviewer_enforceable_tokens"] is None
    assert store.invocation_usage("historical-run") == []
