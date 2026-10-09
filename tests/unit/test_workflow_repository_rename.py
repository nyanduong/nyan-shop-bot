"""A renamed repository must remain inside the trusted publication boundary."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_publish_policy_accepts_new_owner_and_rejects_previous_namespace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = importlib.util.spec_from_file_location(
        "rename_security_policy", REPOSITORY_ROOT / "scripts" / "security_policy.py"
    )
    assert spec is not None and spec.loader is not None
    policy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(policy)
    monkeypatch.setattr(policy, "WORKFLOW_DIR", tmp_path)
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    candidate = tmp_path / "ci.yml"
    candidate.write_text(workflow, encoding="utf-8")
    assert policy.check_workflows() == []

    candidate.write_text(
        workflow.replace("nyanduong/nyan-shop-bot", "NhanDuong21/nyan-shop-bot"),
        encoding="utf-8",
    )
    assert policy.check_workflows() == [
        "ci.yml: publish condition missing 'nyanduong/nyan-shop-bot'"
    ]
