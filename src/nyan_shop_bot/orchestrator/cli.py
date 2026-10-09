"""Command-line control plane for the local Nyan agent runner."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from nyan_shop_bot.orchestrator.launcher import spawn_background
from nyan_shop_bot.orchestrator.models import DesiredState
from nyan_shop_bot.orchestrator.service import AUTO_MERGE_BLOCKER, RunnerService, process_alive
from nyan_shop_bot.orchestrator.viewer import watch_activity


def _service(root: Path, state_dir: Path | None) -> RunnerService:
    return RunnerService(root, state_dir)


def _start_background(service: RunnerService, run_id: str) -> dict[str, object]:
    service.prepare_process_launch(run_id)
    launched_pid = spawn_background(service.root, service.state_dir, run_id)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        run = service.store.get_run(run_id)
        persisted_pid = int(run["pid"]) if run["pid"] is not None else None
        if persisted_pid is not None:
            return {
                "run_id": run_id,
                "launched_pid": launched_pid,
                "pid": persisted_pid,
                "process_alive": process_alive(persisted_pid),
            }
        if not process_alive(launched_pid):
            break
        time.sleep(0.2)
    status = service.status(run_id)
    return {
        "run_id": run_id,
        "launched_pid": launched_pid,
        "pid": status["pid"],
        "process_alive": status["process_alive"],
        "phase": status["phase"],
        "last_error": status["last_error"],
    }


def _resolve_run_id(service: RunnerService, value: str | None) -> str:
    return value or service.store.latest_run_id()


def _wait_for_controller_settle(
    service: RunnerService,
    run_id: str,
    *,
    timeout_seconds: float = 10.0,
) -> dict[str, object]:
    """Bound a control race while an active agent's containment callback drains."""

    deadline = time.monotonic() + timeout_seconds
    status = service.status(run_id)
    while bool(status["process_alive"]) and time.monotonic() < deadline:
        time.sleep(0.1)
        status = service.status(run_id)
    return status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--state-dir", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="Claim a trusted task and launch its runner")
    selection = start.add_mutually_exclusive_group(required=True)
    selection.add_argument("--task", type=Path)
    selection.add_argument("--next", action="store_true", help="Select the next trusted M0-M2 task")
    start.add_argument("--max-workers", type=int, default=2, choices=(1, 2))
    start.add_argument("--foreground", action="store_true")

    for name in ("status", "pause", "resume", "stop"):
        control = subparsers.add_parser(name)
        control.add_argument("--run-id")

    watch = subparsers.add_parser(
        "watch",
        help="Read-only live activity viewer; never starts or controls a worker",
    )
    watch_target = watch.add_mutually_exclusive_group(required=True)
    watch_target.add_argument("--run-id")
    watch_target.add_argument("--all", action="store_true", dest="watch_all")
    watch.add_argument("--role", choices=("all", "runner", "worker", "reviewer"), default="all")
    watch.add_argument("--history", type=int, default=30)
    watch.add_argument("--after-cursor", type=int)
    watch.add_argument("--poll-seconds", type=float, default=0.25)
    watch.add_argument("--idle-seconds", type=float, default=15.0)
    watch.add_argument("--once", action="store_true", help="Print a snapshot and exit")

    authorize = subparsers.add_parser(
        "authorize-auto-merge",
        help="Fail-closed diagnostic; atomic head-and-base merge binding is unavailable",
    )
    authorize.add_argument("--repository", required=True)
    authorize.add_argument("--confirm", required=True)

    internal = subparsers.add_parser("_run", help=argparse.SUPPRESS)
    internal.add_argument("--run-id", required=True)
    return parser


def main(arguments: list[str] | None = None) -> int:
    args = build_parser().parse_args(arguments)
    root = args.root.resolve()
    state_dir = args.state_dir.resolve() if args.state_dir else None

    if args.command == "watch":
        if args.history < 0:
            raise SystemExit("--history must be zero or greater")
        if args.after_cursor is not None and args.after_cursor < 0:
            raise SystemExit("--after-cursor must be zero or greater")
        if args.poll_seconds <= 0 or args.idle_seconds <= 0:
            raise SystemExit("viewer intervals must be positive")
        watch_activity(
            state_dir or root / ".nyan-runner",
            run_id=None if args.watch_all else args.run_id,
            role=args.role,
            history=args.history,
            after_cursor=args.after_cursor,
            follow=not args.once,
            poll_seconds=args.poll_seconds,
            idle_seconds=args.idle_seconds,
            output=sys.stdout,
        )
        return 0

    service = _service(root, state_dir)

    if args.command == "start":
        if args.next:
            task_path = service.select_next_task_path("nyanduong/nyan-shop-bot")
            if task_path is None:
                raise SystemExit("No trusted M0-M2 task has closed dependencies")
        else:
            task_path = args.task if args.task.is_absolute() else root / args.task
        run_id = service.create_run(task_path, max_workers=args.max_workers)
        if args.foreground:
            service.run(run_id)
            print(json.dumps(service.status(run_id), indent=2, default=str))
        else:
            print(json.dumps(_start_background(service, run_id), indent=2, default=str))
        return 0

    if args.command == "_run":
        service.run(args.run_id)
        return 0

    if args.command == "authorize-auto-merge":
        service.authorize_auto_merge(args.repository, args.confirm)
        print(
            json.dumps(
                {
                    "repository": args.repository,
                    "authorized": False,
                    "scope": "BLOCKED until head and base can both be bound atomically",
                },
                indent=2,
            )
        )
        return 0

    run_id = _resolve_run_id(service, args.run_id)
    if args.command == "status":
        print(json.dumps(service.status(run_id), indent=2, default=str))
        return 0

    before = service.status(run_id)
    if args.command == "resume":
        service.resume_run(run_id)
    else:
        desired = {
            "pause": DesiredState.PAUSED,
            "stop": DesiredState.STOPPED,
        }[args.command]
        service.set_control(run_id, desired)
    status = service.status(run_id)
    if args.command in {"pause", "stop"} and bool(status["process_alive"]):
        status = _wait_for_controller_settle(service, run_id)
    if (
        args.command == "resume"
        and before["desired_state"] == DesiredState.PAUSED
        and bool(before["process_alive"])
    ):
        status = _wait_for_controller_settle(service, run_id)
    if (
        args.command in {"pause", "stop"}
        and not bool(status["process_alive"])
        and status["phase"]
        not in {"BLOCKED", "COMPLETED", "MERGE_PENDING_CONFIRMATION", "READY_FOR_OWNER", "STOPPED"}
    ):
        # Reconcile a control request that arrived after the first liveness check but
        # before the controller lease disappeared. The second call sees no live
        # controller, contains any registered child, and clears stale process state.
        service.set_control(run_id, desired)
        status = service.status(run_id)
    if args.command == "resume" and not bool(status["process_alive"]):
        status.update(_start_background(service, run_id))
    print(json.dumps(status, indent=2, default=str))
    return 0


def confirmation_text() -> str:
    """Expose why no confirmation text grants merge authority."""

    return AUTO_MERGE_BLOCKER
