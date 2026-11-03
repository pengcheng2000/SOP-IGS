"""Keep cabinet-plan registry metadata aligned with a validated live manifest."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..services.template_approval import apply_manifest_approval

if TYPE_CHECKING:
    from ..models import Template


def apply_template_manifest(template: Template, manifest: dict) -> None:
    """Update within the caller's transaction; never carry approval to a new hash."""
    if template.master_sha256 != manifest["master_sha256"]:
        template.status = "review_required"
    template.source_sha256 = manifest["source_sha256"]
    template.master_sha256 = manifest["master_sha256"]
    template.manifest_version = manifest["manifest_version"]
    apply_manifest_approval(template, manifest, manifest["master_sha256"])
