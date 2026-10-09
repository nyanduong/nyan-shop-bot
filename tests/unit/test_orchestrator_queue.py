from __future__ import annotations

from nyan_shop_bot.orchestrator.models import TaskSpec
from nyan_shop_bot.orchestrator.queue import select_ready_task
from tests.unit.test_orchestrator_models import task_data


def task(task_id: str, issue: int, phase: str, dependencies: list[int]) -> TaskSpec:
    value = task_data()
    value.update(
        {
            "task_id": task_id,
            "issue_number": issue,
            "issue_url": f"https://github.com/nyanduong/nyan-shop-bot/issues/{issue}",
            "branch": f"nyan/{task_id.lower()}-queue-test",
            "queue_phase": phase,
            "queue_eligible": phase != "demo",
            "dependencies": dependencies,
        }
    )
    return TaskSpec.model_validate(value)


def test_queue_selects_only_trusted_m0_m2_task_with_closed_dependencies() -> None:
    states = {1: "CLOSED", 12: "CLOSED", 15: "OPEN", 16: "OPEN"}
    selected = select_ready_task(
        [task("NSB-041", 15, "demo", []), task("NSB-042", 16, "M1", [1, 12])],
        issue_state=lambda number: states[number],
        task_has_run=lambda _task_id: False,
    )

    assert selected is not None
    assert selected.task_id == "NSB-042"


def test_queue_skips_task_when_dependency_is_open_or_task_already_ran() -> None:
    candidate = task("NSB-042", 16, "M1", [1, 12])

    assert (
        select_ready_task(
            [candidate],
            issue_state=lambda number: "OPEN" if number == 12 else "CLOSED",
            task_has_run=lambda _task_id: False,
        )
        is None
    )
    assert (
        select_ready_task(
            [candidate],
            issue_state=lambda number: "OPEN" if number == 16 else "CLOSED",
            task_has_run=lambda _task_id: True,
        )
        is None
    )
