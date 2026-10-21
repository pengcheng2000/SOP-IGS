# TODO.md

## Doing

* Review the boost 测试项分类表 spec and `input-template.xlsx` with the user department (format values, A-column rule, `+` multi-item rows, image placement); changes go into `backend/app/boost/input/interpreter.py` (bump `PARSER_VERSION`) and `tools/build_boost_input_template.py`. The template still contains the case project's parameter values as examples.
* After any future master change, re-review it and update `approved_master_sha256` in that template's `manifest.yaml` (deployments then need nothing).
* Complete cross-machine browser UAT for both product choices through `http://10.122.3.224:8010`.

## Next

* Register `http://10.122.3.224:8010/api/auth/feishu/callback` in the Feishu application, confirm its employee availability scope/permissions, and complete a real QR-code login. Add admin open IDs later if automatic Feishu-admin promotion is required.
* Keep monitoring unattended 02:00 backups; the 2026-10-20 run returned result 0.
* Decide whether existing local cabinet projects created by `admin` should be reassigned now that projects are owner-scoped.
* Run UAT with representative real projects and up to 200 photos.
* Review the seeded fire/module/BMS/lifting/forklift/temperature photo-group labels with business owners.
* Review sample-photo placement and the regenerated TOC with business users; sample photos remain recommended rather than mandatory.

* Run boost UAT with real workbooks prepared from the standard template; confirm the Excel-only sections (空调, 断路器整定值, 绝缘监测装置, 电压频率检测装置, 充气柜（正泰）) are laid out as the business wants.
* If Word automation hangs, inspect OfficePLUS for the Worker account and ask for confirmation before changing its registry `LoadBehavior`; do not change it pre-emptively.
* Move the Worker from the current logged-in account to a dedicated, licensed interactive account for long-term unattended operation.
* Keep using bootstrap for this production database (no Alembic version table); boost tables, the result-note column, and the heartbeat table are present. Do not apply the full Alembic chain to an initialized schema without a deliberate baseline.
* Confirm in a browser on `http://10.122.3.224:8010` that file selection shows progress/preview, and review 测试结果描述 placement with business users. Upload/preview APIs and the saved result note in the Word-finalized DOCX passed deployment checks, but Windows browser automation could not identify its current URL reliably.
* Confirm Worker recovery after a future Windows login; the account must remain logged in even though the custom weekly restart is now disabled.

## Backlog

* Evaluate object storage when local storage no longer fits.
* Add project archive/recycle-bin UI and formal retention settings.
* Add frontend route-level code splitting if bundle growth affects load time.
* Clean up superseded boost source-file uploads and their extracted images (currently kept forever).
* Review the one high-severity issue reported by `npm audit` in a planned dependency-maintenance change. Do not run `npm audit fix` automatically or alter the lockfile as part of deployment.

## Blocked

* Feishu end-to-end acceptance is blocked on the external redirect URL, application permissions/availability scope, and a real employee scan.
