# Workspace interaction and file workflow contract

This contract covers the 2026-09-28 file-resilience, fluid-interaction and compose-submission changes.
Existing Finance-aligned visual identity and approval/security contracts remain
in force. "Apple-like" means continuous, responsive interaction, not Apple
branding or a promise of zero network latency.

## Canonical UI Map

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
| --- | --- | --- | --- | --- |
| Form | Shared workspace constraints owner plus existing draft lifecycle in app.js | Native validity constraints, authorized document detail and content revision | Native controls with app-owned inline errors; existing inline text editor | Invalid-submit zero-request, valid recovery, IME and six-role browser tests |
| CRUD | backendRequest and scoped editor lifecycle | Backend revision, locked request and immutable assets | Explicit retry; no automatic mutation replay | Scope, reopen, download and transport resilience tests |
| Toast | showToast plus persistent upload/opening status | The current scoped operation result | Toast is supplemental, never the only recovery surface | Browser failure/cancel/retry journeys |
| Scrollbar | Browser viewport and existing styles.css overflow rules | Native scroll position | Existing PDF stage and queue scrolling | Desktop/tablet/mobile overflow checks |
| Select/Listbox | Pinned Tom Select 2.6.2 and shared `workspace-select.js/css` adapter | Server-provided companies, categories and seals; native values/options/datasets remain authoritative | Anchored searchable popup, keyboard and IME-safe commit, native disabled/validation synchronization, viewport collision and modal-owned portal; native fallback if library unavailable | `verify_workspace_select_browser.mjs` and six-role selection/upload journeys |
| Date | Existing native compose date input | User-entered date with existing today default | Unchanged and outside the file-resilience release | Existing compose regressions |
| Table Selection | Electronic-seal queue uses row actions, not bulk selection | Authorized paginated cases | No selectable table introduced | Slim-row download fixture |

## Shared interaction owners

| Capability | Canonical owner | Contract |
| --- | --- | --- |
| Navigation | `setView` and six existing major routes | Immediate selected view; same-route operations preserve scroll/focus; returning restores route scroll only within the current in-memory session; a changed route focuses its title. Integrated sub-sections retain their intentional section navigation. |
| Background reads | Scoped route loaders and official list transport | Share identical in-flight reads, not mutations; differing query/cursor/session remain separate. Preserve generation, permission and revision guards. Failure can be explicitly retried. |
| Inbound paging | Scoped server cursor and existing inbound list | Apply company, actor and status before paging; opaque cursor stays in memory, not URL or cross-session storage. Changing actor, company or filters invalidates the cursor. Stable order and explicit more-results control preserve authorized older cases. |
| Timeliness | Server timeliness report | Full authorized dataset aggregation, not loaded rows or status strings. Show missing timestamps as unknown, separate elapsed waiting from days until deadline, and distinguish incomplete data from zero. |
| Initialization | `initializeDeferredWorkspace` | Ordered cooperative batches yield to interaction. Do not remove initialization or reorder dependency steps. Old-session work must stop. |
| Form input | Existing compose/application lifecycle | During IME composition, hold preview/local/cloud autosave. Commit the final composition before saving; manual transitions cannot submit uncommitted input. Avoid rebuilding unchanged controls. |
| Form validation | Shared capture-phase constraints owner | Product forms use novalidate to avoid browser popups, not to skip constraints. Check required, type, pattern, range, step and custom validity before handlers; invalid input stops submission, receives localized inline error/aria-invalid/describedby and focuses the first invalid field. Disabled and composition-pending input must not bypass guards. Clear only owned errors after correction; server validation remains authoritative. |
| Compose distribution | `composePayload`, cloud draft snapshot and official PDF metadata | 正本 defaults to the current recipient; 副本 defaults to the selected sending company. Both are editable and must survive draft restore, correction and final PDF generation. Manual edits are preserved; changing the sending company only replaces its previous default when that default is still present. An explicitly cleared 副本 prints as 無. |
| Compose submission | `handleComposeSubmitRequest` and `confirmComposeSubmission` | One visible 送出簽核 action opens an app-owned confirmation only after the Finance workflow-readiness check passes. Missing Finance approvers are explained beside that action; the button remains actionable for a fresh check, but no backend mutation bypasses the Finance gate. Cancel/Escape preserves the draft and returns focus. |
| Lists | Existing authorized queue/log renderers | Preserve focused row action, scroll and stable nodes when content is unchanged. Do not restore focus into a different case, hidden control or new actor. |
| Notices | `showToast` | One notice, one owned 4s timer; identical messages do not rewrite the live region. Hover pauses its remaining duration. Persistent inline errors/retry controls remain authoritative. |
| Modal/drawer | Existing modal markup with shared isolation/focus helpers | Inert workspace children, never unset authentication's outer inert gate. Tab containment, Escape/cancel and trigger restoration. Reopening an already visible detail does not steal focus. |
| Backup restore | `requestWorkspaceTypedConfirmation`, `normalizeBackupDrill` and existing backup panel | Reuse workspace modal isolation/focus; typed consent is IME-safe and defaults to Cancel. Prevent duplicate requests. Blocked or incomplete evidence is never success, never creates a fabricated snapshot or updates the last successful drill date. Missing timings show 未量測; uncertain transport outcome is not automatically replayed. |
| Approval actions | Server `available_actions` and existing `officialDecisionModal` | Withdraw only while approval is pending and stamping has not been claimed. Return previous reopens the approved predecessor without applicant editing. Correction is resumable; decline is terminal. Shared review checkboxes start disabled, enable only after the corresponding successful view/download, and require manual acknowledgement for all approver decisions. Destructive decline initially focuses Cancel. Server errors preserve entered reason; conflicts refresh the case and require fresh review. |
| Motion/layers | `styles.css` | Finance colors/frame unchanged. Shared dialog/toast layer tokens; toast above dialog on all widths. Reduced motion disables travel; no operation waits for animation. |
| Editor confirmation | Shared workspace dialog | PDF replacement, page deletion, conflict reload and correction reason use app-owned dialogs; Cancel/Escape performs zero mutations. Recheck actor, document, revision and upload generation before committing. No missing browser-dialog API may imply consent. |
| Submission failure | `backendRequest`, `friendlyBackendErrorMessage`, compose save status and editor preflight status | An exact atomic-RPC validation rejection is not submitted and preserves the application/files; show persistent localized feedback and the support reference, not a transient retry promise. An uncertain commit remains unknown and directs the person to the approval record before retrying. No client or server automatic mutation replay is introduced. |
| Optional help | Shared disclosure | Short guidance is folded by default; record guidance_used only when a person actually expands it. No help text, document data or identities enter telemetry. |
| Performance | Scoped numeric event measurements | Measure actual workspace-interactive, local-editable and cloud-saved boundaries separately. A local provisional asset cannot be saved/submitted as an authoritative asset. No fabricated progress or completion. Cold/warm, device and network profiles stay separate in acceptance evidence. |
| Core refresh | `loadRouteBackendData` and `refreshWorkspaceSupplementalData` | Company directory, workflow configuration, current-company seal catalog and workflow readiness load in parallel. `workspace_core_ready` measures completion of actual required data, not first paint. Notifications and existing-case lists have independent persistent background/error states and never hold the editor refresh button busy. Manual refresh bypasses the healthy directory throttle; typed data is preserved. |
| Seal catalog recovery | Shared seal selectors and inline retry | Scope successful catalog metadata to actor, session and exact company. Ordinary large/small selection and the seam-only primary-large choice have independent state. A transient failure preserves same-scope choices but blocks new stamp placement and submission until refreshed. A 401/403, company switch or session change clears or isolates old choices. Loading, transport failure, permission denial, genuinely empty catalog, classification mismatch and unverifiable file states are not interchangeable. Existing document recovery does not revoke a valid same-scope catalog. Server-side file/use checks remain authoritative. |

## Fluid interaction acceptance

- Same-fixture before/after desktop and mobile screenshots for all six pages;
  tablet checks in the six-role suite. No overflow or inaccessible primary action.
- Route selection is synchronous; measure click-to-visible view locally, not
  authenticated production network/SSO timing. Navigation must not wait for reads.
- Concurrent identical list loads make one read; different session/query loads
  do not share. Unchanged organization data does not rebuild selectors, but an
  actual organization change with the same version still updates.
- Synthetic paused IME does not send partial local/cloud autosave; composition
  end commits the latest text. Physical OS IME remains a separate device check.
- Background refresh preserves focused case buttons and inputs; identical
  header state causes no repeated live-region text writes.
- Keyboard/mobile drawer and detail dialogs pass Tab/Escape/return focus and
  isolation checks; toast replacement has a full independent duration.
- Existing upload, locked version, cross-company denial, approval, final-output
  and receipt tests must remain passing before production publication.

## File lifecycle owners

| Capability | Canonical owner | Required behavior |
| --- | --- | --- |
| Authenticated metadata | `backendRequest` / `fetchWithDeadline` | 20s read deadline; heavy PDF/server operations 120s. Body consumption is bounded. Mutation timeout means outcome unknown, never automatic duplicate submission. |
| Legacy PDF version download | `downloadPdfVersion` / `downloadBinaryFile`, server document ACL | API downloads carry the current session and recheck document/company access even when a short-lived file token exists. Do not navigate directly to the API URL. Disable duplicate activation while pending; failure preserves the page and never records download success. Local same-origin blob versions remain downloadable without sending credentials elsewhere. Case-specific originals, editor assets, received attachments and reply files cannot use the legacy generic endpoint. |
| PDF transport | `performTusUpload` | Real byte progress, external cancellation, bounded chunk/HEAD requests. Same intent retries reuse the existing TUS resource and authoritative remote offset; immutable object storage is retained. |
| Local A4 editing | `handleUploadedSealPdfChange` | Validated local A4 opens before transfer. No persistent sensitive local draft is introduced. Unsynced edits remain in memory; save/submit stays gated until finalization and state save succeed. |
| Upload preparation | Local provisional asset and server intent promise | After validating the current application context, local A4 rendering and server draft/intent preparation run concurrently. Server failure leaves local work recoverable but unsaved; only a matching session/company/application/generation may replace the provisional asset. |
| Uploaded application editing | Editor metadata capabilities and revision CAS | Uploading a PDF is not submission. Title, reason, department and document category remain editable while draft/correction authorization permits; company is editable only for a never-submitted, unnumbered uploaded-PDF V2 draft. During transfer, queue the latest IME-committed inputs without changing the original upload intent. Synchronize them before preflight/submission. Company changes preserve the PDF and non-seal edits, remove foreign-company stamps and complete seam groups, and require a fresh review. |
| Final submitted snapshot | Document-locked metadata, editor-save, preflight and submission transactions | Compare application content revision, latest editor revision/manifest and prepared-file witness under the same document lock. A change after preparation or a concurrent save yields a conflict, not a stale approval or stamped file. Workflow actors and immutable seal file versions are selected from the final server-confirmed snapshot. Already-submitted history cannot be reassigned to a different company. |
| Stamp taxonomy and availability | Server company-seal policy and immutable Seal Vault files | Company: 公司章大/小、便章大/小、連續章. Institution: 圖記章大/小、便章大/小、連續章. Existing category IDs remain historical identifiers. Missing, inactive, invalid-calibration, unmatched or absent backing files are not selectable. Owner kind is explicit manager metadata, never inferred from a company name; unclassified is not a fabricated physical-inventory conclusion. |
| Physical seal size | Immutable file calibration | Existing company/便章 square policies remain. New rectangular 圖記章 and single 連續章 require explicit measured width and height from the custodian; no invented physical size. Geometry and category-policy pairing are checked server-side. Historical locked versions remain replayable independently of the current pointer. |
| Explicit PDF draft save | `saveUploadedEditorDraft`, existing metadata sync and editor CAS | Header and footer 暫存草稿 share one operation. Save the latest IME-committed application and PDF; no stamp is required. Only server-confirmed synchronization reports success. Preserve input on failure and restore the disabled trigger's focus only when the person has not focused another control. |
| Five-page riding-seam stamp | `uploadedSeamPrimaryLargeSeal`, `EDOCSeam`, `editor_seam.py` and locked manifest renderer | Classified selected-unit primary rule: new grouped seams use only the selected unit's available primary large seal: company → 公司章 (`establishment_seal`), institution → 圖記章 (`official_seal`). Classification comes from the server policy, not a name or editable element. Missing, noncurrent, uncalibrated, foreign-unit, bank, 便章, continuous and small seals remain unavailable. Version 2 fixes the displayed right edge and limits vertical placement to 10mm from top/bottom on every member page. Contiguous pages form groups of at most five; each receives one distinct left-to-right 1/N original-image strip, without shrinking or reshaping the original. New groups inherit the first group's physical top offset and can then be adjusted independently. Crop/rotation and smallest-page limits are checked by both client and server. Old pair/version-1 manifests and approved immutable snapshots retain their historical behavior. Deleting/reordering a member cannot produce an incomplete group. |
| Applicant seal preview | Synthetic geometry only, client placeholder and compatibility preview endpoint | Draft/editor/preapproval previews never fetch private real seal pixels. Use the exact physical bounding box, concise size label and always-visible dashed outline; seam selection matches its visible slice. The server renders real seal pixels only into the authorized approved output. Custodian management remains separately authorized. Original PDF content is not erased; already approved documents can still be screenshotted. |
| Editor image import | Local provisional PNG/JPEG, background immutable upload | Decode and validate the local image before insertion. Preserve intrinsic aspect ratio and distinguish local work from server-saved assets. The editor-image-only antivirus exemption is truthful `not_scanned`; structural validation, MIME/size limits, file hash, current actor and immutable storage remain mandatory in Python and finalization/conflict-copy RPCs. General attachments and seal registration are unchanged. Pending/failed images cannot submit or report saved. |
| Editor pointer interaction | Selected-node rAF update and pointer-up state commit | Drag/resize modifies only the active SVG node per animation frame, not the whole editor. Text font/box and images scale uniformly; seal physical size stays fixed. Correct inverse viewport/PDF coordinates preserve rotated-page direction. Undo and server autosave commit after interaction, not on every move. |
| Draft workspace | `#drafts`, `workspace_drafts.py`, bounded metadata RPC | Sidebar count is the authenticated applicant's complete deduplicated unfinished cloud/official work, not just the loaded page. Correction cases remain marked. Local unsynced content is separately identified. Fresh compose remains blank; open a specific authorized draft deliberately. Never download every snapshot just to count. |
| Approval workspace | Four primary tabs plus scoped operational filters | Pending, mine, actually acted, returned/correction. Assignment alone is not completed approval. Preserve delegation, overdue, general-affairs/receipt and retry tasks. Server visibility and available actions remain authoritative. |
| Approval evidence dialog | Existing `officialDecisionModal`, evidence state and shared modal focus owner | One-column evidence cards at every width; checkbox text owns a shrink-safe wrapping span. Every review acknowledgement and comment change recomputes the same submit gate. Show the remaining requirements beside the action; failed downloads never count as read, and no-attachment cases must not claim a download. Do not auto-check or weaken the actual evidence/revision requirements. |
| Case company identity | Authorized case identity and current-session company directory | Preserve an explicit case company-name snapshot; if absent, resolve its exact company ID using the current-session directory. Never substitute the currently selected company, the user's company, the first directory row or a fixed company fallback. Keep the issuing/sealing unit separate from the applicant's department. Loading, missing identity and lookup failure use honest neutral copy; display resolution never changes a saved company, selected stamp, payload or permission. |
| Read-only PDF presentation | Existing editor capability/lock/review-mode owners and authorized case status/revision | A locked or review-only document is presented as document review, not an editable application. Show the actual known case status and available revision; a temporary loading lock or another applicant's draft must not be called submitted. Remove irrelevant mutation affordances while preserving authorized view/download and the existing return/new-application paths. An editable applicant's prepared-file review retains its existing return-to-edit and confirm-submit actions; it is not a submitted-case lock. Draft/correction editing remains governed by existing capabilities, and previewing original/prepared files never grants edit rights. UI presentation does not replace server locking or revision checks. |
| Case return navigation | Shared official-case route helper and actor-scoped return context | URL carries only opaque case ID, tab and mode, never subject, applicant or search text. Opening an authorized case chooses pending/mine/acted from actual server membership. PDF review has an explicit return action; refresh reauthorizes the same case. Search/scroll context is confined to the current actor and cleared at logout. The detail interaction breakpoint matches the 1120px single-column layout. New application is explicit and cannot overwrite a submitted case or silently discard unsaved edits. |
| Dispatch list | Actor/company/tenant scoped keyset page and `internalDispatchPageState` | Scope and optional `needs_reply` filter run before a bounded 50-row page. The pager exposes older records, never describes a loaded page as a complete global count, and preserves the previous page/filter on failure. Stale session responses cannot replace current data. Hosted listing uses one bounded RPC instead of a detail request per row. |
| Dispatch retry | Actor-scoped content digest to random intent key, transactional mutation ledger | The same uncertain create retry reuses its key; a confirmed success clears it so an intentional new dispatch is distinct. Browser storage contains only hashes and random keys, with an in-memory fallback. Case, recipients, audit and notification outbox commit once together; no external email runs inside the transaction. Existing callers without a key remain compatible but cannot claim retry deduplication. |
| Dispatch close and handover | Backend state transaction and canonical workspace confirmation | A required pending reply blocks closure in UI and server. Cancellation performs no write. Reassignment moves only unfinished required work to the successor; the old recipient becomes `reassigned`/已移交 and retains historical identity and replies. The successor gains the linked case/attachment/reply access without broadening other-company permissions. |
| Approved original scan exception | `seal_scan_exceptions.py`, immutable exact-byte allowlist and database guards | The owner's 2026-10-13 approval applies only to the 22 identified PNG crops of the confirmed 1:1 20260914 source. Preserve their 200 DPI pixels and scan-derived width/height; other uploads retain 250 DPI validation. Catalog metadata, by itself, is not an uploaded or usable stamp. |
| Additional native original scan | `seal_scan_20261013.py` and the exact-policy facade | The separately approved 1:1 20261013 source supplies exactly six New Taipei-selected primary large/small stamps for three explicit Finance units. Its immutable 120 DPI registry preserves native pixels and individually rounded physical canvas dimensions, never a forced square. The Taipei alternative and every unknown source remain outside this policy; the old 22-file batch and ordinary 250 DPI rule remain unchanged. Upload/current/locked-version/output authority still requires exact slot, hash, dimensions and usable backing validation. |
| Cancel / recovery | Upload controller and pending intent | Abort only owned transfer. Keep text and PDF in this page. Explicit retry synchronizes the same intent. Do not cancel an uncertain server finalization. |
| Preview library | `ensurePdfJsLibrary` | Failed promise is not cached permanently; bounded retry can recover without reloading the whole app. Concurrent requests share one load. |
| Reopen existing case | `loadUploadedEditorState` | Old case remains active until all required authorized sources validate. Detail and state reads must match the exact locked revision. Two-file bounded concurrency; visible source first. |
| Opening feedback | `createUploadedEditorOpeningPreview` | Immediate inline status, optional readonly original preview, cancel before atomic commit and inline retry. Never show the original as the sent/approved version. |
| Approved download | `downloadElectronicSealFinalFile` | Queue may be slim; fresh detail must authorize the exact committed final-file ID/type and current session. Fail closed with no candidate fallback. |

## Acceptance gates

1. Delaying real local draft/intent preparation or transfer does not delay
   normal A4 local editing. Selection-to-editor timing includes all local work;
   server intent acquisition and durable cloud save are separately measured.
2. Editing while pending cannot submit; cancellation/retry retains those edits
   and only server-confirmed synchronization shows saved.
3. A final chunk committed before a lost response resumes by HEAD at the same
   TUS resource, with no duplicate creation or immutable-object overwrite.
4. Timeout, cancel, library failure and missing/unauthorized files terminate
   with actionable recovery and no false success.
5. Reopen loads at most two assets concurrently and may preview the first;
   cancellation/failure or old-case edits prevent destructive switching.
6. Concurrent submission mismatches are rejected before active-state commit.
7. Approved downloads remain visible in slim rows; fresh authorization and
   exact locked/final version checks are mandatory.
8. Six synthetic roles on desktop/tablet/mobile retain usable actions, no
   horizontal overflow, cross-company denial and conflict protection.
9. Editing application fields before/during/after upload preserves the same
   PDF draft and applies only the latest values; company changes cannot reuse
   foreign stamps, prior seam groups or stale prepared output.
10. Concurrent metadata/save/preflight/submit operations have one serial
    authoritative order. Stale content/editor versions cannot create workflow
    rows or output from a superseded snapshot.
11. Stamp choices come only from available files for the selected owner/type;
    an absent original is distinct from an unregistered digital current file.
12. Approval action works in both comment/checkbox interaction orders; 1120px,
    tablet, mobile and enlarged-text evidence remains readable. Acted membership
    survives detail hydration; own-case links, PDF back/refresh and new-case
    actions preserve the authorized selected case and existing submitted data.
13. More than 300 dispatches remain discoverable through scoped pagination and
    the pending-reply filter. A lost successful create response followed by a
    retry produces one case and one notification per recipient. Pending replies
    block closure; successor handover retains original audit/reply history.
14. Draft, correction, pending, approved, closed and non-owner read-only editor
    states show consistent labels and available actions. Read-only inspection,
    refresh and navigation do not change document versions, elements or files.
15. Two companies, an institution, long names, missing identity, directory
    failure and session changes never display an unrelated company as the
    case owner. Issuing/sealing unit and applicant department remain distinct.

Local synthetic browser tests do not establish physical iOS Safari acceptance
or authenticated production-business workflow proof. Production checks are
read-only public health/readiness, released static hashes and access denials.
Non-A4 conversion and very large/scanned PDFs remain dependent on actual file
complexity, server processing and network; universal two-second readiness is
not a truthful guarantee.
