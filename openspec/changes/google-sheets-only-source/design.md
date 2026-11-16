# Design

## Context

See `proposal.md` and `specs/guided-notes-google-sheets/spec.md` for the behavior change. The current teacher UI and room API support both `.xlsx` upload and Google Sheet links. The Google adapter also exports a Drive `.xlsx` snapshot for the download endpoint. Room rows already store source type and workbook bytes; existing databases may contain rooms created by either source.

## Goals / Non-Goals

**Goals:**

- Route every new room through Google Sheet URL validation and server-side Service Account access.
- Remove the teacher's file-upload control, upload API branch, filled `.xlsx` download control, and matching API endpoint.
- Keep answer backfill, CSV history export, room/session history, and student/projector behavior.
- Set the ignored local `.env` variable to the existing JSON file's repo-relative path under `credential/`, without opening or copying key contents.
- Restrict Google credentials to the Sheets API scope needed for import, cell reads, and batch writes.

**Non-Goals:**

- Delete existing room, submission, or workbook data, or revoke already completed sheet writes.
- Remove the internal Guided Notes workbook parser if it remains useful for converting API grid data into the existing question mapping.
- Change race ranking, review, cooldown, CSV, projection, or room-window rules.

## Decisions

### Make the existing room-creation API Google-only

Require `sheet_url` for `POST /api/rooms` and remove `UploadFile`, file-size checks, ZIP validation, and the Excel branch from that endpoint. Keep URL validation before any Google request, so malformed or unsupported links do not contact an arbitrary host. This keeps a single room-creation contract and prevents the old file route from remaining available outside the UI. An alternative is to keep a hidden compatibility upload branch; that would contradict the single-source requirement and leave the retired behavior callable.

### Stop exporting XLSX snapshots and copies

Change `GoogleSheetsAdapter` to return the grid-derived internal workbook bytes and sheet metadata without calling Drive `files.export`. Remove Drive service construction and the `drive.readonly` scope. Remove the teacher download control, `/export/guided-notes.xlsx` endpoint, and service method that fills an XLSX copy. Keep the internal workbook bytes in the existing non-null database column for compatibility; no schema migration or destructive cleanup is needed. The existing sheet-cell writeback remains the only document write operation. Keep the CSV endpoint unchanged.

An alternative is retaining Drive export only for legacy rooms. Existing rooms already contain their stored workbook bytes and can be retained as historical data; a download feature for those rooms was explicitly excluded, so continuing to request Drive access would add a permission the product no longer needs.

### Configure the existing Service Account path locally

Set `GOOGLE_SERVICE_ACCOUNT_FILE` in the ignored project-root `.env` to the existing `credential/<JSON filename>` relative path. Keep `.env.example` as a non-secret placeholder and never copy key contents into it. The app loads `.env` from its working directory, so document launching the app from the project root. Keep the current `credential/` ignore rule. Do not open the key JSON as part of this change; test configuration with a temporary path and mocks.

### Preserve legacy data without legacy file features

Do not migrate or delete rooms whose `source_type` is `upload`. The new API will not create additional upload rooms, while existing records and submission results remain readable. Remove XLSX download behavior uniformly for all rooms. This avoids a table rebuild and preserves classroom history.

## Risks / Trade-offs

- [Teachers can no longer create offline rooms from an Excel file] → Explain that room creation requires a Google Sheet shared with the configured Service Account.
- [The API contract no longer accepts `file`] → Return a clear validation error when callers submit a file without a Sheet URL.
- [A local `.env` points to the wrong working-directory-relative path] → Document the project-root launch command and validate that the configured file exists without exposing its contents.
- [Old tests and documentation assume XLSX upload/export] → Replace those expectations with Google mock import, endpoint-removal, CSV-preservation, and legacy-record-retention tests.

## Migration Plan

1. Confirm `.env` remains ignored and its Google credential path targets the existing JSON under ignored `credential/`; keep `.env.example` free of key material.
2. Deploy the Google-only UI/API and remove Drive export scope and calls. No database migration is required; existing rows remain untouched.
3. Update callers to submit a Google Sheet URL. Validate source import, conflict-safe writeback, CSV export, and legacy room reads with mocks and the full test suite.
4. Roll back by restoring the previous application version; retained SQLite room/workbook data remains available to that version. No automatic deletion or reverse write to Google Sheets is performed.
