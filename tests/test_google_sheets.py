import pytest
from io import BytesIO
from openpyxl import load_workbook

from app.guided_notes import parse_guided_notes
from app.services.google_sheets import GoogleSheetReference, GoogleSheetsAdapter, GoogleSheetsError, parse_google_sheet_url, spreadsheet_to_xlsx


VALID_ID = "1dHJOnfihH0J2OPeqzkMofJD17TXMsT10PfVDbCqW7aQ"


def _sheet_from_fixture(filename, title, gid):
    workbook = load_workbook(BytesIO(open(f"tests/fixtures/{filename}", "rb").read()), data_only=False)
    worksheet = workbook[workbook.sheetnames[0]]
    rows = []
    for row in worksheet.iter_rows():
        values = []
        for cell in row:
            value = {"userEnteredValue": {"stringValue": str(cell.value)}} if cell.value is not None else {}
            values.append(value)
        rows.append({"values": values})
    merges = [
        {
            "startRowIndex": area.min_row - 1,
            "endRowIndex": area.max_row,
            "startColumnIndex": area.min_col - 1,
            "endColumnIndex": area.max_col,
        }
        for area in worksheet.merged_cells.ranges
    ]
    workbook.close()
    return {
        "properties": {"sheetId": gid, "title": title},
        "merges": merges,
        "data": [{"startRow": 0, "startColumn": 0, "rowData": rows}],
    }


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


def test_readme_documents_google_only_source_and_writeback():
    readme = open("README.md", encoding="utf-8").read()
    assert "啟用 Google Sheets API" in readme
    assert "最新的工作表分頁" in readme
    assert "client_email" in readme
    assert "檢視者權限" in readme and "編輯者權限" in readme
    assert "不帶 `gid`" in readme
    assert "GOOGLE_SERVICE_ACCOUNT_FILE" in readme
    assert "不提供 `.xlsx` 上傳或副本下載" in readme
    assert "完整歷史 CSV" in readme


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
    adapter = GoogleSheetsAdapter(sheets)
    data, title, gid = adapter.import_sheet(GoogleSheetReference(VALID_ID, 77))
    assert parse_guided_notes(data, "mock.xlsx").questions[0].id == "Q1"
    assert (title, gid) == ("學習單", 77)
    assert sheets.get_args["includeGridData"] is True
    assert adapter.read_cells(VALID_ID, title, ["B2", "C3"]) == {"B2": "現有值", "C3": None}
    adapter.write_cells(VALID_ID, gid, [{"coordinate": "B2", "value": "回填值"}])
    assert len(sheets.batch["body"]["requests"]) == 1
    request = sheets.batch["body"]["requests"][0]["updateCells"]
    assert request["range"]["sheetId"] == 77
    assert request["rows"][0]["values"][0]["userEnteredValue"]["stringValue"] == "回填值"


def test_google_adapter_selects_rightmost_valid_sheet_without_gid():
    response = {"sheets": [
        _sheet_from_fixture("guided-notes-single.xlsx", "舊題目", 11),
        _sheet_from_fixture("guided-notes-group.xlsx", "較新題目", 22),
        {"properties": {"sheetId": 33, "title": "最新空白分頁"}, "merges": [], "data": []},
    ]}
    adapter = GoogleSheetsAdapter(FakeSheetsService(response))

    data, title, gid = adapter.import_sheet(GoogleSheetReference(VALID_ID, None))

    assert (title, gid) == ("較新題目", 22)
    assert [question.id for question in parse_guided_notes(data, "selected.xlsx", title).questions] == [
        "Q1", "Q2", "Q3", "Q4"
    ]


def test_google_adapter_honors_gid_and_does_not_fallback_from_invalid_sheet():
    response = {"sheets": [
        _sheet_from_fixture("guided-notes-single.xlsx", "有效舊表", 11),
        {"properties": {"sheetId": 33, "title": "指定空白表"}, "merges": [], "data": []},
    ]}
    adapter = GoogleSheetsAdapter(FakeSheetsService(response))

    with pytest.raises(GoogleSheetsError, match="題號"):
        adapter.import_sheet(GoogleSheetReference(VALID_ID, 33))


def test_google_adapter_rejects_workbook_without_any_valid_worksheet():
    response = {"sheets": [
        {"properties": {"sheetId": 33, "title": "空白表"}, "merges": [], "data": []},
        {"properties": {"sheetId": 34, "title": "無欄位表"}, "merges": [], "data": []},
    ]}
    adapter = GoogleSheetsAdapter(FakeSheetsService(response))

    with pytest.raises(GoogleSheetsError):
        adapter.import_sheet(GoogleSheetReference(VALID_ID, None))
