# PROJECT_STATE.md

## Development Stage

V1 local MVP implemented for two product types (工商业柜 liquid-cooled cabinet, 升压一体机 boost-integrated unit); production hardening and business acceptance remain.

Canonical source repository: https://github.com/pengcheng2000/SOP-IGS (public).

## Current Architecture

* React/Vite SPA served through the FastAPI deployment.
* FastAPI + SQLAlchemy API with PostgreSQL production configuration and SQLite development fallback.
* Local filesystem blob storage behind a bounded storage adapter.
* Database-backed, single-consumer document task queue.
* Two products with isolated implementations. 工商业柜 (cabinet) is the original code (`api/projects|photos|generation|advice`, `services/docx/generator.py`, `worker/word_worker.run_task`). 升压一体机 (boost) lives entirely in `backend/app/boost/` (own settings `SOP_BOOST_*`, tables `boost_*`, `/api/boost` router, OOXML helpers, builder, validator, worker handler) and `frontend/src/features/boost/`.
* Shared only: login/accounts, the project list page (product chosen in the create dialog; lists merged on the frontend), the `templates` registry table, the Word COM runner, image normalization, blob storage, and the single Word worker process. Hook points: `main.py` (boost router + `bootstrap_boost()`), `word_worker.main()` (polls the boost queue when the cabinet queue is empty), `App.tsx` project list.
* Deterministic Pillow/OOXML generation followed by isolated Microsoft Word COM finalization.
* Optional OpenAI-compatible AI advisory path; all core operations work without it.

## Technology Stack

* React, TypeScript, Ant Design, TanStack Query, dnd-kit.
* Python 3.11, FastAPI, Pydantic, SQLAlchemy, Alembic.
* lxml, Pillow, pillow-heif, openpyxl, pywin32.
* PostgreSQL, Caddy, Windows Task Scheduler/WinSW for production.

## Confirmed Decisions

* Cabinet behaviour is unchanged by the boost work: tick test items from the fixed catalog, upload grouped photos, generate from the versioned cabinet template.
* Boost projects: no test-item selection and no photo upload. Users upload a 测试项分类表 workbook; each sheet becomes a 5.x chapter of the boost master (`templates/boost-integrated-unit/v1`), images come from the workbook, and the workbook wording wins over older case documents. Fixed chapters (适用范围、参考文献、调试环境、工装仪器、5.1 注意事项) stay in the master; only manifest-declared fields are substituted (`boost_projects.fields`, plus document number/version columns). A broken boost template disables only 升压一体机, never cabinet startup.
* The boost master is derived reproducibly by `tools/build_boost_master.py` from a case document (kept out of git); it tokenizes title, scope, references, both title-block text-box copies and the revision history, fixes chapter-5 numbering to one continuous list (heading numbers use the case's SimSun numbering look), pins the vertical file-name text box to the page (the case anchored it to a paragraph, so longer content pushed its label off the page), and verifies that replaced case text no longer appears. Body text uses the case's dominant layout (1.5 line spacing, two-character first-line indent); indented paragraphs under list items are their own prototype. Fields: the archive month is a `YYYY-MM` month picker, and the reference field shows the standard references already in the master.
* Boost workbook parsing is split into a spec-independent reader (`boost/input/workbook.py`, images read from drawing parts with anchor cell and displayed size) and the only spec-dependent interpreter (`boost/input/interpreter.py`, `PARSER_VERSION=v1`). Uploads (`boost_source_files`) are immutable; the newest is current and its parsed model is copied into the generation snapshot. Table column widths follow the text length (like Word auto-fit), not the Excel column widths.
* Stable test-item IDs are independent of generated display numbers.
* Parent selection is derived from selected leaves; retained chapters are renumbered continuously.
* Photos retain user order, are separated by template/custom photo groups, and are placed as inline images in deterministic tables.
* Historical photo-bearing tables are removed from the sanitized master; each test item rebuilds one bordered evidence table from its non-empty photo groups.
* Photo completeness is tiered: explicit "at least include" evidence is required; recommended evidence needs acknowledgement; optional evidence never blocks.
* LLM output is advisory, schema-validated, and never required for DOCX generation.
* Production runs on a dedicated, logged-in Windows account with one Word Worker.
* Authentication: Feishu SSO via a QR code embedded on the login page (LarkSSOSDKWebQRCode from Feishu CDN, with a web-redirect fallback); identity is `open_id`; OAuth state is HMAC-signed and bound to a browser cookie (15-minute TTL). Any employee in the Feishu app's availability scope is auto-provisioned as an active `user` with no approval step. Admins can promote or disable accounts; `SOP_FEISHU_ADMIN_OPEN_IDS` auto-grants admin. Local password login remains only as the admin fallback.
* Deployment access is plain intranet HTTP at `http://10.122.3.224:8010` (port 8000 belongs to another project): the API service binds `0.0.0.0:8010`, `SOP_PUBLIC_BASE_URL` fixes the Feishu redirect URI, and production config permits insecure cookies only when that URL is explicitly `http://`. Caddy/HTTPS is optional for later.
* Projects are private to their creator (`projects.created_by`), including for admins; every project, photo-group, photo, generation and document endpoint returns 404 for other users. Admins manage accounts, not other users' projects.
* Users change their own password from the header; a change revokes the user's other login sessions.

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
* Boost product end to end as a standalone module: master + manifest, workbook reader/interpreter, upload/preview/preflight/generation/download/template-approval API, own generation queue handled by the shared Word worker, standalone workspace UI. Verified with Word (continuous 5.x.y.z numbering, list restarts, merged tables, cell images, title-block fields, total page count in the text box via per-shape field update). The standard template `templates/boost-integrated-unit/v1/input-template.xlsx` is derived by `tools/build_boost_input_template.py` from the case Excel (wording wins) plus the case Word (layout of every row); generating from it matches the case Word structure item by item except for content that exists in only one of the two. A workbook with no 格式 marker is rejected with guidance to download the template. The boost Word subprocess writes to temp files (a Windows pipe holds only 4 KB) and boost validation ignores the duplicate drawing ids Word writes inside `mc:Fallback`; the cabinet path keeps its original behaviour.

## Current Issues / Risks

* The sanitized master still requires domain-owner review of all historical measured-data cells and project-specific paragraphs before production approval.
* The required 100-job Word COM soak test has not yet been run on the final production machine.
* Production PostgreSQL, backup credentials, and Word licensing are not configured in the repository; the real LLM endpoint is configured locally and verified.
* Microsoft Word COM remains an operational risk and must stay isolated to the dedicated interactive worker account.
* The boost input spec (v1: column J 「格式」 with `+` for several items per row; column A = 三级标题, or content when a format is set and B–I are empty) is implemented and documented in the template's 填写说明 sheet, but the business has not confirmed it. The template keeps the case project's parameter values (time zone, power, IP tables) as editable examples.
* The boost master (title-block fields, fixed chapters, reference list) needs business review and approval before production use.

## Current Focus

Business review of both masters, agreeing the boost workbook spec with the user department, target-machine deployment, 100-job soak testing, and UAT.
