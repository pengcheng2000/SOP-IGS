# TODO.md

## Doing

* Have a domain owner review and approve the regenerated `master.docx` (manifest v3, historical photo tables removed).
* Clone the public GitHub repository to the dedicated Windows machine, complete production configuration, and run the 100-job Word COM soak test.

## Next

* Configure production PostgreSQL, HTTPS certificate, backups, and service accounts.
* Run UAT with representative real projects and up to 200 photos.
* Review the seeded fire/module/BMS/lifting/forklift/temperature photo-group labels with business owners.
* Review sample-photo placement and the regenerated TOC with business users; sample photos remain recommended rather than mandatory.

## Backlog

* Add Feishu SSO using the provider identity boundary.
* Evaluate object storage when local storage no longer fits.
* Add project archive/recycle-bin UI and formal retention settings.
* Add frontend route-level code splitting if bundle growth affects load time.

## Blocked

* Production approval is blocked on manual template review and the target-machine COM soak test.
