from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from app.services.template_approval import apply_manifest_approval

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ["liquid-cooled-cabinet", "boost-integrated-unit"]


def template(status: str) -> SimpleNamespace:
    return SimpleNamespace(key="t", status=status)


def test_matching_hash_approves() -> None:
    row = template("review_required")
    apply_manifest_approval(row, {"approved_master_sha256": "abc"}, "abc")
    assert row.status == "approved"


def test_changed_master_returns_to_review() -> None:
    row = template("approved")
    apply_manifest_approval(row, {"approved_master_sha256": "abc"}, "def")
    assert row.status == "review_required"


def test_manifest_without_approval_keeps_manual_status() -> None:
    for status in ("approved", "review_required"):
        row = template(status)
        apply_manifest_approval(row, {}, "abc")
        assert row.status == status


@pytest.mark.parametrize("name", TEMPLATES)
def test_shipped_masters_are_approved_in_manifest(name: str) -> None:
    """The reviewed hash is committed with the master, so a deployment needs no approval step."""
    directory = ROOT / "templates" / name / "v1"
    manifest = yaml.safe_load((directory / "manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["approved_master_sha256"] == hashlib.sha256((directory / "master.docx").read_bytes()).hexdigest()
