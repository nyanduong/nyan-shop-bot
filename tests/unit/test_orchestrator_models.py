from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from nyan_shop_bot.orchestrator.models import (
    Budget,
    ReviewResult,
    TaskSpec,
    Usage,
    UsageNormalization,
    WorkerResult,
)


def task_data() -> dict[str, object]:
    return {
        "schema_version": 1,
        "task_id": "NSB-041",
        "issue_number": 15,
        "issue_url": "https://github.com/nyanduong/nyan-shop-bot/issues/15",
        "repository": "nyanduong/nyan-shop-bot",
        "title": "Runner proof",
        "base_ref": "nyan/nsb-040-agent-runner",
        "pr_base": "nyan/nsb-040-agent-runner",
        "branch": "nyan/nsb-041-runner-proof",
        "worker": "codex",
        "role": "backend",
        "risk": "low",
        "queue_phase": "demo",
        "queue_eligible": False,
        "trusted_prompt": "Create the bounded runner proof document and nothing else.",
        "acceptance_criteria": ["Document all control commands."],
        "allowed_paths": ["docs/runner-demo.md"],
        "required_checks": ["ci-gate"],
        "dependencies": [],
        "auto_merge_eligible": False,
        "budget": {
            "max_agent_invocations": 5,
            "max_total_tokens": 100000,
            "max_elapsed_seconds": 3600,
            "max_fix_rounds": 3,
            "ci_timeout_seconds": 1200,
            "poll_initial_seconds": 2,
            "poll_max_seconds": 30,
        },
    }


def test_task_spec_rejects_silent_ui_worker_substitution() -> None:
    value = task_data()
    value.update({"role": "ui", "worker": "codex"})

    with pytest.raises(ValidationError, match="map to each other exactly"):
        TaskSpec.model_validate(value)


def test_ui_task_rejects_admin_wide_scope_before_adapter_launch() -> None:
    value = task_data()
    value.update(
        {
            "worker": "antigravity",
            "worker_model": "gemini-3.8-flash-low",
            "role": "ui",
            "allowed_paths": ["admin/**"],
        }
    )

    with pytest.raises(ValidationError, match="admin/src/features"):
        TaskSpec.model_validate(value)


@pytest.mark.parametrize(
    "allowed_paths",
    [
        ["admin/src/features/**"],
        ["admin/src/features/*/**"],
        [
            "admin/src/features/catalog-proof/**",
            "admin/src/features/second-proof/**",
        ],
    ],
)
def test_ui_task_rejects_broad_or_multi_root_grants(allowed_paths: list[str]) -> None:
    value = task_data()
    value.update(
        {
            "worker": "antigravity",
            "worker_model": "gemini-3.8-flash-low",
            "role": "ui",
            "allowed_paths": allowed_paths,
        }
    )

    with pytest.raises(ValidationError, match="one exact"):
        TaskSpec.model_validate(value)


def test_antigravity_worker_requires_ui_role_and_pinned_model() -> None:
    backend = task_data()
    backend.update({"worker": "antigravity", "worker_model": "gemini-3.8-flash-low"})
    with pytest.raises(ValidationError, match="map to each other exactly"):
        TaskSpec.model_validate(backend)

    unpinned = task_data()
    unpinned.update(
        {
            "worker": "antigravity",
            "role": "ui",
            "allowed_paths": ["admin/src/features/catalog-proof/**"],
        }
    )
    with pytest.raises(ValidationError, match="pin a discovered"):
        TaskSpec.model_validate(unpinned)


def test_task_spec_rejects_untrusted_path_escape() -> None:
    value = task_data()
    value["allowed_paths"] = ["../outside"]

    with pytest.raises(ValidationError, match="unsafe allowed path"):
        TaskSpec.model_validate(value)


def test_worker_success_requires_tests_and_exact_shape() -> None:
    with pytest.raises(ValidationError, match="test evidence"):
        WorkerResult.model_validate(
            {
                "status": "SUCCESS",
                "issue": 15,
                "branch": "nyan/nsb-041-runner-proof",
                "head_sha": "a" * 40,
                "changed_files": ["docs/runner-demo.md"],
                "tests": [],
                "blockers": [],
                "summary": "done",
            }
        )


def test_review_pass_cannot_hide_findings() -> None:
    with pytest.raises(ValidationError, match="PASS cannot include"):
        ReviewResult.model_validate(
            {
                "verdict": "PASS",
                "reviewed_head_sha": "a" * 40,
                "findings": [
                    {
                        "severity": "low",
                        "file": None,
                        "line": None,
                        "message": "unresolved",
                        "evidence": "present",
                    }
                ],
                "tests": [],
                "blockers": [],
                "summary": "incorrect pass",
            }
        )


def test_review_pass_cannot_hide_failed_test_evidence() -> None:
    with pytest.raises(ValidationError, match="PASS cannot include a failed test"):
        ReviewResult.model_validate(
            {
                "verdict": "PASS",
                "reviewed_head_sha": "a" * 40,
                "findings": [],
                "tests": [
                    {
                        "command": "pytest",
                        "result": "FAIL",
                        "evidence": "One regression failed.",
                    }
                ],
                "blockers": [],
                "summary": "incorrect pass",
            }
        )


def test_generated_schemas_forbid_unknown_fields() -> None:
    worker_schema = WorkerResult.model_json_schema()
    review_schema = ReviewResult.model_json_schema()

    assert worker_schema["additionalProperties"] is False
    assert review_schema["additionalProperties"] is False
    finding_schema = review_schema["$defs"]["Finding"]
    assert set(finding_schema["required"]) == {
        "severity",
        "file",
        "line",
        "message",
        "evidence",
    }


def test_nsb_011_fixture_preserves_raw_values_and_derives_policy_tokens() -> None:
    fixture = Path("tests/fixtures/orchestrator/nsb_011_usage.json")
    raw = json.loads(fixture.read_text(encoding="utf-8"))
    usage = Usage(
        raw_input_tokens=raw["input_tokens"],
        cached_input_tokens=raw["cached_input_tokens"],
        raw_output_tokens=raw["output_tokens"],
        reasoning_tokens=raw["reasoning_output_tokens"],
    )

    normalized = usage.normalize_codex()

    assert raw == {
        "input_tokens": 2_589_292,
        "cached_input_tokens": 2_407_168,
        "output_tokens": 9_451,
        "reasoning_output_tokens": 4_843,
    }
    assert normalized.raw_input_tokens == 2_589_292
    assert normalized.cached_input_tokens == 2_407_168
    assert normalized.raw_output_tokens == 9_451
    assert normalized.reasoning_tokens == 4_843
    assert normalized.fresh_input_tokens == 182_124
    assert normalized.enforceable_tokens == 191_575
    assert normalized.normalization_state is UsageNormalization.COMPLETE


@pytest.mark.parametrize(
    ("values", "message"),
    [
        (
            {"raw_input_tokens": 3, "cached_input_tokens": 4},
            "cached input tokens cannot exceed input tokens",
        ),
        (
            {"raw_output_tokens": 3, "reasoning_tokens": 4},
            "reasoning tokens cannot exceed output tokens",
        ),
    ],
)
def test_usage_rejects_invalid_subset_relationships(values: dict[str, int], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Usage.model_validate(values)


def test_codex_raw_total_is_audit_only_and_missing_fields_stay_nullable() -> None:
    complete = Usage(
        raw_input_tokens=10,
        cached_input_tokens=4,
        raw_output_tokens=3,
        reasoning_tokens=2,
        raw_provider_total=999,
    ).normalize_codex()
    partial = Usage(raw_input_tokens=10, raw_provider_total=10).normalize_codex()
    unknown = Usage().normalize_codex()

    assert complete.raw_provider_total == 999
    assert complete.enforceable_tokens == 9
    assert partial.normalization_state is UsageNormalization.PARTIAL
    assert partial.cached_input_tokens is None
    assert partial.enforceable_tokens is None
    assert unknown.normalization_state is UsageNormalization.UNKNOWN
    assert unknown.raw_input_tokens is None
    assert unknown.enforceable_tokens is None


def test_role_token_ceilings_override_or_fall_back_to_legacy_total() -> None:
    legacy = Budget(max_total_tokens=123_000)
    split = Budget(
        max_total_tokens=123_000,
        max_worker_tokens=200_000,
        max_reviewer_tokens=50_000,
    )

    assert legacy.token_ceiling("worker") == 123_000
    assert legacy.token_ceiling("reviewer") == 123_000
    assert split.token_ceiling("worker") == 200_000
    assert split.token_ceiling("reviewer") == 50_000
