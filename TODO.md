# TODO.md

## Doing

* Have a domain owner review and approve the regenerated `master.docx` (manifest v3, historical photo tables removed).
* Clone the public GitHub repository to the dedicated Windows machine, complete production configuration, and run the 100-job Word COM soak test.
* Review the boost 测试项分类表 spec and `input-template.xlsx` with the user department (format values, A-column rule, `+` multi-item rows, image placement); changes go into `backend/app/boost/input/interpreter.py` (bump `PARSER_VERSION`) and `tools/build_boost_input_template.py`. The template still contains the case project's parameter values as examples.

## Next

* Complete a real Feishu QR-code login end to end locally, then on `http://10.122.3.224:8010` after deployment (redirect URLs are registered).
* On the deployment machine set `SOP_PUBLIC_BASE_URL=http://10.122.3.224:8010`, `SOP_SESSION_COOKIE_SECURE=false`, open firewall port 8010.
* Decide whether the 6 existing local projects created by `admin` should be reassigned to other users now that projects are owner-scoped.
* Configure production PostgreSQL, backups, and service accounts.
* Run UAT with representative real projects and up to 200 photos.
* Review the seeded fire/module/BMS/lifting/forklift/temperature photo-group labels with business owners.
* Review sample-photo placement and the regenerated TOC with business users; sample photos remain recommended rather than mandatory.

* Run boost UAT with real workbooks prepared from the standard template; confirm the Excel-only sections (空调, 断路器整定值, 绝缘监测装置, 电压频率检测装置, 充气柜（正泰）) are laid out as the business wants.
* On every machine that runs the Word worker (including the dedicated production account), disable the Microsoft OfficePLUS Word add-in for that account (`HKCU\Software\Microsoft\Office\Word\Addins\MSOfficePLUS` `LoadBehavior=0`); it blocks headless Word automation (hidden WinForms/network wait, 300 s timeout). Run the worker in a logged-in interactive session, not a hidden background process.
* Have a domain owner review and approve the boost `master.docx` (title-block placeholders, fixed reference list, 5.1 text); production generation stays gated on `review_required`.
* Run `alembic upgrade head` on the production PostgreSQL (0004 adds only the standalone `boost_*` tables).

## Backlog

* Evaluate object storage when local storage no longer fits.
* Add project archive/recycle-bin UI and formal retention settings.
* Add frontend route-level code splitting if bundle growth affects load time.
* Clean up superseded boost source-file uploads and their extracted images (currently kept forever).

## Blocked

* Production approval is blocked on manual template review and the target-machine COM soak test.
