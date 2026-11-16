import pytest
from io import BytesIO
from openpyxl import load_workbook

from app.guided_notes import parse_guided_notes
from app.services.google_sheets import GoogleSheetReference, GoogleSheetsAdapter, GoogleSheetsError, parse_google_sheet_url, spreadsheet_to_xlsx


VALID_ID = "1dHJOnfihH0J2OPeqzkMofJD17TXMsT10PfVDbCqW7aQ"


@pytest.mark.parametrize(
    ("url", "gid"),
    [
        (f"https://docs.google.com/spreadsheets/d/{VALID_ID}/edit?usp=sharing", None),
        (f"https://docs.google.com/spreadsheets/d/{VALID_ID}/edit?gid=123#gid=123", 123),
        (f"https://docs.google.com/spreadsheets/d/{VALID_ID}/edit#gid=456", 456),
    ],
)
def test_parse_google_sheet_reference(url, gid):
    reference = parse_google_sheet_url(url)
    assert reference.spreadsheet_id == VALID_ID
    assert reference.gid == gid


@pytest.mark.parametrize(
    "url",
    [
        "https://docs.google.com/spreadsheets/d/edit?gid=123",
        f"https://evil.example/spreadsheets/d/{VALID_ID}/edit",
        f"https://docs.google.com.evil.example/spreadsheets/d/{VALID_ID}/edit",
        f"http://docs.google.com/spreadsheets/d/{VALID_ID}/edit",
        f"https://docs.google.com/spreadsheets/d/{VALID_ID}/edit?gid=abc",
    ],
)
def test_rejects_invalid_sheet_urls_without_network_calls(url):
    with pytest.raises(GoogleSheetsError):
        parse_google_sheet_url(url)


@pytest.mark.parametrize("fixture", ["guided-notes-single.xlsx", "guided-notes-group.xlsx"])
def test_google_grid_adapter_preserves_template_questions_groups_and_slots(fixture):
    source_bytes = open(f"tests/fixtures/{fixture}", "rb").read()
    source = load_workbook(BytesIO(source_bytes), data_only=False)
    source_ws = source["學習單"]
    rows = []
    for row in source_ws.iter_rows():
        values = []
        for cell in row:
            item = {}
            if cell.value is not None:
                item["userEnteredValue"] = {"stringValue": str(cell.value)}
            values.append(item)
        rows.append({"values": values})
    merges = [
        {
            "startRowIndex": area.min_row - 1,
            "endRowIndex": area.max_row,
            "startColumnIndex": area.min_col - 1,
            "endColumnIndex": area.max_col,
        }
        for area in source_ws.merged_cells.ranges
    ]
    response = {
        "sheets": [{
            "properties": {"sheetId": 77, "title": "學習單"},
            "merges": merges,
            "data": [{"startRow": 0, "startColumn": 0, "rowData": rows}],
        }]
    }
    converted, title, gid = spreadsheet_to_xlsx(response, 77)
    target = parse_guided_notes(converted, "google-export.xlsx")
    expected = parse_guided_notes(source_bytes, fixture)
    assert title == "學習單"
    assert gid == 77
    assert target.as_dict() == expected.as_dict()
    source.close()


def test_readme_keeps_xlsx_flow_and_documents_google_requirements():
    readme = open("README.md", encoding="utf-8").read()
    assert "Google Sheets API 與 Google Drive API" in readme
    assert "Service Account 電子郵件" in readme
    assert "GOOGLE_SERVICE_ACCOUNT_FILE" in readme
    assert "未設定 Service Account 時，原有 `.xlsx` 上傳流程仍可使用" in readme


class ApiRequest:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result


class FakeSheetsService:
    def __init__(self, response):
        self.response = response
        self.get_args = None
        self.read_args = None
        self.batch = None

    def spreadsheets(self):
        return self

    def get(self, **kwargs):
        self.get_args = kwargs
        return ApiRequest(self.response)

    def values(self):
        return self

    def batchGet(self, **kwargs):
        self.read_args = kwargs
        return ApiRequest({"valueRanges": [{"values": [["現有值"]]}, {}]})

    def batchUpdate(self, **kwargs):
        self.batch = kwargs
        return ApiRequest({"replies": []})


class FakeDriveService:
    def files(self):
        return self

    def export(self, **kwargs):
        self.export_args = kwargs
        return ApiRequest(b"xlsx-snapshot")


def test_google_adapter_reads_sheet_and_performs_one_atomic_batch_request():
    response = {"sheets": [{
        "properties": {"sheetId": 77, "title": "學習單"},
        "merges": [],
        "data": [{"startRow": 0, "startColumn": 0, "rowData": [
            {"values": [{"userEnteredValue": {"stringValue": "題號"}}, {"userEnteredValue": {"stringValue": "作答"}}]},
            {"values": [{"userEnteredValue": {"stringValue": "Q1"}}, {}]},
        ]}],
    }]}
    sheets = FakeSheetsService(response)
    drive = FakeDriveService()
    adapter = GoogleSheetsAdapter(sheets, drive)
    data, title, gid, snapshot = adapter.import_sheet(GoogleSheetReference(VALID_ID, 77))
    assert parse_guided_notes(data, "mock.xlsx").questions[0].id == "Q1"
    assert (title, gid, snapshot) == ("學習單", 77, b"xlsx-snapshot")
    assert sheets.get_args["includeGridData"] is True
    assert drive.export_args["mimeType"].endswith("spreadsheetml.sheet")
    assert adapter.read_cells(VALID_ID, title, ["B2", "C3"]) == {"B2": "現有值", "C3": None}
    adapter.write_cells(VALID_ID, gid, [{"coordinate": "B2", "value": "回填值"}])
    assert len(sheets.batch["body"]["requests"]) == 1
    request = sheets.batch["body"]["requests"][0]["updateCells"]
    assert request["range"]["sheetId"] == 77
    assert request["rows"][0]["values"][0]["userEnteredValue"]["stringValue"] == "回填值"
