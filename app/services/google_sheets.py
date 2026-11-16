"""Google Sheets API adapter. Credentials are loaded only from an external file path."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import re
from urllib.parse import parse_qs, urlparse

from openpyxl import Workbook
from openpyxl.utils.cell import get_column_letter

from app.config import get_settings


class GoogleSheetsError(ValueError):
    def __init__(self, message: str, code: str = "invalid_sheet"):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class GoogleSheetReference:
    spreadsheet_id: str
    gid: int | None


_ID = re.compile(r"^[A-Za-z0-9_-]{20,}$")


def parse_google_sheet_url(url: str) -> GoogleSheetReference:
    try:
        parsed = urlparse(url.strip())
        if parsed.scheme != "https" or parsed.hostname != "docs.google.com" or parsed.port:
            raise ValueError
        match = re.fullmatch(r"/spreadsheets/d/([^/]+)(?:/(?:edit|view))?/?", parsed.path)
        if not match or not _ID.fullmatch(match.group(1)):
            raise ValueError
        query = parse_qs(parsed.query)
        fragment = parse_qs(parsed.fragment.lstrip("#?"))
        gid_value = query.get("gid", fragment.get("gid", [None]))[0]
        if gid_value is None:
            return GoogleSheetReference(match.group(1), None)
        if not gid_value.isdecimal():
            raise ValueError
        return GoogleSheetReference(match.group(1), int(gid_value))
    except (ValueError, AttributeError):
        raise GoogleSheetsError("請提供有效的 Google Sheets 試算表連結。") from None


def build_google_services(settings=None):
    settings = settings or get_settings()
    credential_file = settings.google_service_account_file
    if not credential_file or not credential_file.is_file():
        raise GoogleSheetsError("尚未設定有效的 Service Account JSON 路徑。", "credentials_missing")
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    credentials = Credentials.from_service_account_file(
        str(credential_file),
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.readonly",
        ],
    )
    return (
        build("sheets", "v4", credentials=credentials, cache_discovery=False),
        build("drive", "v3", credentials=credentials, cache_discovery=False),
    )


def _cell_value(cell: dict):
    entered = cell.get("userEnteredValue", {})
    if "stringValue" in entered:
        return entered["stringValue"]
    if "numberValue" in entered:
        return entered["numberValue"]
    if "boolValue" in entered:
        return entered["boolValue"]
    return cell.get("formattedValue")


def spreadsheet_to_xlsx(spreadsheet: dict, gid: int | None = None) -> tuple[bytes, str, int]:
    sheets = spreadsheet.get("sheets", [])
    selected = next((s for s in sheets if gid is not None and s.get("properties", {}).get("sheetId") == gid), None)
    if gid is None:
        selected = next((s for s in sheets if s.get("properties", {}).get("title") == "學習單"), None)
        selected = selected or (sheets[0] if sheets else None)
    if selected is None:
        raise GoogleSheetsError("連結指定的工作表不存在。", "sheet_not_found")
    props = selected.get("properties", {})
    title = props.get("title", "學習單")
    sheet_id = props.get("sheetId")
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]
    grid_data = selected.get("data", [])
    for block in grid_data:
        start_row = block.get("startRow", 0)
        start_col = block.get("startColumn", 0)
        for row_offset, row in enumerate(block.get("rowData", [])):
            for col_offset, cell in enumerate(row.get("values", [])):
                value = _cell_value(cell)
                if value is not None:
                    ws.cell(start_row + row_offset + 1, start_col + col_offset + 1).value = value
    for merge in selected.get("merges", []):
        r1, r2 = merge.get("startRowIndex", 0) + 1, merge.get("endRowIndex", 1)
        c1, c2 = merge.get("startColumnIndex", 0) + 1, merge.get("endColumnIndex", 1)
        ws.merge_cells(f"{get_column_letter(c1)}{r1}:{get_column_letter(c2)}{r2}")
    output = BytesIO()
    wb.save(output)
    wb.close()
    return output.getvalue(), title, int(sheet_id)


class GoogleSheetsAdapter:
    def __init__(self, sheets_service=None, drive_service=None):
        self.sheets_service = sheets_service
        self.drive_service = drive_service

    def _services(self):
        if self.sheets_service is None or self.drive_service is None:
            self.sheets_service, self.drive_service = build_google_services()
        return self.sheets_service, self.drive_service

    def import_sheet(self, reference: GoogleSheetReference):
        sheets, drive = self._services()
        try:
            source = sheets.spreadsheets().get(
                spreadsheetId=reference.spreadsheet_id,
                includeGridData=True,
                fields="spreadsheetId,properties(title),sheets(properties(sheetId,title),merges,data(startRow,startColumn,rowData(values(userEnteredValue,formattedValue))))",
            ).execute()
            data, title, gid = spreadsheet_to_xlsx(source, reference.gid)
            snapshot = drive.files().export(
                fileId=reference.spreadsheet_id,
                mimeType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ).execute()
            if isinstance(snapshot, str):
                snapshot = snapshot.encode("latin1")
            return data, title, gid, bytes(snapshot)
        except GoogleSheetsError:
            raise
        except Exception as exc:
            status = getattr(getattr(exc, "resp", None), "status", None)
            if status in (401, 403):
                raise GoogleSheetsError("Service Account 無法讀取此試算表，請確認已分享檔案。", "permission_denied") from exc
            raise GoogleSheetsError("讀取 Google Sheet 失敗，請檢查連結與 API 設定。", "google_api_error") from exc

    def read_cells(self, spreadsheet_id: str, worksheet_name: str, coordinates: list[str]) -> dict[str, str | None]:
        sheets, _ = self._services()
        escaped = worksheet_name.replace("'", "''")
        ranges = [f"'{escaped}'!{cell}" for cell in coordinates]
        try:
            result = sheets.spreadsheets().values().batchGet(
                spreadsheetId=spreadsheet_id, ranges=ranges,
                valueRenderOption="UNFORMATTED_VALUE",
            ).execute()
        except Exception as exc:
            status = getattr(getattr(exc, "resp", None), "status", None)
            if status in (401, 403):
                raise GoogleSheetsError("Service Account 沒有此試算表的讀取權限。", "permission_denied") from exc
            raise GoogleSheetsError("讀取回填目標失敗。", "google_api_error") from exc
        values = {}
        for coordinate, item in zip(coordinates, result.get("valueRanges", [])):
            rows = item.get("values", [])
            values[coordinate] = rows[0][0] if rows and rows[0] else None
        return values

    def write_cells(self, spreadsheet_id: str, sheet_id: int, cells: list[dict]) -> None:
        sheets, _ = self._services()
        from openpyxl.utils.cell import coordinate_to_tuple

        requests = []
        for item in cells:
            row, column = coordinate_to_tuple(item["coordinate"])
            requests.append({
                "updateCells": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": row - 1,
                        "startColumnIndex": column - 1,
                    },
                    "rows": [{"values": [{"userEnteredValue": {"stringValue": item["value"]}}]}],
                    "fields": "userEnteredValue",
                }
            })
        try:
            sheets.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id, body={"requests": requests}
            ).execute()
        except Exception as exc:
            status = getattr(getattr(exc, "resp", None), "status", None)
            if status in (401, 403):
                raise GoogleSheetsError("Service Account 沒有此試算表的編輯權限。", "permission_denied") from exc
            raise GoogleSheetsError("Google Sheet 批次回填失敗，來源未更新。", "google_api_error") from exc
