# PROJECT_STATE.md

## Development Stage

V1 for both product types is deployed on the target Windows workstation from commit `f0023ef`. Both product masters are business-reviewed and approved; cross-machine UAT and Feishu end-to-end acceptance remain.

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
* The target deployment currently runs one Word Worker in the logged-in `chengpeng3` session; moving it to a dedicated licensed interactive account remains the long-term plan.
* The interactive Worker uses the deployment launcher `D:\SOP-IGS-Infra\Scripts\run-sop-word-worker.ps1`, Python UTF-8 mode, timestamped logs, exit-code propagation, and a five-minute recovery trigger (IgnoreNew). Upgrades disable the trigger and terminate the old Python child process tree before changing files; a scheduled-task stop alone can leave a consumer alive.
* The user-created `JianSanFang-WeeklyRestart` task was disabled by explicit request after its weekly restart logged the Worker account out. Other restart policies are unchanged.
* Authentication: Feishu SSO via a QR code embedded on the login page (LarkSSOSDKWebQRCode from Feishu CDN, with a web-redirect fallback); identity is `open_id`; OAuth state is HMAC-signed and bound to a browser cookie (15-minute TTL). Any employee in the Feishu app's availability scope is auto-provisioned as an active `user` with no approval step. Admins can promote or disable accounts; `SOP_FEISHU_ADMIN_OPEN_IDS` auto-grants admin. Local password login remains only as the admin fallback.
* The target deployment's primary intranet address is `http://10.122.3.224:8010`: FastAPI listens on `0.0.0.0:8010`, the Domain/Private firewall profiles allow TCP 8010, `SOP_PUBLIC_BASE_URL` matches that address, and secure session cookies are disabled only for this explicit HTTP URL. PostgreSQL remains loopback-only on `127.0.0.1:5432`. Caddy remains available as a compatibility proxy to the same API but is not the advertised login entry point.
* Projects are private to their creator (`projects.created_by`), including for admins; every project, photo-group, photo, generation and document endpoint returns 404 for other users. Admins manage accounts, not other users' projects.
* Users change their own password from the header; a change revokes the user's other login sessions.
* The SPA is served over plain HTTP on an intranet IP, which is not a secure context: browser APIs that require one (`crypto.randomUUID`, `crypto.subtle`, `navigator.clipboard`) must not be used in `frontend/src`; client-side ids use a counter. Upload start-up and failures are shown per file in the photo step.
* Word worker liveness: the worker writes `worker_heartbeats` every 5 s from a background thread (migration 0006); `GET /api/worker/status` reports `online` when a beat is ≤30 s old, and both generation panels (cabinet and boost) show a red "Word Worker 未启动" alert under the generate button when it is offline.
* Cabinet test items have an optional 测试结果描述 text (`project_test_items.result_note`, ≤5000 chars, auto-saved, API `GET /projects/{id}/test-result-notes`, `PUT /projects/{id}/test-items/{item}/result-note`, no revision bump). It is copied into the generation snapshot (`result_notes`) and written as paragraphs "测试结果描述：…" directly before the item's 测试结论 paragraph, with or without photos. The 基础信息 测试时间 field stays free text (`YYYY-MM-DD 至 YYYY-MM-DD`) with a date-range picker button. Boost projects are unaffected.

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
* Boost product end to end as a standalone module: master + manifest, workbook reader/interpreter, upload/preview/preflight/generation/download/template-approval API, own generation queue handled by the shared Word worker, standalone workspace UI. Verified with Word (continuous 5.x.y.z numbering, list restarts, merged tables, cell images, title-block fields, total page count in the text box via per-shape field update). The standard template `templates/boost-integrated-unit/v1/input-template.xlsx` is derived by `tools/build_boost_input_template.py` from the case Excel (wording wins) plus the case Word (layout of every row); generating from it matches the case Word structure item by item except for content that exists in only one of the two. A workbook with no 格式 marker is rejected with guidance to download the template. The boost Word subprocess writes to temp files (a Windows pipe holds only 4 KB) and boost validation ignores the duplicate drawing ids Word writes inside `mc:Fallback`; drawing ids are unique across body, headers and footers (the case master reused them, generation renumbers header/footer ids and validation checks all parts), and the master's `image/.jpg` JPG declaration is normalised so JPEG workbook images open in Word; the cabinet path keeps its original behaviour.
* Target deployment upgraded to `f0023ef`: dependencies reinstalled, frontend rebuilt, `project_test_items.result_note` and `worker_heartbeats` initialized by the existing bootstrap-managed schema, and PostgreSQL/API/Caddy/interactive Worker all restarted. The full suite passed 76 tests with two expected skips for private case workbooks. Served/local release asset hashes match, with no old application listener or Worker left running.
* Upgrade backup `D:\SOP-IGS-Backups\upgrade-20261020-171517` includes the database dump, originals, processed images, outputs, boost data, prior frontend build, and deployment notes. The dump passed `pg_restore --list` validation.
* The daily 02:00 SYSTEM backup task completed on 2026-10-20 with result 0 and remains scheduled for the following day.
* Live release checks passed: admin login, Feishu credential/QR endpoints, Worker online status, HTTP JPEG upload/preview, test-period/result-note persistence, Word-finalized cabinet generation (32 s), download hash, and the result note in the final DOCX. Standard boost-template upload parsed 11 chapters and 16 images. Diagnostic projects use synthetic data only.
* Both masters passed SHA256 verification and are approved following the owner's explicit business-review confirmation on 2026-10-21: `liquid-cooled-cabinet` v1 (`e06985520105`) was already approved and was not changed; `boost-integrated-unit` v1 (`43996b5ba310`) was approved with one `boost_template.approve` audit carrying `via=ops-script`. Only the boost status changed, with all other template fields preserved; no bootstrap, new login, environment change, or service restart was needed.
* Complete AI advice exceeded the former 60 s timeout; deployment configuration now uses `SOP_LLM_TIMEOUT_SECONDS=90`. After API restart, a real advice request succeeded in 63 s. The upstream model and credentials were also checked independently; application source was not modified locally.
* Feishu credentials remain only in the ignored production `.env`; the provider credential check returned code 0. A real employee scan remains a business/browser acceptance step.

## Current Issues / Risks

* Template approval is decided in development and shipped in each `manifest.yaml` as `approved_master_sha256` (the business-reviewed master hash); bootstrap marks the template approved while the master hash matches, and falls back to `review_required` when the master changes until the manifest hash is updated after a new review. Deployments need no approval step. Representative business UAT should still confirm measured-data cells and project-specific paragraphs.
* The original cabinet deployment completed a 100-job Word COM soak test; the newly approved boost path still needs a production Word end-to-end UAT run.
* Two earlier cabinet task snapshots reference four photos deleted while the Worker was offline; these failed tasks were not rewritten or silently requeued. Existing photo rows were checked for original/processed file integrity during incident repair.
* Production PostgreSQL, backup credentials, and the daily SYSTEM backup task are configured locally. The real LLM endpoint is configured and verified.
* Microsoft Word COM remains an operational risk; the Worker must stay in a logged-in interactive account and should ultimately move to a dedicated account.
* Feishu login is enabled, but a real scan still depends on the Feishu application allowing employees and registering the exact IP-based callback. No Feishu admin open IDs are configured yet; the local admin remains the fallback.
* The boost input spec (v1: column J 「格式」 with `+` for several items per row; column A = 三级标题, or content when a format is set and B–I are empty) is implemented and documented in the template's 填写说明 sheet, but the business has not confirmed it. The template keeps the case project's parameter values (time zone, power, IP tables) as editable examples.
* Browser click-through verification could not be completed because the Windows computer-use tool could not reliably identify the current browser URL. HTTP upload APIs, preview, deployed assets, and final report generation were verified independently; actual file-picker/progress UI acceptance remains pending.

## Current Focus

Real two-product UAT, boost workbook-spec acceptance, and Feishu QR-login acceptance.
