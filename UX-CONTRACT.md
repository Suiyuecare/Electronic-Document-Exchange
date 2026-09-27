# File workflow contract

This is a focused contract for the 2026-09-28 file-resilience changes. Existing
Finance-aligned UI and approval/security contracts remain in force.

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
