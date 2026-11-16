from app.services.google_sheets import GoogleSheetsError


class FakeGoogleSheetsAdapter:
    """Return local Guided Notes fixtures through the Google adapter contract."""

    def __init__(self, workbooks, *, error_code=None):
        self.workbooks = list(workbooks) if isinstance(workbooks, (list, tuple)) else [workbooks]
        self.error_code = error_code
        self.import_calls = 0
        self.cells = {}

    def import_sheet(self, reference):
        self.import_calls += 1
        if self.error_code:
            raise GoogleSheetsError("mock Google Sheets failure", self.error_code)
        workbook = self.workbooks[min(self.import_calls - 1, len(self.workbooks) - 1)]
        return workbook, "學習單", 77

    def read_cells(self, spreadsheet_id, worksheet_name, coordinates):
        return {coordinate: self.cells.get(coordinate) for coordinate in coordinates}

    def write_cells(self, spreadsheet_id, sheet_id, cells):
        self.cells.update({item["coordinate"]: item["value"] for item in cells})
