# Audit findings to fixes

This release implements the bounded audit plan approved on 14 October 2026. It preserves Flask/PostgreSQL, the XP palette and branding, three roles, permanent animal identities, approvals, account security, drafts and separate currencies. No installed database was migrated and no demonstration transactions were added to the existing source.

| Finding or approved addition | Result | Evidence |
|---|---|---|
| Rapid Next / Back / saving overlap | Shared capture transition lock; controls disabled during transition; reached step saved before rendering | Double-submit browser regression and retained-step checks |
| Restored submission remains on capture | Always route to submitted-record status after local save | Offline restored-draft submission without navigation workaround |
| Offline sign-out restores server account | Persistent logout intent; server logout before boot/sign-in restoration; local drafts retained | Offline logout, reload, reconnect and same-account draft comparison |
| Offline conflicts do not reach Manager | Valid field proposals stay Pending approval with explicit conflict information; approval revalidates | Duplicate calf tag, moved/version/lifecycle and insufficient stock tests |
| Station reminder hides another animal's due date | Latest explicit procedure schedule per participant; station/date/procedure summaries | Two different cattle/due-date regression |
| Cropped pending queues | Outstanding submissions/account requests independent of history pagination | More than 2,000 closed events and more than 200 closed registrations |
| Invalid breeding category | Cow/Heifer eligibility; active Bull at station; sex/category consistency on entry, identity and import | Steer rejected, Bull accepted, invalid purchase/identity tests |
| Incomplete reports | Captured medicine usage, absences, breeding results, parentage, destinations, currency/price/reference included | Report content assertions, nine PDF exports and rendered sample inspection |
| Broken shortcuts and repeated Performance | Owner health filter/Supplies report shortcuts; measured growth and recorded calving | Role-page/browser checks and measured growth regression |
| General Hand profile View denied | Only accessible authored events offer View; other permitted summaries remain | Existing permission tests; assigned-station record interface |
| Long bulk review | Recorded/expected counts, absences visible, participant list expandable | 83 recorded of 87 expected browser review |
| Irrelevant form controls | Single-animal forms omit Select all; exposure hides check controls; opening balances hide payment; stock use omits dosage | All capture-form forward/back browser checks |
| Notifications obscure actions | Notification occupies its own sticky strip above the application | Actual pointer hit testing |
| Raw correction JSON | Readable original/replacement field comparison | Activity rendering and existing correction tests |
| Poor readability | Audited navigation/capture/report handlers reformatted; transition and batch helpers extracted | JavaScript syntax checks and browser regressions |
| Lost/found | Existing profile/assigned-station records; Hand approval, direct Manager confirmation; identity/history retained; found station confirmed | Lifecycle counts, permission, duplicate synchronization and dependent correction tests |
| Bulk breeding | Shared Bull exposure; individual pregnancy results and supported estimates; atomic session | Mixed-result backend tests and grouped-check browser form |
| Bulk purchase | Individual cattle prices; server total; one invoice expense; correction preserves all animal IDs and reverses expense | Duplicate-tag atomicity, summed prices, correction and batch-form tests |
| HTTPS proxy origin | Explicit Waitress proxy address, one hop; scheme/host/client-IP headers trusted only from that peer | Trusted HTTPS origin succeeds; untrusted forwarded request denied |
| Unattended backup ambiguity | Shared explicit ignored database configuration, explicit scheduled identity, restore gate and SQLite identity comparison | PowerShell syntax and disposable backup restore/mismatch test |

## Verification

Latest completed results: 66 automated tests passed; isolated browser suite passed; JavaScript and PowerShell syntax passed. Nine sample PDFs were exported and visually inspected.

- Required workflow/account suite: `python -m unittest discover -s tests -v`.
- JavaScript: `node --check static/app.js`, `node --check static/auth.js`.
- Browser: `node tests/browser-check.mjs`, exclusively against a newly created fictional SQLite database and disposable Chrome profile. Includes 360/390/650/820/1366 pixels, keyboard/focus, pointer hit testing, offline persistence, account recovery, 17 capture trackers and the 83-of-87 approval journey.
- PowerShell parser checks cover Start.ps1, Backup.ps1 and Install-BackupSchedule.ps1.
- Samples: [nine PDFs and source/date index](sample-reports/README.md), generated through existing report endpoints from a read-only fictional snapshot. Source hash matched before/after export. Later normal application activity is not part of that snapshot.

## Compatibility and launch gates

Legacy single-animal purchase and pregnancy-check events/drafts remain supported. New rows are stored in existing event JSON with existing animal links and ledgers; no schema upgrade is required. The original logo and favicon/PWA icons are unchanged. Restart the application server and refresh the PWA to load shell version 8.

Not verified on the production host: PostgreSQL concurrent approvals, a full PostgreSQL restore, HTTPS proxy deployment, scheduled execution while logged off/after reboot, actual farm-tablet airplane-mode acceptance, and one-station reconciliation. The installer does not automatically establish these facts: `-PostgresRestoreVerified` is an explicit operator attestation after a completed restore. No Windows scheduled task was installed by this release.


## Targeted follow-up: audit items 1-3

The follow-up closes the breeding-action bypass, replaces client-version station trust with signed capture proofs, and preserves original draft capture metadata. Returned-record updates require an explicit online before/current review and confirmation. Legacy moved-animal drafts without proof remain local for Manager reconciliation/re-entry. No farm data or database schema is changed; PWA cache is version 9. Items 4-7 from the subsequent read-only review remain outside this follow-up.

Regression coverage includes unsupported actions with forged results, exposure/check field mixing, proof tampering and wrong user/station/animal/version, moved-animal conflict queues, birth-dam/resubmission authorization, absence permissions, legacy drafts, and proof survival after credential changes. Browser checks cover original metadata after refresh, re-selection, Back and offline restart, plus explicit returned-record reconciliation.


Follow-up verification: 74 automated tests passed, JavaScript syntax checks passed, and the isolated browser suite passed the added capture-proof retention and explicit returned-record reconciliation journeys. Prior production-host launch gates remain open. No migrations, operating-system tasks or changes to installed farm records were performed.
