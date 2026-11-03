from types import SimpleNamespace

from app.cabinet_plan.templates import apply_template_manifest


def test_changed_master_revokes_manual_approval_and_updates_metadata():
    row = SimpleNamespace(
        key="cabinet-test-plan", master_sha256="old", status="approved"
    )
    manifest = {
        "source_sha256": "source",
        "master_sha256": "new",
        "manifest_version": "2",
    }
    apply_template_manifest(row, manifest)
    assert row.master_sha256 == "new"
    assert row.source_sha256 == "source"
    assert row.manifest_version == "2"
    assert row.status == "review_required"


def test_matching_master_keeps_manual_approval():
    row = SimpleNamespace(
        key="cabinet-test-plan", master_sha256="same", status="approved"
    )
    apply_template_manifest(
        row, {"source_sha256": "s", "master_sha256": "same", "manifest_version": "1"}
    )
    assert row.status == "approved"


def test_new_master_only_uses_its_own_explicit_manifest_approval():
    for approved, expected in [("old", "review_required"), ("new", "approved")]:
        row = SimpleNamespace(
            key="cabinet-test-plan", master_sha256="old", status="approved"
        )
        apply_template_manifest(
            row,
            {
                "source_sha256": "s",
                "master_sha256": "new",
                "manifest_version": "1",
                "approved_master_sha256": approved,
            },
        )
        assert row.status == expected
