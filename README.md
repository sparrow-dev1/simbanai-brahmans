# Simbanai Brahmans

A Flask cattle management application with XP-style forms, deeper grey surfaces, selective light green, forest green actions, bold labels, offline field capture, and manager-controlled official records.

The compact login panel uses a forest green logo on grey, Sign in/Register tabs, and password visibility controls. The white transparent artwork and supplied header original are preserved. The favicon and PWA icons use the cattle emblem without lettering on forest green. `python scripts/prepare_branding.py` regenerates the cutout and icons using Pillow (asset preparation only); `python scripts/prepare_login_logo.py` builds the green SVG from that cutout and the shared action-colour token. The user approved the precise original-image cutout after two imagegen attempts produced unwanted marks; the source image stays unchanged.

Every existing capture form uses the same red → yellow → green progress tracker. Reached colours remain visible through Back navigation and reopening a draft; only the current step is bold. These colours indicate form progress, not manager approval.

## Open the local demonstration

This workspace has an isolated, fictional demonstration database with 87 cattle at Station A. It is not real farm data.

```powershell
.\Start.cmd
```

Open **http://127.0.0.1:5000**. Demo usernames: `manager`, `hand`, `owner`. Each uses **`Simbanai-Demo-2026!`**. General Hands have a tablet home; managers have operational controls; owners are read-only. Never use these demo accounts in production.

The provided machine has Flask and SQLAlchemy installed. Additional runtime packages were installed into ignored `.runtime/`; `Start.cmd` loads them. The server uses Waitress. Double-click `Start.cmd` to launch, or run it from a terminal. `Start.ps1` is also provided for environments that permit PowerShell scripts and for changing the listen address or port.

## Install on another machine

Use Python 3.12 or newer:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```

For a fictional demo in an empty database:

```powershell
.\.venv\Scripts\python -m flask --app app demo
.\Start.ps1
```

The demo command refuses to overwrite existing accounts or records.

## Production setup

Provision an empty PostgreSQL database and a dedicated database account. Set environment variables privately on the server; do not commit credentials:

```powershell
$env:DATABASE_URL = 'postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE'
$env:SECRET_KEY = 'a-long-random-secret-generated-for-this-server'
$env:HTTPS_ONLY = '1'
.\.venv\Scripts\python -m flask --app app setup
.\Start.ps1
```

`setup` securely prompts for separate manager and owner passwords. It creates one initial station, and never overwrites existing users. The manager creates additional stations and General Hand accounts in Administration, and reviews registration requests for all three existing roles.

Place the server behind an HTTPS reverse proxy. The tablet must use HTTPS for service workers; localhost is permitted for local development. `HTTPS_ONLY=1` requires HTTPS and must not be set for a plain-http local demo. Tablets connect to the server's HTTPS hostname, not their own `127.0.0.1` address.

When `DATABASE_URL` is absent, the application uses **SQLite for local development** in `instance/cattle.db`. PostgreSQL is the production database, using row locks and transactional approval effects. No PostgreSQL server was available on the implementation machine; production-host concurrency and restore checks remain launch gates.

Fresh empty databases receive the complete schema. Installed databases are never automatically migrated. Account workflows require the explicit schema revision described below.

## Upgrade an existing installation

Stop the application server and set the same database environment variables used by that installation. Run:

```powershell
python -m flask --app app upgrade-accounts
```

The command creates and checks a backup in ignored `backups/` before applying account schema revision **001_accounts** through SQLAlchemy. It adds registration requests, recovery requests, throttling and a migration ledger; existing User columns and farm records remain intact. A repeat run reports that the revision is already installed and makes no changes. If the backup fails, the upgrade stops. Use `--backup-directory PATH` to choose a different protected backup folder. Restart the server after success. Before a production upgrade, rehearse on a separate database copy and verify restoration as described under Reports and backup.

## Registration and account recovery

Registration requires connectivity. Applicants provide their name, a unique username, requested role, and matching passwords of 12 to 200 characters. Requests remain pending, with a password hash only; applicants cannot sign in before approval. In **Administration → Users**, the manager reviews Registration requests. General Hands need an assigned station. Owners receive read-only access and Managers receive full operational access, with an explicit confirmation before granting it. Owners and Managers have no station assignment. Rejection requires a reason; rejected applicants may reapply with an available username. Approval never replaces an existing account or its credentials. Existing account-edit controls still manage General Hands only.

**Forgot password?** gives the same acknowledgement for eligible, unknown, disabled and Manager usernames. Active General Hand and Owner requests appear under **Administration → Users → Password recovery**. Verify identity independently before selecting Issue code. The code has 12 digits displayed as `0000 0000 0000`, is shown once with Copy, and expires after 30 minutes. Share it privately with the verified account holder. Issuing a replacement invalidates the previous code. Rejecting a request requires a reason. No email or SMS service is connected.

On **Reset password**, enter the username, code, and matching new passwords. Spaces and hyphens are accepted in pasted codes; leading zeros are preserved. Successful recovery consumes the code, invalidates other codes and existing sessions, and returns to Sign in. It preserves the account ID, role, station, active status, and that user's saved field drafts. Intervening password changes also invalidate outstanding codes. Disabled accounts cannot redeem codes and are never reactivated by recovery.

Farm Manager recovery is restricted to the server administrator:

```powershell
python -m flask --app app issue-manager-reset USERNAME
```

Verify the Manager's identity before running the command. It uses the same code mechanism, displays the code once and the expiry in Africa/Harare time, and never writes the raw code to application logs. Run it privately, without terminal-output recording or log redirection. The Manager uses the public Reset password screen and signs in normally afterward. Web managers cannot issue Manager recovery codes.

Database-backed limits default to five new public requests per username per hour, thirty per client IP per hour, and five failed code attempts per username per fifteen minutes. Configure `AUTH_REQUESTS_PER_USERNAME`, `AUTH_REQUESTS_PER_IP`, and `AUTH_CODE_ATTEMPTS` as positive integer environment variables. These limits cover the new account endpoints and never disable accounts. Behind a proxy, ensure the server receives trustworthy client addresses; it does not trust arbitrary forwarded headers. Keep `SECRET_KEY` stable: it secures sessions and recovery-code hashes.

Credentials and reset codes are excluded from IndexedDB, PWA caches, audit details and application logs. Authentication API responses use `Cache-Control: no-store`. The implementation follows the relevant [OWASP recovery guidance](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html): uniform acknowledgements, a consistent minimum response time, secure randomness, expiry, single use, confirmation and session invalidation. The PWA shell is version 9; account workflows remain online while saved field work remains available offline.

## First farm setup

1. Create real stations and General Hand accounts. Each General Hand is assigned to one station.
2. In Administration → Opening herd, download the CSV template and enter paper records in a spreadsheet. Keep identifier cells as text and dates as `YYYY-MM-DD`. Leave unknown dates and parent identifiers blank.
3. Upload and preview. Fix all errors before confirming. The import creates cattle and parent relationships without inventing historical expenses.
4. Add medicine, feed, and fuel products with their stock units and minimums.
5. Receive existing supplies with receipt type **Opening balance**. Record new purchases as **Purchase** with total amount, currency, and supplier/reference.
6. Reconcile cattle and stock at one pilot station. Test the actual tablet in airplane mode before expanding.

## Daily work

On phones, open **Menu** to navigate. Routine cattle, submission, supply, and money lists become compact record cards; dense reports and weighing tables remain scrollable within their panels. The owner's Overview includes a lifecycle doughnut: Active, Sold, Dead, and Lost. Its centre shows **all registered cattle**, including historical animals; select a legend entry to open the matching cattle register.

Field capture follows Select cattle → Enter details → Review → Submit. A station's cattle can be selected together and exceptions removed. A single procedure supports several medicine products; quantities are **total stock used**, with dosage recorded separately.

Drafts save on the device as information is entered. **Saved on this tablet** means the server has not received the record. **Pending approval** means it has reached the manager. The server remains authoritative; pending sessions do not change herd or stock totals. Use Send & refresh after connectivity returns. Repeated synchronization cannot apply the same UUID twice.

The application downloads station cattle and lookup lists after online login. Offline histories are available only for profiles previously opened online. Keep the tablet's browser data; clearing site data removes unsent work. Saved drafts are partitioned by user and remain on the device after logout for that user's next login.

Only a manager approves field work. Approve or return a complete session; return/reject requires a reason. Stale animal versions, changed stations, insufficient stock, incompatible lifecycle events, and invalid dates are explained and blocked. Refresh the field lists and correct/resubmit returned records rather than silently replacing official truth.

Manager entries require an online confirmation. Stock receipts, sales, and cattle purchases automatically create financial entries. Stock consumption does not create a duplicate purchase expense. USD and ZiG remain separate throughout.

Corrections preserve original events and audit history. The correction screen is available for approved events, subject to dependent-record checks. Later dependent changes must be reconciled first. Birth and purchase events can be corrected without creating another animal; purchase expenses are reversed and replaced. Changes to the dam or voiding an animal registration require reconciliation of dependent records. Permanent tagging updates the same calf record.

## Reports and backup

The nine generated sample PDFs and their source/date index are in `sample-reports/`. They use an unchanged snapshot of the existing fictional demo database. Empty reports explicitly state that no records match. The exports do not invent transactions or change the application database.

Reports support date and station filters, printing, and generated PDF downloads. Herd reports describe current state; date filters apply to event/transaction reports. Stock and finance reports include reversal entries so balances remain explainable.

Start.ps1 and Backup.ps1 can share `instance/deployment.json`, an ignored local file containing `DATABASE_URL`. Protect its Windows file permissions because the connection URL may contain credentials. Scheduled backups require this explicit configuration and never fall back to a development SQLite database. Start.ps1 retains environment-variable configuration when the file is absent.

Run a backup:

```powershell
.\Backup.ps1
```

SQLite backups are made using the database backup API and checked for integrity. Verify a real restore into memory:

```powershell
python -m flask --app app verify-sqlite-backup backups\YOUR-BACKUP.sqlite
```

For PostgreSQL, install `pg_dump` and `pg_restore` on PATH. Backup archives are created in custom format and checked for readability. Before launch, restore into a separate, empty test database using `pg_restore --dbname RESTORE_DATABASE backups\YOUR-BACKUP.dump`, then check herd, ledger, and audit counts. Never restore over the live database for a test.

After restoring and reconciling the selected backup in an isolated database, schedule daily Windows backups with:

```powershell
$backupAccount = Get-Credential
.\Install-BackupSchedule.ps1 -Credential $backupAccount -VerifiedBackup backups\YOUR-BACKUP.dump -PostgresRestoreVerified
```

Run this on the intended server. Its explicit scheduled account must have Python access, backup-folder permissions, and read access to the protected deployment configuration. The PostgreSQL switch is an operator attestation of a completed full restore, not an automated restore check. SQLite scheduling verifies restoration and compares farm identities with the configured database. Existing task replacement is not forced. The default is 02:00 server-local time; set the server to UTC+02:00. Test the scheduled task and monitor its exit result. The implementation session does not install an operating-system task on your behalf; installation is a launch step. Keep a second backup copy outside the server.

## Verification

```powershell
python -m unittest discover -s tests -v
node --check static/app.js
node --check static/auth.js
node --check static/sw.js
```

`node tests/browser-check.mjs` is an additional headless Chrome acceptance check. It creates its own isolated fictional database and starts a temporary test server on a dynamically allocated localhost port; it never changes the main application database. It assumes Chrome's standard Windows location. It checks account layouts at 360, 390, 650, 820 and 1366 pixels, keyboard focus, approval of all three registration roles, recovery, preserved drafts, manager screens, reports, tablet offline capture, reload persistence, 83-of-87 dipping, synchronization, approval, stock, mobile overflow, and owner permissions. Screenshots and isolated test databases go to ignored `test-output/`.

See `SCOPE.md` for the feature-to-acceptance checklist and `AGENTS.md` for boundaries future coding work must preserve.


## Audit fixes and approved cattle workflows

See `AUDIT-FIXES.md` for findings, implementation and validation. Animal profiles offer Record lost/Record found to field users and Managers; field entries require approval. My Records includes assigned-station animals so field users can reach these actions without changing the six Home actions. Lost retains history and health; Found confirms the station and reuses the same ID.

Manager purchases allow multiple animal rows with individual prices and one currency/reference. Review shows the invoice total; the server calculates the authoritative total and posts one expense. Corrections preserve the full set of registered animal IDs. Breeding sessions allow several eligible females, with one active Bull for exposure or individual pregnancy results and supported estimates for checks.

Open approvals and account requests are never cropped by history limits. History loads in pages of 100. Conflicting offline proposals remain Pending with conflicts and must be returned/corrected or rejected before they can become official. Reminders belong to the participating animals, not the last station-wide procedure.

For a single trusted reverse proxy, set `TRUSTED_PROXY` to its exact address before starting Waitress. Only that peer's forwarded host, HTTPS scheme and client IP are accepted; wildcard trust is rejected. Keep the backend bound to loopback when the proxy runs on the same server. Set `HTTPS_ONLY=1` for production. Do not enable proxy trust for direct connections.

After updating, restart the application server and refresh the PWA to load shell version 9. Production PostgreSQL concurrency, full restore, unattended logged-off/reboot backup execution, actual farm tablets and pilot reconciliation remain launch checks.


## Targeted audit fixes: capture validation and station proof

Breeding actions are validated regardless of supplied pregnancy results. Exposure accepts no pregnancy-check results or calving estimates; pregnancy checks still support individual results and properly supported estimates.

Downloaded General Hand cattle now carry signed station-capture proofs. Drafts retain the original animal version and proof, including across updated reference lists and offline restarts. The server checks proofs when receiving/resubmitting participating cattle, birth dams and listed absences. A valid earlier-assignment proof allows an offline movement conflict to reach Manager review; it never permits approval against incompatible current records.

Older drafts without proof still upload while the cattle remain assigned to the Hand. If they have moved away, the draft remains saved: ask the Manager to reconcile and enter the record. Do not clear browser storage to resolve this message. For returned records still available at the assigned station, use **Review updated cattle for this returned record**. Review the captured/current values and explicitly confirm before metadata changes; then submit for Manager approval.

Signing uses the existing stable application secret with a dedicated purpose salt, not passwords or session versions. Password recovery preserves these proofs. Rotating the application secret makes older proofs invalid; retain those drafts for Manager reconciliation. No database migration is required. Restart the server and refresh the PWA to load shell version 9. Audit items 4-7 were not changed.


## Approved farm workflow release (shell version 10)

- Medicine uses compatible mL/L or g/kg inputs and decimal conversion to the configured stock unit (six stock-unit decimal places). Enter actual concentrate consumed, excluding mixing water. Entered quantities and units remain in the event history. Negative usage and insufficient-stock approval remain blocked.
- Outside-source usage records its source and requires a linked official receipt before approval. Record paid receipts as Purchase and free receipts as External supply; only paid receipts create an expense. Receipt allocations cannot exceed recorded quantities. Archive/Restore replaces deletion and retains balances/history; archived products require restoration before approval.
- General Hands may have multiple assigned stations. Reference downloads include their assigned cattle, and source permissions plus signed capture proofs are enforced server-side. All registered movement destinations remain available.
- Add cattle distinguishes Purchase (individual prices, currency, one expense) from Gift (donor/source, no expense). Opening-herd imports and births remain separate workflows. Newborns remain Calf; known birth dates trigger calendar-month review reminders (default six, configurable 1?60). Managers confirm classifications with a reason.
- Shared XP animal-ID tiles provide search, selection and separate View controls, preserving first-captured proofs on reselection. Participant and absence lists remain separate. Records default to newest event date with an oldest-first option. Completion returns to its starting context with truthful save status.
- Owner Overview retains the lifecycle doughnut and compact concerns/shortages, with current-month recorded expenses. Money shows all recorded dates by default. Expense charts keep currencies separate, include reversals and distinguish empty data. Auto grouping is daily up to 90 days, monthly up to two calendar years, then yearly; manual grouping is available.
- Performance starts with a metric prompt. Measured daily gain uses summed weight differences divided by summed interval days; births, deaths and latest pregnancy results per animal/period use official records. No forecasts or unsupported fertility scores are inferred.
- Manager/Owner animal profiles have official summaries and downloadable/printable PDFs. Pregnancy checks are not separate pregnancies; registered offspring are not an assumed complete lifetime total.
- All nine report families use the supplied unchanged local letterhead (`static/report-letterhead.png`). Animal profiles, Growth and Births/deaths use portrait A4; other reports use landscape A4. Branding is proportionally recomposed on every page, with searchable body text, repeated headings and complete ID appendices. Print opens the same branded PDF used for download; use the browser PDF viewer?s Print command.

### Explicit installed-database upgrade

Stop application writes and run `python -m flask --app app upgrade-farm`. Revision `003_dashboard_avatar` creates a verified backup first, retains the earlier station-assignment, product-archival and stock-precision changes, and adds the General Hand profile-picture table. Pictures are resized safely and stored in the database, so they are included in normal backups. Existing IDs, primary station assignments, credentials and drafts are preserved. Run `upgrade-accounts` first if revision 001 is not installed. Repeating the command is a no-op. Installed databases are never upgraded automatically; operational API access gives a readable upgrade-required response until ready. Restart the application and reload the PWA after upgrading.

Production PostgreSQL concurrency/restore verification, logged-off unattended backups, actual farm-tablet checks and one-station pilot reconciliation remain launch requirements. Browser checks must use isolated fictional data exclusively.

Supplemental release checks: `node tests/browser-check.mjs --release-layouts` uses another isolated fictional database and checks all three roles at 360/390/650/820/1366 pixels, multi-station assignment, chart labels and offline sorting. The release checklist is in `FARM-RELEASE-CHECKLIST.md`.


### Local records-loading recovery (14 October 2026)

The local installed database was explicitly upgraded to revision 002 after creating and integrity-checking a backup. Existing cattle, users, events, stock, money and audit values were verified unchanged. PWA shell 11 refreshes the cached application scripts together; close and reopen the app, then refresh if the old screen remains. Do not clear site data or IndexedDB, because field drafts are stored there.

Windows Application Control blocked the globally installed SQLAlchemy optional compiled extension on this machine. The application runtime uses the same SQLAlchemy version's official pure-Python source build in the ignored `.runtime` directory. Start.cmd and Start.ps1 already load this local runtime. For manual CLI/test commands in PowerShell, prepend it first: `$env:PYTHONPATH = (Join-Path (Get-Location).Path '.runtime') + [IO.Path]::PathSeparator + $env:PYTHONPATH`.
