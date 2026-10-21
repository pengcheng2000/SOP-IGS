"""Template approval is decided in development and shipped in the manifest, never by a step on the server."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import Template

LOGGER = logging.getLogger(__name__)


def apply_manifest_approval(template: Template, manifest: dict, master_sha256: str) -> None:
    """Make the template status follow the manifest's `approved_master_sha256`.

    The master the business reviewed is identified by its hash: while the hash matches the master in use the
    template is approved, and a changed master falls back to review_required until the manifest is updated.
    A manifest without the key leaves the status alone (manual approval through the admin API still works).
    """
    approved = manifest.get("approved_master_sha256")
    if not approved:
        return
    if approved == master_sha256:
        if template.status != "approved":
            LOGGER.info("Template %s approved by manifest", template.key)
            template.status = "approved"
    elif template.status == "approved":
        LOGGER.warning("Template %s master changed since approval; back to review_required", template.key)
        template.status = "review_required"
