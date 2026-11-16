# Design

## Context

See `proposal.md` for the motivation and `specs/` for observable behavior. The current room creation accepts `.xlsx` uploads and the parser uses worksheet values, merged ranges, and cell coordinates. Room submission history is persisted in SQLite; the result service derives current winners and applies the configured question cap. The current teacher page contains duplicate `teacher-progress` and `teacher-results` IDs, and the student result board does not replace the answer form.

The requested Google credential is a Service Account JSON key file. The `.env` value will contain only the path to that file; teachers must share each source spreadsheet with the Service Account email and grant edit access for writeback.

## Goals / Non-Goals

**Goals:**

- Add a Google Sheets source adapter while retaining the current `.xlsx` upload path.
- Persist enough source metadata and original cell values to safely map, validate, and update answer cells.
- Keep winner selection, cooldown, cap checks, and submission ordering authoritative and transactional on the server.
- Avoid exposing Service Account credentials or access tokens to clients, the database, or application logs.

**Non-Goals:**

- Do not implement teacher-by-teacher OAuth or domain-wide delegation; the deployment Service Account is the only Google identity in this change.
- Do not search a teacher's Drive or change sharing permissions. Teachers share the specific sheet with the Service Account themselves.
- Do not remove `.xlsx` upload or downloadable filled-workbook export.
- Do not change the existing one-active-window-per-group rule or add multi-process WebSocket infrastructure.

## Decisions

### Use one server-side Service Account for Sheets and Drive export

Read the configured `GOOGLE_SERVICE_ACCOUNT_FILE` path, create Google credentials on the server, and request only the scopes needed for Sheets read/write and Drive read-only export. The JSON file remains outside the repository; `.env.example` contains a sample path only. Errors returned to teachers are normalized and must not include credential contents, private keys, or access tokens.

The Google Sheets API `spreadsheets.get` can return selected grid data and sheet metadata; its `Sheet` resource includes merge ranges. Use a Google-specific adapter to map those values and merges to the existing internal question/slot model, while keeping the current `.xlsx` parser as the file adapter. `spreadsheets.values.batchUpdate` writes cell values, and Drive `files.export` can produce the `.xlsx` snapshot needed by the existing filled-workbook export. See [spreadsheets.get](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/get), [Sheet metadata](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/sheets), [service-account server-to-server OAuth](https://developers.google.com/identity/protocols/oauth2/service-account), and [Drive files.export](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/export).

An alternative is to require teachers to upload `.xlsx` only, which avoids Google credentials but fails the requested link-import and original-sheet-writeback flow. Per-teacher OAuth would avoid pre-sharing with a deployment account but introduces consent screens, refresh-token lifecycle, and user identity management outside the project's current scope.

### Store spreadsheet identity, cell baselines, and the original workbook snapshot

Add nullable source metadata to `rooms`: source kind, spreadsheet ID, selected sheet ID, and configured cooldown seconds. Keep `workbook_blob` populated for Google imports by exporting the source sheet at room creation. Extend answer-slot metadata with the source sheet ID and the cell's imported value. Store each successfully written value separately so later retries can distinguish the system's previous answer from an unrelated teacher edit.

Use the stable numeric sheet ID plus zero-based row/column coordinates for writes; preserve an A1 coordinate for teacher-facing conflict messages and CSV/XLSX mapping. Store only spreadsheet identifiers and cell mappings, never Google credentials or access tokens. Existing `.xlsx` rooms use a source kind of `upload` and retain their current behavior.

### Preflight and atomically write only mapped winner cells

The teacher-only backfill endpoint first computes the current approved winners and reads all corresponding source cells. For each target, allow the write only when the current value matches either the import baseline or the application's last successfully written value. If every target already contains its current winner answer, report the sheet as already synchronized. If any target has an unrelated value, reject the whole operation and list the conflicting cells before writing.

When preflight succeeds, submit all cell updates in one Sheets `spreadsheets.batchUpdate` request using `updateCells` with the field mask restricted to `userEnteredValue`, so existing formatting remains unchanged. Google documents that a Sheets batch update validates all subrequests and applies them atomically; update local last-written values only after the API confirms success. If the process stops after Google succeeds but before local persistence, a retry sees the intended answer already present and can safely report it as synchronized. See [Google Sheets batch requests](https://developers.google.com/workspace/sheets/api/guides/batch).

An alternative is to make one API write per cell; a network failure could then leave a partly completed learning sheet. A narrow race remains if an external editor changes a target cell after preflight but before the batch write; the API does not provide a per-cell compare-and-set in this flow. Keep the preflight-to-write interval short and report conflicts found during the read.

### Reconcile cooldown and winner awards in the existing database transaction

Add a room-level cooldown duration (0–3600 seconds, default 30), a current cooldown deadline and source award reference for each group, and a current award record for each submission bundle. Submission insertion, current winner reconciliation, cap accounting, and cooldown updates must run in one `BEGIN IMMEDIATE` transaction. Check cooldown at server receipt time before assigning a receipt sequence; rejected cooldown submissions do not enter history or affect rank.

Use existing stable receipt order and bundle cap rules when reconciling awards. A newly selected effective winner starts one cooldown for the bundle award (a multi-question bundle counts its full question count toward the existing win cap but starts one cooldown). A group with an active cooldown cannot submit another bundle. On teacher rejection, remove the rejected award, re-run the current award reconciliation, clear the old group's cooldown if it has no other active award source, and start cooldown for a newly promoted winner. Cooldown snapshots and submission errors provide the group only its own remaining time; teacher and projection roles receive no additional private group-session credentials.

An alternative is to calculate cooldown only in JavaScript, but clients can bypass it and simultaneous submissions would disagree. The server transaction remains authoritative; the browser countdown is informational and submission is revalidated on receipt.

### Keep results and teacher progress views singular and role-specific

Remove duplicate IDs from the teacher document and render progress and results into one element each. When the room enters `ended`, hide/remove the student answer board and show the result board; reconnect snapshots restore the same view. Keep active student events free of other groups' answers and candidate state. The existing single-window connection rule stays in force; reconnecting the same group session restores its own submitted and cooldown state.

## Risks / Trade-offs

- [The Service Account is not automatically allowed to read a teacher's sheet] → Show the Service Account email and a concise sharing instruction; fail room creation cleanly until read access is granted.
- [Drive or Sheets API can be disabled, rate-limited, or temporarily unavailable] → Make one bounded import/export request per operation, return a retryable status without claiming success, and keep the `.xlsx` workflow available.
- [A source cell may be manually edited between import and backfill] → Compare against import baseline and last application write, stop the entire batch on detected conflicts, and identify affected cell coordinates.
- [A process can fail after a successful remote write] → Make backfill idempotent by treating cells already containing current winner answers as synchronized before updating local sync metadata.
- [Cooldown, caps, and teacher rejection interact with concurrent submissions] → Serialize reconciliation with the same SQLite immediate transaction and test concurrent requests, bundle wins, cooldown expiry, and rejection promotion.
- [A credential path accidentally points into the repository] → Document an external secret-file location, ignore local `.env` and credential patterns, and scan sample files; never log credential file contents.

## Migration Plan

1. Back up the SQLite database and configure `GOOGLE_SERVICE_ACCOUNT_FILE` with a path to a deployment-managed JSON file outside the repository. Enable Google Sheets API and Drive API for the deployment project, then share a test sheet with the Service Account email.
2. Apply a new additive SQLite migration. Existing rooms receive source kind `upload`, no Google identifiers, and no retroactive cooldown; new rooms use the 30-second default unless configured otherwise.
3. Deploy the adapter, teacher controls, cooldown reconciliation, and result-view changes. Verify import, conflict-safe writeback, and `.xlsx` export with a disposable shared sheet before classroom use.
4. To roll back the application, deploy the prior version while retaining the additive columns. Google Sheet writes already completed remain in the source sheet; do not automatically reverse them. Database backup restoration is only needed if the new migration itself must be removed.
