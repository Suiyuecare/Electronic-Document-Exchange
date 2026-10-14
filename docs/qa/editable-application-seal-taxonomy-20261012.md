# Uploaded-PDF application edits and explicit seal taxonomy acceptance

## Scope and release boundary

Candidate-only implementation for the approved editable-application and seal-catalog request. Legacy display mapping is confirmed: `establishment_seal` means 公司章; `general_seal` means 便章. IDs and historical stamp files are preserved. The primary dirty checkout is untouched.

This record is not production promotion, real employee SSO, physical-device acceptance, external delivery, or a hosted latency guarantee. No production migrations, real seal imports, production account changes, or government exchange calls were performed. The protected draft PR requires independent approval and the existing release gates.

## Acceptance criteria and result

| Criterion | Implementation and frozen evidence |
| --- | --- |
| PDF upload does not lock draft application fields | During transfer and after persistence, category, department, company, subject and reason remain editable within the server-authorized draft scope; latest committed IME input is persisted. Browser 3/3 viewport journeys passed. |
| Company switch preserves work without retaining foreign seals | Same document ID, PDF source bytes, page order and non-seal elements survive; foreign-company seals and entire seam groups are removed, undo/redo and obsolete review are cleared. Cancel makes no change. |
| Final approval uses one exact submitted version | Save, revision, preflight and submit serialize on the same document lock. Content revision, application snapshot, company, editor revision/manifest and prepared asset hash are checked together. Typed submission intent rejects stale-tab success replay. |
| Submitted records cannot be silently rewritten | UI is read-only after submit; server guards remain authoritative. Ever-submitted company ownership stays immutable; authorized correction is a distinct guarded scope. |
| Company and institution catalogs are explicit | Custodian chooses owner kind through a guarded API; names and filenames never infer it. Unclassified new selections fail closed. Company primary pair is 公司章; institution primary pair is 圖記章; both have 便章 pair and one 連續章. |
| Missing or unusable seals are not selectable | Inactive, mismatched owner/category, absent current version, invalid geometry, mismatched file metadata or unavailable private blob is excluded. A bounded private Range GET checks backing bytes rather than trusting Storage catalog metadata alone. |
| Rectangular geometry is truthful | 圖記章 and 連續章 require actual measured width/height and preserve aspect ratio. No invented dimensions; physical dimensions remain immutable on uploaded versions. A 1 mm seal is not enlarged by the legacy renderer's minimum visual size. |
| Historical output keeps its original stamp | Preview and final rendering use the locked file/hash/geometry even after a new current version is uploaded. Browser and actual final-PDF tests cover rectangular and continuous seals. |
| Data API remains least privilege | New public/shared RPCs use invoker privileges, empty search path, bounded lock timeout and backend-only grants. Owner policy has FORCE RLS and no backend DELETE. Trigger-only helpers have no direct backend execution grant. Actual PostgreSQL mutation tests reject weakened grants/search paths. |

## Exact frozen runtime

- `app.js`: `98c419d8883df88ea9b39bdff16be5e001df9bfdc3593f136da166bf5cbd2397`
- `backend.py`: `f6576fd791bdb04b2985a0855c15b50bcc18049f6b04d7ed086111864f219d16`
- `index.html`: `162c26d4add4b87530b0ca40a236998135e1d8ebd142c2c34f4bc96f7f7619f9`
- `styles.css`: `c914079cf968ffc4d52430e5311cb2571c7efd4f0f4511607a46bbb8aa15258c`

The commit ID is recorded in the PR evidence after commit creation; runtime hashes above match the local frozen tests. Browser reports verify the application hash before and after each run. The role-flow report has equal aggregate source digests and `source_changed_during_acceptance=false`.

## Executed checks

- Full Python discovery: **1,996 tests, OK, one skipped local signed-TUS environment case**. PostgreSQL opt-in tests executed against the disposable loopback cluster. The Storage/TUS case is delegated to the required fresh Supabase CI job, not counted as local success.
- Full Node discovery: **217/217 passed**, zero skips.
- Role-flow acceptance: **16 groups, 162 tests passed**, zero skips; includes six distinct synthetic Finance-role HTTP flows, inbound dispatch, correction/withdrawal/terminal decisions, transparent top-layer output, final application snapshot and actual calibrated PDF output. These are a subset of discovery coverage, not additional independent totals.
- Real Chromium loopback application journeys: **3/3** desktop/tablet/phone, **57 Boolean checks**; actual metadata/text readback, transfer queue, company-switch preservation, last-wins/IME, final confirmation cancel-zero-submit and exactly-once submit, read-only final UI and no horizontal overflow.
- Real Chromium loopback seal-policy journeys: **2/2** desktop/phone, **30 Boolean checks**; actual manual rectangular/continuous file upload/readback, five-slot inventory, classification cancel-zero-write and one-write confirmation, separate optional continuous slot, correct physical aspect and immutable PDF element profile.
- Only expected browser readiness response is the exact `/api/production/go-live-audit` **503 NO_GO** from the disposable local fixture. It is recorded with its response; no blanket 5xx suppression is used.
- Read-only final adversarial review: no concrete remaining high-priority issue; 12 Python and 8 Node narrow regressions passed without changing runtime hashes.
- Public-to-shared deterministic generation checks, Python compilation, embedded-credential scan and `git diff --check`: passed.

## Private local evidence locations

Evidence is outside the repository; only synthetic PDFs/PNGs are used by tests.

- `../artifacts/oct12-final3-python.log`
- `../artifacts/oct12-final3-node.log`
- `../artifacts/role-flow-oct12-final.json`
- `../browser-application-oct12-frozen-98c-final/report.json`
- `../browser-seal-policy-oct12-frozen-98c-final/report.json`
- `../browser-application-oct12-before/report.json` — visual baseline only, not old-client/new-server acceptance.

The root reviewer inspected final desktop/phone screenshots. Finance frame and mobile bottom navigation remain intact. Failed intermediate diagnostic logs remain available and are not overwritten by passing reports.

## Database candidate and inventory limitations

Public candidate migrations are `20261012114854_explicit_seal_owner_policy_and_continuous_geometry.sql` and `20261012115431_editor_application_final_snapshot.sql`. Their generated shared counterparts end in `20261012120530` and `20261012120531`; the manifest, fresh bootstrap and shared cutover/grant gates include both. They have not been applied to production.

Read-only current inventory found 11 active units, 96 active catalog entries, zero registered digital file versions and zero current versions. This is not proof that any physical stamp is missing. Source-original gaps are reported privately to the user, without copying real scanned stamps or identifiable contracts into the repository. Existing provided originals need faithful transparency processing, measured dimensions and approved vault registration before becoming selectable; placeholders are never silently treated as usable stamps.

## Reproduction

Run the existing CI workflow for fresh local Supabase/PostgREST/Storage/TUS acceptance. For isolated loopback PostgreSQL, supply `EDOC_COMPOSE_TEST_PG_PORT`, `EDOC_TEST_PG_USER`, `EDOC_TEST_PG_BIN`, and a fresh empty `EDOC_NUMBERING_TEST_PG_DSN`, then run `python -m unittest discover -s tests -p 'test_*.py'`. Run `node --test tests/*.test.js` and `python tools/complete_role_flow_acceptance.py --include-handover --report <private-outside-repo-path>`.

Browser acceptance scripts refuse unsafe output destinations and use disposable, deidentified local fixtures. No official exchange endpoint or real employee credentials are needed.
