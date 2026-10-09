"""Idempotently seed Nyan Shop Bot labels, milestones, and issues with gh."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "nyanduong/nyan-shop-bot"

LABELS: dict[str, tuple[str, str]] = {
    "agent:coordinator": ("5319e7", "Coordinator-owned work"),
    "agent:backend": ("1d76db", "Backend, bot, or supplier adapter work"),
    "agent:ui": ("d4c5f9", "Admin UI work"),
    "agent:review": ("0e8a16", "Independent review work"),
    "status:backlog": ("d4c5f9", "Not ready to claim"),
    "status:ready": ("0e8a16", "Dependencies satisfied; coordinator may grant a claim"),
    "status:in-progress": ("fbca04", "One writer has an active claim"),
    "status:in-review": ("1d76db", "Implementation is awaiting review"),
    "status:blocked": ("b60205", "Requires owner input or an external state change"),
    "risk:high": ("b60205", "High operational, money, data, or workflow risk"),
    "risk:medium": ("fbca04", "Material but bounded risk"),
    "risk:low": ("0e8a16", "Low-risk bounded change"),
    "priority:p0": ("b60205", "Foundation blocker"),
    "priority:p1": ("fbca04", "Next-wave priority"),
    "priority:p2": ("d4c5f9", "Later backlog priority"),
    "area:foundation": ("0052cc", "Repository foundation"),
    "area:backend": ("0052cc", "FastAPI or persistence"),
    "area:bot": ("0052cc", "Telegram bot"),
    "area:frontend": ("a371f7", "React admin"),
    "area:supplier": ("006b75", "Supplier integration"),
    "area:ci": ("000000", "CI, security, or delivery"),
    "area:release": ("c2e0c6", "Deployment or release"),
    "area:agents": ("5319e7", "Agent workflow"),
}

MILESTONES: dict[str, str] = {
    "M0 — Foundation": "Runnable mock foundation, agent workflow, CI, and container delivery.",
    "M1 — Catalog and read-only integrations": "Normalized catalog and read-only supplier/UI/bot work.",
    "M2 — Simulated end-to-end orders": "Durable order behavior using fake suppliers and mock checkout only.",
    "M3 — Staging and live readiness": "Mock staging and evidence-based readiness; does not authorize production.",
    "M4 — Unattended agent dispatch": "Durable local orchestration with owner-gated merge enablement and no live-money authority.",
}


@dataclass(frozen=True)
class IssueSpec:
    code: str
    title: str
    milestone: str
    owner: str
    risk: str
    priority: str
    areas: tuple[str, ...]
    dependencies: tuple[str, ...]
    objective: str
    scope: tuple[str, ...]
    out_of_scope: tuple[str, ...]
    acceptance: tuple[str, ...]
    tests: tuple[str, ...]
    files: tuple[str, ...]


ISSUES = (
    IssueSpec(
        "NSB-001",
        "Bootstrap repo, agent workflow, and CI/container delivery",
        "M0 — Foundation",
        "coordinator",
        "high",
        "p0",
        ("foundation", "backend", "frontend", "bot", "ci", "agents"),
        (),
        "Create a runnable, mock-only foundation and a real reviewable GitHub workflow.",
        (
            "FastAPI health/readiness, PostgreSQL migration, and a small synthetic catalog.",
            "React/Vite/TypeScript admin reading the backend catalog with a visible MOCK state.",
            "Offline-testable aiogram handler skeleton, agent instructions/templates, Docker, and CI.",
        ),
        (
            "Live supplier adapters, order/payment flows, production deployment, and backlog implementation beyond NSB-001.",
            "Automatic merge or unattended agent dispatch.",
        ),
        (
            "One setup/dev path and one unified verify command work on documented PowerShell/Linux environments.",
            "PR and main run lint, typecheck, tests, PostgreSQL migration, frontend build, mock smoke, Docker build, secret/workflow checks, and fail-closed ci-gate.",
            "Trusted main publishes exact-SHA GHCR images only after the same commit passes ci-gate.",
            "Defaults are mock/disabled/false; no live write route or real credential is present.",
        ),
        (
            "Run python scripts/task.py verify and python scripts/task.py smoke.",
            "Verify unsafe settings fail, non-loopback runtime networking is blocked in tests, bot uses no live transport, and forbidden write paths are absent.",
            "Attach the real Actions run and exact HEAD SHA.",
        ),
        (
            "Repository-wide foundation files; coordinator is the only Phase 0 writer.",
            "Private nyan-bootstrap/ inputs must be removed from tracking but retained locally.",
        ),
    ),
    IssueSpec(
        "NSB-010",
        "Normalized catalog, capability model, and code-generated schema",
        "M1 — Catalog and read-only integrations",
        "backend",
        "high",
        "p1",
        ("backend", "supplier"),
        ("NSB-001", "NSB-040"),
        "Define the reviewed catalog contract that later backend and UI work can safely share.",
        (
            "Explicit currency/unit, supplier product and variant identities, mapping approval state, freshness/error state, and a deterministic fake supplier.",
            "Generate OpenAPI and UI fixtures/client input from FastAPI code.",
        ),
        ("Supplier purchase operations and guessed schemas.", "Automatic product mapping by name."),
        (
            "Mapping requires explicit admin approval and keeps supplier IDs distinct.",
            "OpenAPI and fixtures come from code and include stale/error state.",
            "Purchase capability remains disabled.",
        ),
        (
            "Contract/schema tests, currency/unit tests, mapping approval tests, and deterministic fake-supplier tests.",
            "Full repository verification and exact-SHA evidence.",
        ),
        (
            "src/nyan_shop_bot/catalog/**",
            "tests/**",
            "generated contract/fixture files assigned by coordinator",
        ),
    ),
    IssueSpec(
        "NSB-011",
        "VietShare read-only adapter and signing tests",
        "M1 — Catalog and read-only integrations",
        "supplier-backend",
        "high",
        "p1",
        ("backend", "supplier"),
        ("NSB-010",),
        "Implement only verified VietShare account/catalog/detail reads and deterministic signing behavior.",
        (
            "Raw-byte HMAC canonicalization, ordered query, fake clock/nonce, pagination, timeout/429 handling, and redaction.",
        ),
        ("Live POST orders, top-up, or use of real credentials in CI.",),
        (
            "Canonical path includes /v1 and exact query order; body hash uses transmitted bytes.",
            "Retry behavior refreshes timestamp/nonce/signature while write capability stays off.",
            "Rate limiting and Retry-After are represented without live purchase claims.",
        ),
        (
            "Deterministic signing vectors, pagination, timeout, 429/backoff, redaction, and outbound-block tests.",
        ),
        ("src/nyan_shop_bot/suppliers/vietshare/**", "tests/suppliers/vietshare/**"),
    ),
    IssueSpec(
        "NSB-012",
        "KhoMMO read-only adapter",
        "M1 — Catalog and read-only integrations",
        "supplier-backend",
        "high",
        "p1",
        ("backend", "supplier"),
        ("NSB-010",),
        "Implement evidence-backed KhoMMO account/product reads without pretending missing order guarantees exist.",
        (
            "Bearer redaction, me/products/detail, pagination, stock, and separate CREDIT/VND units.",
        ),
        ("Orders, blind timeout retry, a second 5% discount, or interpreting CREDIT as postpaid.",),
        (
            "Only documented response fields are parsed; unknown schema returns unsupported with a recorded gap.",
            "Published API price is not discounted again and wallet units remain separate.",
            "Purchase capability remains disabled.",
        ),
        (
            "Fixture parsing, pagination, redaction, currency separation, missing-schema, and outbound-block tests.",
        ),
        ("src/nyan_shop_bot/suppliers/khommo/**", "tests/suppliers/khommo/**"),
    ),
    IssueSpec(
        "NSB-013",
        "Roboticvn schema audit and read-only adapter",
        "M1 — Catalog and read-only integrations",
        "supplier-backend",
        "high",
        "p1",
        ("backend", "supplier"),
        ("NSB-010",),
        "Audit current public OpenAPI and implement only confirmed Roboticvn reads.",
        (
            "Fetch public OpenAPI by GET, record provenance/checksum, compare request requirements, and implement product/detail/variant/wallet reads.",
        ),
        (
            "Quote/order/top-up writes, guessed request bodies, or unapproved delivery credential access.",
        ),
        (
            "Schema provenance and checksum are recorded without partner secrets.",
            "Quote/order/top-up gaps are explicit and write capabilities stay disabled.",
            "Read models keep product and variant identities distinct.",
        ),
        ("Schema/fixture tests, error/rate-limit tests, redaction, and outbound-block tests.",),
        (
            "src/nyan_shop_bot/suppliers/roboticvn/**",
            "tests/suppliers/roboticvn/**",
            "docs/provenance/**",
        ),
    ),
    IssueSpec(
        "NSB-014",
        "Admin catalog, suppliers, and environment state",
        "M1 — Catalog and read-only integrations",
        "ui-antigravity",
        "medium",
        "p1",
        ("frontend",),
        ("NSB-010",),
        "Build the Vietnamese admin catalog UI from the backend-generated contract.",
        (
            "Catalog, supplier balance/currency, stale/error/empty/loading states, and visible MOCK/READ-ONLY environment status.",
        ),
        ("Backend/workflow edits, live credentials, or invented profit figures.",),
        (
            "UI consumes generated OpenAPI/fixtures and handles responsive/keyboard/reduced-motion use.",
            "No supplier credential or sensitive delivery data reaches the browser.",
            "MOCK/READ-ONLY status is prominent in every relevant state.",
        ),
        (
            "Frontend unit/component tests, accessibility checks, typecheck, lint, and production build.",
        ),
        ("admin/src/features/admin-dashboard/**",),
    ),
    IssueSpec(
        "NSB-015",
        "Telegram bot catalog browsing and simulated quote",
        "M1 — Catalog and read-only integrations",
        "backend-bot",
        "medium",
        "p1",
        ("backend", "bot"),
        ("NSB-010",),
        "Add honest mock/read-only catalog browsing to the Telegram bot.",
        (
            "Start, catalog, product detail, orders placeholder, support, and simulated quote using server-side identity/price.",
        ),
        ("Live Telegram transport in CI, Stars/payment, or supplier purchase.",),
        (
            "Callbacks do not trust product identity or price supplied by clients.",
            "Orders placeholder states that checkout is unavailable.",
            "Bot tests run without a Telegram token or outbound network.",
        ),
        (
            "Mocked aiogram transport, forged callback, catalog/error, and offline network-policy tests.",
        ),
        ("src/nyan_shop_bot/bot/**", "tests/bot/**"),
    ),
    IssueSpec(
        "NSB-020",
        "Order orchestration, dedupe, and reconciliation with fake supplier",
        "M2 — Simulated end-to-end orders",
        "backend",
        "high",
        "p1",
        ("backend",),
        ("NSB-010",),
        "Prove durable order invariants entirely against a fake supplier.",
        (
            "Persisted intent/attempt, database idempotency, crash recovery, UNKNOWN/RECONCILING, delivery retry separation, and safe price/stock/balance failures.",
        ),
        (
            "Live supplier failover, live refund/payment, or common retry semantics that erase supplier differences.",
        ),
        (
            "Duplicate clicks/callbacks cannot create a second obligation.",
            "Uncertain outcomes are reconciled without failover, repurchase, or guessed refund.",
            "Delivery/notification retries never create another supplier order.",
        ),
        (
            "Concurrency, duplicate callback, timeout/202, crash recovery, price/stock/balance, and migration integration tests.",
        ),
        ("src/nyan_shop_bot/orders/**", "coordinator-owned alembic/**", "tests/orders/**"),
    ),
    IssueSpec(
        "NSB-021",
        "Mock checkout across bot, API, and admin",
        "M2 — Simulated end-to-end orders",
        "backend-qa + ui",
        "high",
        "p1",
        ("backend", "frontend", "bot"),
        ("NSB-014", "NSB-015", "NSB-020"),
        "Demonstrate an authenticated local/test-only checkout across all surfaces with fake money and supplier behavior.",
        (
            "Success/failure/unknown/order history, browser E2E, bot transport test, and shared database fixture.",
        ),
        ("Bank QR, live Stars, public unauthenticated checkout, or production deployment.",),
        (
            "Checkout is accessible only in local/test mock profile and covers success/failure/unknown.",
            "Amounts retain explicit currency and dashboard data comes from the test database.",
            "Nyan can repeat the documented demo without credentials.",
        ),
        (
            "Browser E2E, bot transport, access-control, currency, duplicate callback, and full mock-stack tests.",
        ),
        (
            "src/nyan_shop_bot/**",
            "admin/**",
            "tests/e2e/**",
            "shared files only through coordinator",
        ),
    ),
    IssueSpec(
        "NSB-030",
        "Deploy tested mock images to staging",
        "M3 — Staging and live readiness",
        "release-backend",
        "high",
        "p2",
        ("release", "ci"),
        ("NSB-021",),
        "Deploy exact tested image digests to an owner-provided staging target.",
        (
            "Authenticated ingress, health/smoke, serial deploy, release log, rollback, and safe migration strategy.",
        ),
        ("Production deployment, mutable untested tags, or inventing a host/domain/secret.",),
        (
            "Target and staging secrets are explicitly owner-provided.",
            "Deployed digest matches a gated commit and rollback is demonstrated.",
            "Release remains mock-only and access controlled.",
        ),
        ("Staging health/smoke, digest match, rollback rehearsal, and migration safety evidence.",),
        ("deploy/**", ".github/workflows/** only through coordinator", "staging runbook"),
    ),
    IssueSpec(
        "NSB-031",
        "Live readiness, Stars test, and supplier conformance",
        "M3 — Staging and live readiness",
        "coordinator",
        "high",
        "p2",
        ("release", "supplier", "bot"),
        ("NSB-011", "NSB-012", "NSB-013", "NSB-021"),
        "Collect evidence for an owner decision; acceptance does not itself authorize live money.",
        (
            "Source evidence, retry/unknown semantics, secret separation, backup/restore, Stars test environment, spend caps, allowlists, and kill switch.",
        ),
        (
            "Production purchase/payment, bypassing Telegram Stars, or storing live keys in GitHub Actions.",
        ),
        (
            "Every supplier capability has conformance evidence or remains disabled.",
            "Distribution permission, capital/settlement, and payment decisions are approved by Nyan.",
            "Backup/restore and spend-control evidence is reviewable before any live enablement issue.",
        ),
        (
            "Supplier conformance, Stars test-environment, secret isolation, backup/restore, and failure-mode evidence.",
        ),
        (
            "docs/readiness/**",
            "tests/conformance/**",
            "configuration changes only through separately approved scope",
        ),
    ),
    IssueSpec(
        "NSB-040",
        "Durable local agent orchestrator and owner-gated merge controls",
        "M4 — Unattended agent dispatch",
        "coordinator",
        "high",
        "p0",
        ("agents", "ci"),
        ("NSB-001",),
        "Build and prove a durable local orchestrator while keeping merge enablement owner-gated.",
        (
            "Committed trusted task specs, real Codex/Antigravity CLI adapters, durable runs/claims/events, separate worktrees, exact-SHA CI/review, resume, controls, and bounded fix loops/usage.",
            "One real no-money task plus a deterministic CHANGES_REQUESTED fixture.",
        ),
        (
            "Production deployment, live money, copying login tokens into Actions, GUI automation, or self-approval of runner/policy/workflow changes.",
        ),
        (
            "Worker/reviewer outputs are schema validated and bound to the current exact HEAD.",
            "At most two writers, three fix rounds, bounded invocations/time/tokens, and backoff without model polling are enforced.",
            "Start/status/pause/resume/stop work from durable state without duplicate issue/PR creation.",
            "Auto-merge remains blocked because GitHub cannot atomically bind both reviewed head and base; every PASS stops at READY_FOR_OWNER.",
        ),
        (
            "Schema, claim, resume, stale-SHA, protected-path, limits, backoff, no-secret, and CHANGES_REQUESTED fixture tests.",
            "Full verification plus real issue/PR/Actions/reviewer evidence.",
        ),
        (
            "src/nyan_shop_bot/orchestrator/**",
            "scripts/agent_runner.py and focused tests/fixtures/task specs",
            "agent operation documentation and policy owned by coordinator",
        ),
    ),
    IssueSpec(
        "NSB-041",
        "Prove runner with a no-money operator quickstart",
        "M4 — Unattended agent dispatch",
        "backend",
        "low",
        "p0",
        ("agents",),
        ("NSB-040",),
        "Exercise the real runner with one bounded documentation task.",
        (
            "A Codex worker adds only docs/runner-demo.md with accurate control commands and mock-only boundaries.",
        ),
        (
            "Runner/workflow/policy changes, auto-merge, deployment, or claims that Antigravity generated the document.",
        ),
        (
            "Only the declared document changes and uses placeholders rather than invented IDs.",
            "Exact-HEAD ci-gate and independent reviewer PASS are persisted by the runner.",
        ),
        ("Security policy and command-help checks, followed by the real PR ci-gate.",),
        ("docs/runner-demo.md",),
    ),
)


def validate_issue_specs() -> None:
    """Catch accidental string-as-sequence issue fields before any GitHub mutation."""

    tuple_fields = (
        "areas",
        "dependencies",
        "scope",
        "out_of_scope",
        "acceptance",
        "tests",
        "files",
    )
    for spec in ISSUES:
        for field in tuple_fields:
            value = getattr(spec, field)
            if not isinstance(value, tuple) or any(not isinstance(item, str) for item in value):
                raise TypeError(f"{spec.code}.{field} must be a tuple of strings")


def gh(*arguments: str, input_value: dict[str, Any] | None = None) -> Any:
    executable = shutil.which("gh")
    if executable is None:
        raise RuntimeError("gh CLI is required")
    completed = subprocess.run(
        (executable, *arguments),
        cwd=ROOT,
        input=json.dumps(input_value) if input_value is not None else None,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    if not completed.stdout.strip():
        return None
    return json.loads(completed.stdout)


def api(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    arguments = ["api", "--method", method, path]
    if payload is not None:
        arguments.extend(("--input", "-"))
    return gh(*arguments, input_value=payload)


def ensure_labels() -> None:
    existing = {item["name"] for item in api("GET", f"repos/{REPOSITORY}/labels?per_page=100")}
    for name, (color, description) in LABELS.items():
        payload = {"new_name": name, "color": color, "description": description}
        if name in existing:
            api("PATCH", f"repos/{REPOSITORY}/labels/{quote(name, safe='')}", payload)
        else:
            api(
                "POST",
                f"repos/{REPOSITORY}/labels",
                {"name": name, "color": color, "description": description},
            )


def ensure_milestones() -> dict[str, int]:
    existing = {
        item["title"]: item
        for item in api("GET", f"repos/{REPOSITORY}/milestones?state=all&per_page=100")
    }
    mapping: dict[str, int] = {}
    for title, description in MILESTONES.items():
        milestone = existing.get(title)
        if milestone is None:
            milestone = api(
                "POST",
                f"repos/{REPOSITORY}/milestones",
                {"title": title, "description": description, "state": "open"},
            )
        elif milestone["description"] != description or milestone["state"] != "open":
            milestone = api(
                "PATCH",
                f"repos/{REPOSITORY}/milestones/{milestone['number']}",
                {"description": description, "state": "open"},
            )
        mapping[title] = int(milestone["number"])
    return mapping


def render_body(
    spec: IssueSpec,
    urls: dict[str, str],
    *,
    base_sha: str,
    branch: str,
    run_id: str,
) -> str:
    if spec.dependencies:
        dependencies = "\n".join(f"- [{code}]({urls[code]})" for code in spec.dependencies)
    else:
        dependencies = "- None — root foundation issue."

    def checklist(items: tuple[str, ...]) -> str:
        return "\n".join(f"- [ ] {item}" for item in items)

    def bullets(items: tuple[str, ...]) -> str:
        return "\n".join(f"- {item}" for item in items)

    claim = ""
    if spec.code == "NSB-001":
        claim = f"""
## Active claim

- Owner role: `coordinator` (role label; no fake GitHub assignee)
- Run ID: `{run_id}`
- Branch: `{branch}`
- Base SHA: `{base_sha}`
- State: active until the bootstrap PR is merged/closed or explicitly released
"""

    return f"""<!-- nyan-task:{spec.code} -->
# Objective

{spec.objective}

## Scope

{bullets(spec.scope)}

### Out of scope

{bullets(spec.out_of_scope)}

## Dependencies

{dependencies}

## Ownership and risk

- Owner role: `{spec.owner}`
- Risk: `{spec.risk}`
- Priority: `{spec.priority}`
- GitHub assignee: intentionally empty; AI roles are labels, not GitHub accounts
{claim}
## Acceptance criteria

{checklist(spec.acceptance)}

## Required tests

{checklist(spec.tests)}

## Allowed files / module boundary

{bullets(spec.files)}

## Completion evidence

- [ ] Exact implementation HEAD SHA and base SHA
- [ ] Commands actually run with pass/fail/NOT RUN distinguished
- [ ] Pull request and GitHub Actions URLs
- [ ] Remaining risks, blockers, and rollback/migration notes where relevant

Do not close this issue merely because a PR was opened. Live credentials, money operations, production deployment, gate weakening, and automatic merge are not authorized by this issue.
"""


def existing_issues() -> dict[str, dict[str, Any]]:
    values = api("GET", f"repos/{REPOSITORY}/issues?state=all&per_page=100")
    mapping: dict[str, dict[str, Any]] = {}
    for issue in values:
        if "pull_request" in issue:
            continue
        body = issue.get("body") or ""
        title = issue.get("title") or ""
        for spec in ISSUES:
            if f"<!-- nyan-task:{spec.code} -->" in body or spec.code in title:
                mapping.setdefault(spec.code, issue)
    return mapping


def ensure_issues(
    milestones: dict[str, int],
    *,
    base_sha: str,
    branch: str,
    run_id: str,
) -> dict[str, str]:
    existing = existing_issues()
    urls = {code: issue["html_url"] for code, issue in existing.items()}

    # Establish every stable URL before rendering dependency links. This also
    # supports intentionally accelerated work whose NSB code sorts after its
    # dependent issue (for example NSB-010 depending on NSB-040).
    for spec in ISSUES:
        if spec.code in existing:
            continue
        labels = {
            f"agent:{'ui' if spec.owner == 'ui-antigravity' else 'coordinator' if spec.owner == 'coordinator' else 'backend'}",
            "status:backlog",
            f"risk:{spec.risk}",
            f"priority:{spec.priority}",
            *(f"area:{area}" for area in spec.areas),
        }
        current = api(
            "POST",
            f"repos/{REPOSITORY}/issues",
            {
                "title": f"[{spec.code}] {spec.title}",
                "body": f"<!-- nyan-task:{spec.code} -->\nMetadata seed in progress.",
                "milestone": milestones[spec.milestone],
                "labels": sorted(labels),
            },
        )
        existing[spec.code] = current
        urls[spec.code] = current["html_url"]

    for spec in ISSUES:
        current = existing.get(spec.code)
        current_labels = {label["name"] for label in (current.get("labels", []) if current else [])}
        status_labels = {label for label in current_labels if label.startswith("status:")}
        if not status_labels:
            status_labels = {"status:in-progress" if spec.code == "NSB-001" else "status:backlog"}
        labels = (
            current_labels
            | status_labels
            | {
                f"agent:{'ui' if spec.owner == 'ui-antigravity' else 'coordinator' if spec.owner == 'coordinator' else 'backend'}",
                f"risk:{spec.risk}",
                f"priority:{spec.priority}",
                *(f"area:{area}" for area in spec.areas),
            }
        )
        title = f"[{spec.code}] {spec.title}"

        if current is None:
            raise RuntimeError(f"issue pre-seed failed for {spec.code}")

        body = render_body(
            spec,
            urls,
            base_sha=base_sha,
            branch=branch,
            run_id=run_id,
        )
        updated = api(
            "PATCH",
            f"repos/{REPOSITORY}/issues/{current['number']}",
            {
                "title": title,
                "body": body,
                "milestone": milestones[spec.milestone],
                "labels": sorted(labels),
            },
        )
        urls[spec.code] = updated["html_url"]
    return urls


def git_value(*arguments: str) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Apply changes to GitHub")
    parser.add_argument("--run-id", default="phase0-20260919-local")
    args = parser.parse_args()

    validate_issue_specs()

    base_sha = git_value("merge-base", "HEAD", "origin/main")
    branch = git_value("branch", "--show-current")
    if not args.apply:
        print(
            json.dumps(
                {
                    "repository": REPOSITORY,
                    "base_sha": base_sha,
                    "branch": branch,
                    "labels": len(LABELS),
                    "milestones": list(MILESTONES),
                    "issues": [issue.code for issue in ISSUES],
                    "mode": "dry-run",
                },
                indent=2,
            )
        )
        return 0

    ensure_labels()
    milestones = ensure_milestones()
    urls = ensure_issues(
        milestones,
        base_sha=base_sha,
        branch=branch,
        run_id=args.run_id,
    )
    print(json.dumps({"repository": REPOSITORY, "issues": urls}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
