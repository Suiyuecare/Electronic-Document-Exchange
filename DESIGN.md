---
version: alpha
name: "Suiyue eDoc"
description: "Finance-aligned electronic-document and sealing workspace"
colors:
  primary: "#ea880c"
  readable-action: "#b45309"
  ink: "#2f2a26"
  muted: "#6e6259"
  line: "#f1cfa8"
  panel: "#ffffff"
  cream: "#fff9f2"
  danger: "#b42318"
typography:
  sans:
    fontFamily: '"PingFang TC", "Microsoft JhengHei", "Noto Sans TC", sans-serif'
omitted:
  - section: spacing
    reason: "Existing component-specific spacing remains canonical in styles.css."
  - section: rounded
    reason: "Existing component-specific radii remain canonical in styles.css."
components:
  button: {}
  card: {}
  dialog: {}
  upload: {}
---

# Suiyue eDoc design context

## Overview

The visual reference is the group's Finance workspace, as requested by the
product owner: warm cream surfaces, orange accents, compact labelled actions,
the shared sidebar and header. This is an operational product, not a new brand
or marketing page. Employees create documents; supervisors review exact locked
versions; general affairs and administrators manage sealing and traceability.

The market evidence is the project's Taiwan electronic-document exchange
requirements and the owner's Traditional Chinese workflows. The UI language is
Traditional Chinese. Desktop, tablet and phone layouts must preserve the same
business rules. Native copy review belongs to the product owner.

This file mirrors, rather than generates, the existing canonical runtime tokens
in `styles.css :root`. `primary` maps to `--accent`, `readable-action` to
`--accent-readable`, and other color names to the same-named variables, except
`danger` maps to `--rose`. No runtime palette was changed for the file-resilience
release. Existing PDF-editor semantic state colors remain component-owned.

## Colors

Cream provides the workspace background; white panels separate tasks; the line
token identifies boundaries. Orange identifies selected navigation and actions.
Readable-action is the existing darker action token. Progress, warnings and
failures always include text or an accessible label, never color alone.

## Typography

Controls use the runtime sans-serif stack above. The existing official-document
font is scoped to document rendering/output and must not replace UI typography.
Technical details such as revisions and IDs stay secondary to the user's task.

## Layout

Keep the existing responsive shell, application/editor split and mobile action
layout. New opening feedback belongs directly before the existing editor. It
wraps on narrow screens; optional preview canvases fit their panel. Preserve
44px minimum touch targets and the existing 16px mobile field sizing.

## Elevation & Depth

Use existing panel boundaries and shared shadows. A progress update is inline;
it does not open a blocking modal, cover the user's previous case or add a new
navigation layer. Conversion confirmation retains its established dialog.

## Shapes

Use shared button and panel classes. Do not add a separate pill, card-radius or
shadow system for loading and retry actions.

## Components

### Foundational visual states

Use the existing save-status, real transfer progress, retry and locked-state
owners. In-memory editing is not server-saved. A readonly original preview is
explicitly different from an authoritative confirmation or approved file.

### Buttons and actions

Retain concise labelled actions. Busy downloads prevent duplicate clicks;
cancel ends transmission, not an already-started server finalization. Recovery
acts on the same upload intent or reloads the authoritative case version.

Approval actions distinguish resumable 退回補正 from terminal 不通過（終止案件）.
The latter uses the existing danger treatment and focuses Cancel on opening.
File-review acknowledgements belong to the shared review section, not the
approval-only fields; review confirms inspection, not endorsement of contents.
The server decides which actions are visible at each workflow boundary.

### Navigation and data display

Keep the Finance-aligned sidebar/header frame and colors. Route selection is
immediate, returns retain in-session reading position, and unchanged Header
status is not rewritten. Keep the electronic-seal queue and its pagination;
slim rows obtain exact final-file authority on demand. Background updates must
not destroy the user's current action focus or rebuild unchanged controls.

### Forms and overlays

Preserve application prerequisites, file size/page limits, A4 conversion
consent and the existing conflict/review workflow. Do not add duplicate forms.
Compose and application autosave waits for committed IME text. The existing
detail dialogs share focus/isolation behavior; visible overlays isolate only
workspace children, never clear the authentication gate's outer inert state.
Runtime `--z-workspace-dialog` and `--z-workspace-toast` own dialog/toast layers
for all widths. The supplemental toast stays above dialogs, lasts four seconds
from its latest result, and pauses while hovered.

### Iconography

Reuse existing icons and labelled buttons; no new icon family is introduced.

### Motion

Motion communicates real work. Use the existing progress/reduced-motion rules;
do not animate fake percentages or declare completion before server response.
Reduced-motion removes continuous travel and smooth scrolling across existing
components. Navigation, save and upload logic never wait for an animation.

### Content and data visualization

Short status copy tells users what is happening and the next action. Persistent
failure feedback stays beside the relevant operation; toasts are supplemental.

## Do's and Don'ts

- Do preserve the Finance-aligned identity and shared classes.
- Do distinguish editable-local, transmitting, saved and locked states.
- Do retain input and original files on recoverable failures.
- Don't label partially loaded or unsynchronized data as authoritative.
- Don't expose inaccessible file candidates as approved downloads.
- Don't promise a universal network or large-PDF timing guarantee.
