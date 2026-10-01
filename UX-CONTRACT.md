# Workspace interaction and file workflow contract

This contract covers file resilience, fluid interaction, compose submission and
the 2026-10-02 draft-navigation change.
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
| Navigation | `setView` and seven major routes, including `drafts` | Immediate selected view; same-route operations preserve scroll/focus; returning restores route scroll only within the current in-memory session; a changed route focuses its title. Integrated sub-sections retain their intentional section navigation. `草稿編輯` appears in the Finance-aligned left navigation and mobile drawer, while the four-item mobile bottom bar stays unchanged. |
| Draft recovery | `composeDraftNavCount`, `composeDraftList` and the scoped compose-draft APIs | `撰寫公文` never automatically restores a prior-session draft or presents an inline resume prompt; it retains the current in-session form when navigating away and back. The separate `草稿編輯` route lists only the authenticated user's unarchived cloud drafts, paginates without duplicates, and shows a distinct card for unsynced local content. A user explicitly chooses `繼續編輯`; switching cannot discard current unsaved input or selected local attachments. |
| Draft count | `/api/compose-drafts/count` plus a genuinely local-only draft | Badge and accessible name report the exact private cloud total, including unloaded pages. Add one for a local-only draft without a cloud ID; if an ID was assigned but its first write is indeterminate, probe that ID under the same authenticated owner/company before adding one. Unsynced changes to an existing cloud draft show a local recovery card but never double-count it. Hide the numeric badge while the authoritative count or probe is unavailable rather than claim an exact total. Refresh after save, archive, session change and explicit list refresh. |
| Background reads | Scoped route loaders and official list transport | Share identical in-flight reads, not mutations; differing query/cursor/session remain separate. Preserve generation, permission and revision guards. Failure can be explicitly retried. |
| Initialization | `initializeDeferredWorkspace` | Ordered cooperative batches yield to interaction. Do not remove initialization or reorder dependency steps. Old-session work must stop. |
| Form input | Existing compose/application lifecycle | During IME composition, hold preview/local/cloud autosave. Commit the final composition before saving; manual transitions cannot submit uncommitted input. Avoid rebuilding unchanged controls. |
| Compose distribution | `composePayload`, cloud draft snapshot and official PDF metadata | 正本 defaults to the current recipient; 副本 defaults to the selected sending company. Both are editable and must survive draft restore, correction and final PDF generation. Manual edits are preserved; changing the sending company only replaces its previous default when that default is still present. An explicitly cleared 副本 prints as 無. |
| Compose submission | `handleComposeSubmitRequest` and `confirmComposeSubmission` | One visible 送出簽核 action opens an app-owned confirmation only after the Finance workflow-readiness check passes. Missing Finance approvers are explained beside that action; the button remains actionable for a fresh check, but no backend mutation bypasses the Finance gate. Cancel/Escape preserves the draft and returns focus. |
| Lists | Existing authorized queue/log renderers | Preserve focused row action, scroll and stable nodes when content is unchanged. Do not restore focus into a different case, hidden control or new actor. |
| Notices | `showToast` | One notice, one owned 4s timer; identical messages do not rewrite the live region. Hover pauses its remaining duration. Persistent inline errors/retry controls remain authoritative. |
| Modal/drawer | Existing modal markup with shared isolation/focus helpers | Inert workspace children, never unset authentication's outer inert gate. Tab containment, Escape/cancel and trigger restoration. Reopening an already visible detail does not steal focus. |
| Motion/layers | `styles.css` | Finance colors/frame unchanged. Shared dialog/toast layer tokens; toast above dialog on all widths. Reduced motion disables travel; no operation waits for animation. |

## Fluid interaction acceptance

- Same-fixture before/after desktop and mobile screenshots for all seven pages;
  tablet checks in the six-role suite. No overflow or inaccessible primary action.
- Route selection and its loading state are synchronous. The local click-to-visible
  view target is at most 0.5 seconds on the tested desktop/mobile fixture;
  authenticated production network/SSO and full data refresh are measured
  separately. Navigation must not wait for reads, and a progress bar must not
  imply that stale data is current.
- The draft-route badge exposes a readable count to assistive technology;
  zero has no numeric badge. A synthetic owner with one cloud draft sees one
  card and count 1 on desktop/tablet/mobile. Another account's drafts are not
  visible. A local-only draft is distinguished from cloud state and never
  silently submitted or sent.
- Browser acceptance explicitly opens a private cloud draft, checks restored
  text, verifies that an unsent local attachment prevents switching, then
  checks that edited text survives a deliberate switch to a second draft.
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
9. The seventh major route exposes the private draft list and count without
   expanding the mobile bottom bar. A draft is restored only by explicit
   choice; refresh failures preserve the current editor and local recovery.

Local synthetic browser tests do not establish physical iOS Safari acceptance
or authenticated production-business workflow proof. Production checks are
read-only public health/readiness, released static hashes and access denials.
Non-A4 conversion and very large/scanned PDFs remain dependent on actual file
complexity, server processing and network; universal two-second readiness is
not a truthful guarantee.
