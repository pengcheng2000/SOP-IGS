# PROJECT_STATE.md

## Development Stage

V1 local MVP implemented; production hardening and business acceptance remain.

Canonical source repository: https://github.com/pengcheng2000/SOP-IGS (public).

## Current Architecture

* React/Vite SPA served through the FastAPI deployment.
* FastAPI + SQLAlchemy API with PostgreSQL production configuration and SQLite development fallback.
* Local filesystem blob storage behind a bounded storage adapter.
* Database-backed, single-consumer document task queue.
* Deterministic Pillow/OOXML generation followed by isolated Microsoft Word COM finalization.
* Optional OpenAI-compatible AI advisory path; all core operations work without it.

## Technology Stack

* React, TypeScript, Ant Design, TanStack Query, dnd-kit.
* Python 3.11, FastAPI, Pydantic, SQLAlchemy, Alembic.
* lxml, Pillow, pillow-heif, pywin32.
* PostgreSQL, Caddy, Windows Task Scheduler/WinSW for production.

## Confirmed Decisions

* V1 supports only the versioned liquid-cooled outdoor cabinet DOCX template.
* Stable test-item IDs are independent of generated display numbers.
* Parent selection is derived from selected leaves; retained chapters are renumbered continuously.
* Photos retain user order, are separated by template/custom photo groups, and are placed as inline images in deterministic tables.
* Historical photo-bearing tables are removed from the sanitized master; each test item rebuilds one bordered evidence table from its non-empty photo groups.
* Photo completeness is tiered: explicit "at least include" evidence is required; recommended evidence needs acknowledgement; optional evidence never blocks.
* LLM output is advisory, schema-validated, and never required for DOCX generation.
* Production runs on a dedicated, logged-in Windows account with one Word Worker.
* Local authentication uses provider identities so Feishu `open_id` can be added later.

## Completed Major Modules

* Versioned source and sanitized master template with manifest and cleaning rules.
* Test catalog, tree selection, continuous numbering, project and photo domain models.
* Local login, session/CSRF protection, admin user API, and audit events.
* Image normalization for JPEG/PNG/HEIC and deterministic layout planning.
* OOXML chapter deletion, summary-table rebuild, field mapping, photo injection, and validation.
* Database task worker with isolated Word COM subprocess, timeout, field/TOC update, and heading-number verification.
* Project, selection, photo, preflight, generation, download, and AI advisory APIs.
* Responsive internal Web workflow and Windows deployment examples.
* Automated unit/API/DOCX tests and nine-case Word PoC matrix.
* Template-defined and custom photo groups, drag/drop upload, cross-group moves, grouped DOCX layouts, and required-photo validation.
* Durable generation progress events, Word heartbeat diagnostics, UTC-safe timestamps, and local-time display.
* Official CHINT-derived green wordmark and favicon, plus laptop/mobile responsive login layout.
* Case-compatible `single/4/auto` borders for every generated image table, with six-column logical layout supporting 1/2/3-column rows.
* Project sample photos have three recommended groups (front closed/open/diagonal, 1/1/2 photos) under section 4.3, separate from selectable tests. PhotoGroup scope is database-constrained; legacy test groups migrate without moving files.
* Generic test-photo headings are outside evidence tables and kept with the first photo row; business/custom group titles remain in table rows.
* Word TOC number separators are normalized to one space after the last full field update, preserving hyperlink fields and the page-number tab.
* Test-item selection uses only the in-header auto-save state; step navigation flushes pending debounced saves without an overlay footer.

## Current Issues / Risks

* The sanitized master still requires domain-owner review of all historical measured-data cells and project-specific paragraphs before production approval.
* The required 100-job Word COM soak test has not yet been run on the final production machine.
* Production PostgreSQL, TLS certificate, backup credentials, and Word licensing are not configured in the repository; the real LLM endpoint is configured locally and verified.
* Microsoft Word COM remains an operational risk and must stay isolated to the dedicated interactive worker account.

## Current Focus

Business review of `master.docx`, target-machine deployment, 100-job soak testing, and UAT with real grouped project photos.
