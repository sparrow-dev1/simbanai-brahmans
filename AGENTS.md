# Simbanai Brahmans implementation boundaries

Read `SCOPE.md` before changing application behaviour. The user approved a bounded cattle management application; do not add unrelated modules or features.

- Preserve Flask, PostgreSQL production storage, and the responsive PWA with IndexedDB field drafts.
- Preserve the three roles: General Hand, Farm Manager, Owner. Enforce access on the server; the owner is read-only.
- Use the palette tokens in `static/style.css`: deeper grey surfaces (#D2D2D2/#E6E6E6), selective light green, forest green actions (#2F5D3A) with white bold labels. Retain XP-style forms, tabs, borders, buttons, and Tahoma. Do not introduce blue XP branding, yellow actions, dark themes, floating desktop windows, or a new visual system.
- Preserve mobile navigation, touch targets, routine record cards, and the owner's official-record lifecycle doughnut. The centre means all registered cattle, including historical animals; its four statuses must remain mutually exclusive.
- Retain `static/company-logo.png` unchanged in the header. Login uses `static/company-logo-green.svg`, a forest green version of the transparent artwork on the grey panel, without an image border. Preserve the white cutout, original, header logo and favicon/PWA icons. The user approved deterministic extraction from the original after imagegen cutouts failed visual review.
- Preserve manager-approved registration for all three existing roles. No account or session exists before approval; General Hands require a station, and Manager approval explicitly confirms full manager access. Preserve existing account-edit permissions and initial setup provisioning.
- Recovery uses manager-issued codes for active General Hands/Owners and `issue-manager-reset` for Managers. Codes are 12 digits, expire in 30 minutes, are hashed, shown once, replaced on reissue, and consumed atomically. Credential changes invalidate codes and sessions. Preserve account IDs, roles, active status and offline drafts; never reactivate disabled accounts.
- Account requests require connectivity. Never store credentials/reset codes in IndexedDB, caches, audit details or logs. Keep database-backed public throttles and explicit backed-up `upgrade-accounts` migrations; do not auto-upgrade installed schemas.
- All existing capture forms share reached-step colours: red (#E9ADAD) for step 1, yellow (#FFE167) for step 2, and green (#BBDDB1) for step 3. Unreached steps remain grey. Back navigation retains reached colours and only changes the bold active label; this indicates navigation progress, not manager approval. Immediately persist the highest reached step for every General Hand draft; legacy drafts without progress metadata start with step 1 reached.
- Prefer dropdowns for configured choices, searchable dropdowns for long lists, and checklists for bulk cattle selection. Keep numeric/date/text controls for corresponding information.
- Official records come only from manager confirmation or manager approval. Apply related changes atomically. Never double-process synchronized submissions.
- Preserve permanent animal identity, historical events, ledger reversals, correction reasons, and audit records.
- Keep USD and ZiG separate. Do not add exchange rates, full accounting, production AI, integrations, or additional roles.
- Ask before expanding scope or changing an agreed business rule. Resolve ordinary coding choices using existing conventions.
- Run `python -m unittest discover -s tests -v`, `node --check static/app.js`, and `node --check static/auth.js` for relevant changes. The browser test is deliberately restricted to an isolated fictional demo database.
- Do not run browser tests against real farm data. Never overwrite an existing database to initialize demo records.
- Keep credentials and runtime databases in ignored local paths or environment variables.


## Approved audit update

Preserve the bounded fixes documented in SCOPE.md and AUDIT-FIXES.md. Lost/found submissions belong to the existing animal profile workflow, not an extra home quick action. Keep bulk pregnancy results per animal, active Bull exposure eligibility, and batch purchase prices summed server-side into one expense. Purchase correction must preserve every original animal ID. Pending conflicts must remain reviewable without modifying official records. Keep PWA cache version 9 and explicit deployment configuration for unattended backups; never install a scheduled task or attest a PostgreSQL restore automatically.


Preserve unconditional breeding-action validation and signed station-capture proofs. Client-supplied versions alone never authorize out-of-station cattle. Keep original draft versions/proofs, including after re-selection and reference refresh; only explicit returned-record reconciliation may replace them. Legacy moved-animal drafts without proof require Manager reconciliation/re-entry and must remain saved. Apply field authorization to submissions, resubmissions, birth dams and absences. No schema upgrade is needed for these JSON fields.

- Approved shell-v10 scope: compatible medicine units and decimal stock conversion; receipt-linked outside supplies; reversible product archival; multiple assigned stations and signed station-set permissions; Purchase/Gift acquisitions; calendar-month calf review reminders with Manager-confirmed category edits.
- Use shared XP animal-ID tiles, preserve original capture proofs on reselection, return to capture origin and show truthful save status. Keep labelled attention indicators separate from Lost status.
- Reports and profile PDFs use the unchanged supplied letterhead on every page. Keep nine families, separate currencies, complete participant appendices, searchable text and portrait/landscape layouts. Printing uses the same branded PDF.
- Expense and defined Performance charts use official records without forecasts or unsupported rates. Revision 002 requires the explicit backed-up upgrade-farm CLI; never auto-upgrade installed databases. Keep static/farm.js in JavaScript syntax checks.
