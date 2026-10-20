# TODO.md

## Doing

* Review the boost 测试项分类表 spec and `input-template.xlsx` with the user department (format values, A-column rule, `+` multi-item rows, image placement); changes go into `backend/app/boost/input/interpreter.py` (bump `PARSER_VERSION`) and `tools/build_boost_input_template.py`. The template still contains the case project's parameter values as examples.
* Have a domain owner review and approve the boost `master.docx`; production boost generation remains gated on `review_required`.
* Complete cross-machine browser UAT for both product choices through `http://10.122.3.224:8010`.

## Next

* Register `http://10.122.3.224:8010/api/auth/feishu/callback` in the Feishu application, confirm its employee availability scope/permissions, and complete a real QR-code login. Add admin open IDs later if automatic Feishu-admin promotion is required.
* Confirm the next unattended 02:00 SYSTEM backup run after the successful manual task test.
* Decide whether the three existing local cabinet projects created by `admin` should be reassigned now that projects are owner-scoped.
* Run UAT with representative real projects and up to 200 photos.
* Review the seeded fire/module/BMS/lifting/forklift/temperature photo-group labels with business owners.
* Review sample-photo placement and the regenerated TOC with business users; sample photos remain recommended rather than mandatory.

* Run boost UAT with real workbooks prepared from the standard template; confirm the Excel-only sections (空调, 断路器整定值, 绝缘监测装置, 电压频率检测装置, 充气柜（正泰）) are laid out as the business wants.
* If Word automation hangs, inspect OfficePLUS for the Worker account and ask for confirmation before changing its registry `LoadBehavior`; do not change it pre-emptively.
* Move the Worker from the current logged-in account to a dedicated, licensed interactive account for long-term unattended operation.
* Run `alembic upgrade head` on the production PostgreSQL (0004 adds only the standalone `boost_*` tables; 0005 adds `project_test_items.result_note`; API startup also adds the column automatically).
* After deploying, confirm on `http://10.122.3.224:8010` that photo upload shows progress/preview, and that the business is happy with the 测试结果描述 placement (before 测试结论) in a Word-finalized document; the generator test only checks the OOXML.

## Backlog

* Evaluate object storage when local storage no longer fits.
* Add project archive/recycle-bin UI and formal retention settings.
* Add frontend route-level code splitting if bundle growth affects load time.
* Clean up superseded boost source-file uploads and their extracted images (currently kept forever).
* Review the one high-severity issue reported by `npm audit` in a planned dependency-maintenance change. Do not run `npm audit fix` automatically or alter the lockfile as part of deployment.

## Blocked

* Boost production generation is blocked on business template approval.
* Feishu end-to-end acceptance is blocked on the external redirect URL, application permissions/availability scope, and a real employee scan.
