# Approved scope and acceptance checklist

The approved UX is Windows XP-style forms with `#D2D2D2` backgrounds, `#E6E6E6` panels, selective `#DDEED8` green, `#2F5D3A` forest green actions, bold labels and headings, and Tahoma. Dropdowns, clear feedback, minimal data entry, and 44-pixel mobile touch controls are required.

All existing three-step capture trackers use red (`#E9ADAD`), yellow (`#FFE167`), and green (`#BBDDB1`) tints for steps 1, 2, and 3. Reached steps retain their colours, including after Back navigation and draft restoration, so Review displays all three colours together. Unreached steps remain grey. Only the current step is bold; these colours do not indicate approval or change button styling. General Hand drafts immediately save the highest reached step; reopening starts at step 1 while keeping reached colours. Legacy drafts without that metadata begin with step 1 reached.

App branding retains the supplied original logo in the header. The compact account panel uses a forest green version of the faithful transparent cutout on grey, with no image border. The original white cutout remains available. The favicon and PWA icons use the cattle emblem without company lettering, centred on a forest green square. The original supplied image is retained unchanged. The user approved a deterministic original-image cutout after imagegen outputs failed visual review.

| Capability | Implementation | Acceptance evidence |
|---|---|---|
| Three roles and server permissions | Session authentication, CSRF, role checks, role-specific navigation | Permission and account-revocation tests |
| Account access screen | Compact XP panel, Sign in/Register tabs, Show/Hide, recovery views, online-only account requests | Keyboard, validation, and 360/390/650/820/1366-pixel browser checks |
| Registration approval | Pending hashed requests for General Hand, Owner, Farm Manager; no access before manager approval | Role permissions, station requirement, manager confirmation, rejection/reapplication, duplicate and concurrent approval tests |
| Password recovery | Manager verifies General Hands/Owners; administrator CLI handles Managers; hashed 12-digit codes, 30-minute expiry | Wrong/expired/replaced/used/leading-zero codes, session revocation, disabled-account and preserved-draft tests |
| Account upgrade and throttling | Explicit backed-up schema revision 001; database-backed username/IP/failed-code limits | Repeated migration on database copies, unchanged existing rows, request-limit tests |
| Field home / six actions | Procedure, weights, health, movement, birth, death | Browser capture check |
| Shared capture progress | Retained red/yellow/green reached steps in every capture form | All 15 capture types; Birth/Procedure navigation and offline draft restoration |
| Offline capture | IndexedDB user-partitioned drafts, queue, reference lists; cached PWA shell | Browser offline/reload/sync check |
| Whole-session approvals | Manager review, return/reject reason, resubmission revisions | 83-of-87 dipping and return tests |
| One cattle record and temporary calf IDs | Animal identities, parent links, controlled tag changes | Temporary calf/tag and stillbirth tests |
| Animal profile and histories | Overview, Health, Growth, Breeding, Movements | Browser pages and append-only weight tests |
| Health and multiple treatments | Persistent health cases and product consumption | Multiple treatment/resolution tests |
| Breeding | Bull exposure and pregnancy checks; labelled estimates with required basis | API validation and report tests |
| Movements / births / deaths / purchases / sales | Linked animal events and official projections | Lifecycle and movement tests |
| Medicine / feed / fuel inventory | Stock receipts, usage, minimums, transaction history | Stock aggregation and insufficient-stock tests |
| Operational finance | Automatic source entries, manual operational income/expenses; USD/ZiG separately | Source transaction and currency tests |
| Corrections | Revision history, latest-dependent-event guard, stock/money reversals | Repeated correction and dependency tests |
| Reporting | Current herd, health, breeding, growth, movements, births/deaths, purchases/sales, supplies, finances | Report/filter/PDF tests |
| Administration | Stations, existing General Hand account editing, registration/recovery review, product configuration, activity | Browser pages and account tests |
| Opening herd | CSV spreadsheet template, preview, full validation, atomic import | Import tests |
| Owner oversight | Official records, concerns, stock alerts, currency totals, performance counts | Owner visibility and read-only tests |
| Owner herd chart | Active/Sold/Dead/Lost doughnut, total registered cattle, filterable legend | Lifecycle count, empty-state, and browser legend tests |
| Mobile layouts | Expandable navigation and routine record cards for all three roles | 360/390/650-pixel browser checks |
| Sample reports | Nine PDFs exported from an unchanged snapshot of existing demo records | PDF render review and source-change checks |
| Backups | Backup command and restore verification; daily scheduling script | Local backup restoration check |

## Launch gates

- Local development uses SQLite only when no `DATABASE_URL` is supplied. Production must use PostgreSQL and HTTPS.
- Verify PostgreSQL installation, concurrent approvals, and a full PostgreSQL restore on the deployment host. SQLite tests do not establish PostgreSQL concurrency behaviour.
- Run tablet acceptance tests on the actual farm devices, including airplane mode and reopened installed PWA.
- Enter opening herd and supply balances, then reconcile one pilot station before expanding.
- Install and verify the daily backup schedule on the farm server.

## Explicit boundaries

No additional roles, AI, ERP modules, full accounting ledger, automatic currency conversion, external integrations, or theme alternatives.

Account access is the approved scope extension. Initial Manager and Owner provisioning stays in setup. Registration grants only one of the existing three roles after manager approval; General Hands need a station, while Owners and Managers do not. Approving a Manager requires explicit confirmation of full manager permissions. Existing account-edit permissions stay unchanged. Recovery preserves account identity, role, active status and user-partitioned offline drafts. It never reactivates a disabled account. No email/SMS integration is included. Credentials and reset codes stay out of IndexedDB, PWA caches, audit details and application logs. Installed databases require `upgrade-accounts`; fresh databases receive the complete schema.

Birth and purchase corrections preserve the original animal ID and reverse related expense entries where applicable. Permanent tagging uses the animal identity form. Changing the dam or voiding an animal registration requires parentage/dependent-record reconciliation and is not exposed as an automatic action. Event corrections are allowed only when they do not invalidate later dependent changes. These limits are shown as clear validation errors.

Herd reports show current state. Date filters apply to event and transaction reports. Procedure schedules are based on an explicitly entered next-due date; no dosage or veterinary interval is invented.


## Approved audit fixes and cattle additions (14 October 2026)

The user approved Lost/found capture, individual prices on bulk purchases, and both bulk exposure and pregnancy checks. These extend existing cattle events, not roles or modules.

- Lost/found is available from animal records. General Hands submit assigned-station cattle for whole-session approval; Managers confirm directly. Lost preserves last-known station and health. Found restores the same animal to Active at the confirmed station; Managers may confirm another station. Procedure absences never automatically change lifecycle. No money or stock entries result.
- Bulk exposure uses one station/date and an active Bull. Pregnancy checks record a separate result and supported optional estimate for every selected eligible female. No conception date is inferred.
- Purchases record individual identities and prices, one invoice currency/reference, and one summed expense. Whole-session corrections preserve the full set of created animal IDs and explicitly reverse financial effects. Adding/removing registered animals through correction is blocked.
- Structurally valid field proposals reach Pending approval even when official tags, locations or lifecycle conflict. Conflict labels are review information, not an additional official state. Approval revalidates and cannot bypass conflicts, negative stock, or dependent records.
- Explicit next-due reminders apply per participating active animal. Unselected cattle keep earlier reminders. No veterinary interval is invented.
- Open farm/account queues are independent of paginated history. Offline logout intent blocks session restoration until server logout completes; drafts remain partitioned by account.
- Report details include existing usage, absences, breeding results, parentage, movement and trade information. Performance uses measured weights and recorded calving, with unsupported rates marked unavailable.
- Asset cache version 8; original branding, palette, permissions and account recovery remain unchanged. No database migration or automatic historical repair is required.

Acceptance evidence and deployment gates are listed in `AUDIT-FIXES.md`.


## Targeted audit fixes 1-3: breeding, station proof and draft versions

- Breeding action validation is unconditional. Exposure cannot contain pregnancy-check results or calving estimates. Valid legacy single-animal pregnancy checks and exposure records remain supported; existing historical records are not rewritten.
- General Hand reference animals include a signed `capture_proof`, bound to user ID, station ID, animal ID and downloaded version. Event payloads retain these in `capture_proofs`. An unsigned version field never proves station access. Receiving and resubmitting field records checks participating cattle, birth dams and listed absences.
- Valid proofs allow moved animals to enter the Manager conflict queue, without approving them. Legacy drafts without proof are accepted only while their cattle remain assigned to the Hand. Otherwise keep the draft and require Manager reconciliation/re-entry; do not discard it or grant a legacy access exception.
- Proofs use a dedicated signing salt and the stable application secret, without passwords or session versions. They survive credential recovery; changing the application secret invalidates older proofs. Preserve affected drafts for Manager reconciliation. Proofs establish earlier assignment, not current approval eligibility.
- Capture versions and proofs are recorded on initial selection and retained across deselection/reselection, Back, reference updates, synchronization and reopening. Existing drafts are not silently upgraded with current versions. Returned submissions offer an online review of captured/current values; only explicit confirmation replaces metadata. Cattle unavailable to the Hand require Manager re-entry.
- These additions use existing JSON/IndexedDB storage, with no migration or historical cleanup. PWA shell version 9; style, account recovery, inventory, finances and all other workflows remain unchanged. Audit items 4-7 are outside this release.


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

Stop application writes and run `python -m flask --app app upgrade-farm`. Revision `003_dashboard_avatar` creates a verified backup first, preserves the earlier station-assignment, product-archival and stock-precision changes, and adds database-backed General Hand profile pictures. SQLite numeric affinity preserves historic ledger values. Existing IDs, primary station assignments, credentials and drafts are preserved. Run `upgrade-accounts` first if revision 001 is not installed. Repeating the command is a no-op. Installed databases are never upgraded automatically; operational API access gives a readable upgrade-required response until ready. Restart the application and reload the PWA after upgrading.

Production PostgreSQL concurrency/restore verification, logged-off unattended backups, actual farm-tablet checks and one-station pilot reconciliation remain launch requirements. Browser checks must use isolated fictional data exclusively.


## Maintenance fix: installed release activation

Shell version 11 refreshes previously cached release scripts together, preserving IndexedDB and draft storage. Operational schema upgrades remain explicit and backed up; no automatic startup migration is introduced. The existing installation was upgraded through `upgrade-farm` to resolve the reported loading failure; legacy users, animals, event, ledger and audit values were checked unchanged.

Shell version 12 fixes account buttons disabled by the device offline indicator: account operations still require a successful server connection, but do not require internet availability. In-flight forms prevent repeated submission and show connection failures. Drafts and authentication permissions remain unchanged.

## Approved General Hand dashboard refinement (shell version 13)

- All dashboards place the signed-in name and role below the logo on the left, with an accessible notification bell at the upper right. The bell derives current role-permitted alerts from existing drafts, submissions, approvals and official attention data; it creates no notification history.
- General Hand Home has no introductory or quick-action helper wording, no assigned-cattle download message, and still limits the Working station selector, reference data and signed capture proofs to Manager-assigned stations.
- A General Hand may upload or remove only their own PNG, JPEG or WebP profile picture on Account. The server validates and normalizes it to a small PNG stored in the database; it is part of normal backup/restore and never enters IndexedDB, event payloads or audit details.
- Revision `003_dashboard_avatar` is explicit and backed up through `upgrade-farm`; installed databases are never auto-upgraded. Shell version 15 refreshes the shared header, dashboard and avatar controls without clearing saved drafts.
