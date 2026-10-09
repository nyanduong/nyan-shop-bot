"""Fail-closed repository secret and GitHub Actions policy checks."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"

SECRET_PATTERNS = {
    "AWS access key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "GitHub token": re.compile(r"gh(?:p|o|u|s|r)_[A-Za-z0-9]{30,}"),
    "OpenAI-style key": re.compile(r"sk-[A-Za-z0-9]{20,}"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "VietShare live secret": re.compile(r"vs_live_(?!YOUR_SECRET)[A-Za-z0-9_-]{12,}"),
}
LOCKFILE_NAMES = {"package-lock.json", "requirements.lock", "requirements-dev.lock"}
FORBIDDEN_WORKFLOW_TEXT = (
    "pull_request_target",
    "workflow_run",
    "issue_comment",
    "self-hosted",
    "continue-on-error: true",
    "secrets.",
)


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [ROOT / raw.decode() for raw in result.stdout.split(b"\0") if raw]


def scan_paths(paths: list[Path]) -> list[str]:
    findings: list[str] = []
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        if relative.startswith("nyan-bootstrap/"):
            findings.append(f"private bootstrap input is tracked: {relative}")
        if path.name.startswith(".env") and path.name != ".env.example":
            findings.append(f"local environment file is tracked: {relative}")
        if relative.startswith("secrets/"):
            findings.append(f"secret directory content is tracked: {relative}")
        if path.name in LOCKFILE_NAMES or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{label} pattern found in {relative}")
    return findings


def load_workflow(path: Path) -> dict[str, Any]:
    value = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    if not isinstance(value, dict):
        raise ValueError(f"workflow is not a mapping: {path.name}")
    return value


def check_workflows() -> list[str]:
    findings: list[str] = []
    workflows = sorted((*WORKFLOW_DIR.glob("*.yml"), *WORKFLOW_DIR.glob("*.yaml")))
    if not workflows:
        return ["no GitHub Actions workflow found"]

    action_reference = re.compile(r"^\s*uses:\s*([^\s#]+)", re.MULTILINE)
    pinned_action = re.compile(r"^[^/\s]+/[^/@\s]+@[0-9a-f]{40}$")

    for path in workflows:
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        for forbidden in FORBIDDEN_WORKFLOW_TEXT:
            if forbidden in lowered:
                findings.append(f"{path.name}: forbidden workflow text {forbidden!r}")
        for reference in action_reference.findall(text):
            if reference.startswith("./"):
                continue
            if not pinned_action.fullmatch(reference):
                findings.append(f"{path.name}: action is not pinned to a full SHA: {reference}")

        workflow = load_workflow(path)
        permissions = workflow.get("permissions")
        if permissions != {"contents": "read"}:
            findings.append(f"{path.name}: top-level permissions must be contents: read")
        triggers = workflow.get("on")
        if (
            not isinstance(triggers, dict)
            or "pull_request" not in triggers
            or "push" not in triggers
        ):
            findings.append(f"{path.name}: workflow must run for pull_request and push")

        jobs = workflow.get("jobs")
        if not isinstance(jobs, dict):
            findings.append(f"{path.name}: jobs must be a mapping")
            continue
        gate = jobs.get("ci-gate")
        if not isinstance(gate, dict):
            findings.append(f"{path.name}: missing ci-gate job")
        elif "always()" not in str(gate.get("if", "")):
            findings.append(f"{path.name}: ci-gate must use always()")
        else:
            required_needs = {
                "python-quality",
                "python-tests",
                "database",
                "frontend",
                "security",
                "docker-build",
                "mock-smoke",
            }
            needs = gate.get("needs")
            if not isinstance(needs, list) or set(needs) != required_needs:
                findings.append(f"{path.name}: ci-gate needs do not match mandatory jobs")
        publish = jobs.get("publish")
        if not isinstance(publish, dict):
            findings.append(f"{path.name}: missing trusted-main publish job")
        else:
            publish_permissions = publish.get("permissions")
            if publish_permissions != {"contents": "read", "packages": "write"}:
                findings.append(f"{path.name}: publish permissions must be minimal")
            condition = str(publish.get("if", ""))
            for required in ("push", "refs/heads/main", "nyanduong/nyan-shop-bot"):
                if required not in condition:
                    findings.append(f"{path.name}: publish condition missing {required!r}")
    return findings


def check_impeccable_payload() -> list[str]:
    completed = subprocess.run(
        [sys.executable, "scripts/impeccable_lock.py"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        return [f"Impeccable payload verification failed: {detail}"]
    return []


def main() -> int:
    findings = scan_paths(tracked_files()) + check_workflows() + check_impeccable_payload()
    if findings:
        print("Security policy violations:")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print("Secret scan and workflow policy checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
