# Workspace interaction and file workflow contract

This contract covers the 2026-09-28 file-resilience, fluid-interaction and compose-submission changes.
Existing Finance-aligned visual identity and approval/security contracts remain
in force. "Apple-like" means continuous, responsive interaction, not Apple
branding or a promise of zero network latency.

## Canonical UI Map

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
| --- | --- | --- | --- | --- |
| Form | Existing application inputs and draft lifecycle in app.js | Authorized document detail and content revision | Native controls; existing inline text editor | Six-role browser and application-autosave tests |
| CRUD | backendRequest and scoped editor lifecycle | Backend revision, locked request and immutable assets | Explicit retry; no automatic mutation replay | Scope, reopen, download and transport resilience tests |
| Toast | showToast plus persistent upload/opening status | The current scoped operation result | Toast is supplemental, never the only recovery surface | Browser failure/cancel/retry journeys |
| Scrollbar | Browser viewport and existing styles.css overflow rules | Native scroll position | Existing PDF stage and queue scrolling | Desktop/tablet/mobile overflow checks |
| Select/Listbox | Existing native select fields | Server-provided companies, categories and seals | No replacement or new popup in this change | Six-role selection/upload journeys |
| Date | Existing native compose date input | User-entered date with existing today default | Unchanged and outside the file-resilience release | Existing compose regressions |
| Table Selection | Electronic-seal queue uses row actions, not bulk selection | Authorized paginated cases | No selectable table introduced | Slim-row download fixture |

## Shared interaction owners

| Capability | Canonical owner | Contract |
| --- | --- | --- |
| Navigation | `setView` and six existing major routes | Immediate selected view; same-route operations preserve scroll/focus; returning restores route scroll only within the current in-memory session; a changed route focuses its title. Integrated sub-sections retain their intentional section navigation. |
| Background reads | Scoped route loaders and official list transport | Share identical in-flight reads, not mutations; differing query/cursor/session remain separate. Preserve generation, permission and revision guards. Failure can be explicitly retried. |
| Initialization | `initializeDeferredWorkspace` | Ordered cooperative batches yield to interaction. Do not remove initialization or reorder dependency steps. Old-session work must stop. |
| Form input | Existing compose/application lifecycle | During IME composition, hold preview/local/cloud autosave. Commit the final composition before saving; manual transitions cannot submit uncommitted input. Avoid rebuilding unchanged controls. |
| Compose distribution | `composePayload`, cloud draft snapshot and official PDF metadata | 正本 defaults to the current recipient; 副本 defaults to the selected sending company. Both are editable and must survive draft restore, correction and final PDF generation. Manual edits are preserved; changing the sending company only replaces its previous default when that default is still present. An explicitly cleared 副本 prints as 無. |
| Compose submission | `handleComposeSubmitRequest` and `confirmComposeSubmission` | One visible 送出簽核 action opens an app-owned confirmation only after the Finance workflow-readiness check passes. Missing Finance approvers are explained beside that action; the button remains actionable for a fresh check, but no backend mutation bypasses the Finance gate. Cancel/Escape preserves the draft and returns focus. |
| Lists | Existing authorized queue/log renderers | Preserve focused row action, scroll and stable nodes when content is unchanged. Do not restore focus into a different case, hidden control or new actor. |
| Notices | `showToast` | One notice, one owned 4s timer; identical messages do not rewrite the live region. Hover pauses its remaining duration. Persistent inline errors/retry controls remain authoritative. |
| Modal/drawer | Existing modal markup with shared isolation/focus helpers | Inert workspace children, never unset authentication's outer inert gate. Tab containment, Escape/cancel and trigger restoration. Reopening an already visible detail does not steal focus. |
| Approval actions | Server `available_actions` and existing `officialDecisionModal` | Withdraw only while approval is pending and stamping has not been claimed. Return previous reopens the approved predecessor without applicant editing. Correction is resumable; decline is terminal. Shared review checkboxes start disabled, enable only after the corresponding successful view/download, and require manual acknowledgement for all approver decisions. Destructive decline initially focuses Cancel. Server errors preserve entered reason; conflicts refresh the case and require fresh review. |
| Offboarding handover | Company-scoped handover API, `official-handover-ui.js` and the existing 簽核進度 route | A separate operational queue is visible only to live Finance general affairs and administrative directors. General affairs proposes; a different administrative director confirms or declines. This business-owned dialog uses shared overlay isolation and focus helpers, but its acknowledgement is not file review or document approval. Bounded paginated reads, server CAS, explicit mutation retry with the same operation ID, and preserved reasons are mandatory. Session changes clear the queue and prevent stale response commits. |
| Motion/layers | `styles.css` | Finance colors/frame unchanged. Shared dialog/toast layer tokens; toast above dialog on all widths. Reduced motion disables travel; no operation waits for animation. |

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
| PDF transport | `performTusUpload` | Real byte progress, external cancellation, bounded chunk/HEAD requests. Same intent retries reuse the existing TUS resource and authoritative remote offset; immutable object storage is retained. |
| Local A4 editing | `handleUploadedSealPdfChange` | Validated local A4 opens before transfer. No persistent sensitive local draft is introduced. Unsynced edits remain in memory; save/submit stays gated until finalization and state save succeed. |
| Cancel / recovery | Upload controller and pending intent | Abort only owned transfer. Keep text and PDF in this page. Explicit retry synchronizes the same intent. Do not cancel an uncertain server finalization. |
| Preview library | `ensurePdfJsLibrary` | Failed promise is not cached permanently; bounded retry can recover without reloading the whole app. Concurrent requests share one load. |
| Reopen existing case | `loadUploadedEditorState` | Old case remains active until all required authorized sources validate. Detail and state reads must match the exact locked revision. Two-file bounded concurrency; visible source first. |
| Opening feedback | `createUploadedEditorOpeningPreview` | Immediate inline status, optional readonly original preview, cancel before atomic commit and inline retry. Never show the original as the sent/approved version. |
| Approved download | `downloadElectronicSealFinalFile` | Queue may be slim; fresh detail must authorize the exact committed final-file ID/type and current session. Fail closed with no candidate fallback. |

## Acceptance gates

1. Delaying real local transfer does not delay normal A4 local editing; real
   selection-to-editor timing includes preparation and intent acquisition.
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

Local synthetic browser tests do not establish physical iOS Safari acceptance
or authenticated production-business workflow proof. Production checks are
read-only public health/readiness, released static hashes and access denials.
Non-A4 conversion and very large/scanned PDFs remain dependent on actual file
complexity, server processing and network; universal two-second readiness is
not a truthful guarantee.
