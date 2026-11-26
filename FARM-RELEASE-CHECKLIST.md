# Farm workflow release ? acceptance checklist

Scope: the approved Farm workflow, reporting and display improvements plan. Shell version 10. No production database upgrade or historical cleanup has been performed.

| Agreed capability | Delivered implementation | Acceptance evidence |
|---|---|---|
| Compatible medicine units | mL/L and g/kg dropdowns; Decimal conversion; retained entered quantity/unit; NUMERIC(18,6) stock entries | Fractional 0.1 mL, mixed rows, mass conversion, incompatible/negative input regressions |
| Outside supplies | Source note, Manager-recorded paid/free receipt, receipt dropdown, quantity allocation and date checks | Missing/insufficient links blocked; paid receipt creates one expense; free receipt creates none |
| Product archival | Archive/Restore with remaining balance and history retained; archived products excluded from new selections | Pending submissions survive; approval requires restoration; browser Archive/Restore controls |
| Multiple stations | User/station associations, Manager checklists, all-assigned-station reference downloads, station-set authorization and signed proofs | Assigned second-station capture accepted; unassigned station rejected; existing proof regressions retained |
| Add cattle | Overview/Herd shortcuts; Purchase/Gift dropdown; donor/source; individual prices and one expense for purchases | Gift creates no expense; legacy purchases/corrections retain IDs; unrelated Gift markers cannot suppress sale/expense entries |
| Category review | Known birth date plus calendar-month reminder, configurable default six months | End-of-month calculation; Manager-only settings; classification remains unchanged until confirmation |
| XP cattle tiles | Actual IDs, wrapping borders, search/checklists, selection counts, separate View, keyboard focus, 44px labels/actions | Pointer View leaves selection unchanged; keyboard selection; long IDs retained in PDFs |
| Navigation and naming | Actual procedure names; event-date order; oldest option; origin and filters restored; truthful save status and record link | Browser Money return/filter check; offline Home return; existing draft/proof checks |
| Attention | Labelled red low-stock, health, absence and overdue-dipping indicators | Current role-permitted lists and compact Owner indicators; absence never changes lifecycle |
| Owner and Money charts | Expense line chart, separate currencies, grouping/range controls, reversals, explicit empty states | Currency totals, reversal entries, grouping and sparse-data tests; responsive Money chart |
| Performance | Metric prompt; measured gain, live births, deaths and pregnancy results; contributing counts and notes | Paired-weight arithmetic and per-animal pregnancy result tests; no forecast or unsupported rate |
| Animal profiles | Official summaries, parentage, offspring, detailed history, readable identity changes, Print/PDF | Superseded procedures excluded from counts; Owner allowed and General Hand PDF access blocked |
| Letterheaded reports | Nine report families; portrait/landscape A4; repeated original branding and headings; complete ID grids | All nine samples plus profile and 180-long-ID fixture rendered; text bounds/orientation/header/searchability checks |
| Safe upgrade | Explicit backed-up `upgrade-farm`, revision 002; existing assignments backfilled | Disposable old-schema copy: no auto-upgrade, original rows/credentials preserved, backup verified, repeat command no-op |
| Preserved behaviour | Existing approvals, identities, drafts, date rules, stock/finance reversals and permissions | Full workflow/account/deployment regression suite |

## Verification results

- Full unittest suite: 87 tests passed.
- JavaScript syntax checks: app.js, auth.js and farm.js passed.
- Supplemental isolated browser run (`node tests/browser-check.mjs --release-layouts`): passed all three roles at five widths, multi-station UI assignment/cache, populated responsive charts and labels, explicit Owner Overview panel removal, offline origin return, sorting and reopening.
- Nine sample PDFs regenerated without changing the source database. PDF layout checks cover every page plus profile and long-ID fixtures.
- Full isolated browser regression run: passed, including all 17 capture forms, 83-of-87 offline dipping, approval and 16 L balance, account recovery, signed proofs, returned drafts and offline sign-out/reconnection.

## Test artifacts

- `tests/test_workflows.py`, `tests/test_farm_upgrade.py`, existing account/deployment tests.
- `tests/browser-check.mjs`: fresh fictional database, temporary browser profile and dynamic localhost ports.
- `scripts/export_sample_reports.py`: read-only marked demo source; upgrades only its disposable snapshot; source SHA-256 unchanged.
- `scripts/check_report_layout.py`: all PDF pages rendered, orientation and character bounds checked; long IDs searchable; repeated letterhead checked.
- `test-output/sample-report-qa/layout-verification.json`: generated PDF verification results (local QA artifact).
- `sample-reports/README.md`: dated sample index and unchanged source checksum.

## Installed application and launch requirements

1. Stop application writes. Run `python -m flask --app app upgrade-farm` using the installed application's database configuration. It backs up before revision 002; run `upgrade-accounts` first only if revision 001 is absent.
2. Restart the application and reload the PWA so shell version 10 replaces version 9. Existing user-partitioned drafts remain intact.
3. On the actual production PostgreSQL server, verify concurrent approvals, complete restoration into a separate database, proxy configuration and scheduled backups while logged off.
4. On actual farm tablets, verify offline reopening, touch/keyboard usability and synchronization under the real network conditions.
5. Reconcile cattle and supply balances at one station before expanding the pilot.

Printing opens the same branded PDF as Download; use the browser PDF viewer's Print command. No emails, SMS, exchange rates, additional roles, forecasts or unrelated modules were added.


## Local installation recovery

14 October 2026: the installed local database was upgraded explicitly to revision 002 after a verified backup. Original farm/account/ledger/audit rows were compared unchanged. Shell 11 replaces stale cached scripts without clearing IndexedDB. Production-server and actual-device launch checks above remain outstanding.
