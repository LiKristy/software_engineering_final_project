from io import BytesIO

from openpyxl import Workbook, load_workbook

from app.guided_notes import GuidedNotesError, fill_guided_notes, parse_guided_notes


FIXTURES = "tests/fixtures"


def test_imports_real_single_question_template():
    data = open(f"{FIXTURES}/guided-notes-single.xlsx", "rb").read()

    notes = parse_guided_notes(data, "single.xlsx")

    assert notes.worksheet_name == "學習單"
    assert [question.id for question in notes.questions] == [f"Q{i}" for i in range(1, 7)]
    assert [question.slots[0].cell_coordinate for question in notes.questions] == [
        "G5", "G7", "G9", "G11", "G13", "G15"
    ]


def test_imports_real_group_template_and_answer_markers():
    data = open(f"{FIXTURES}/guided-notes-group.xlsx", "rb").read()

    notes = parse_guided_notes(data, "group.xlsx")

    assert [question.id for question in notes.questions] == ["Q1", "Q2", "Q3", "Q4"]
    assert [(slot.marker, slot.cell_coordinate) for slot in notes.questions[0].slots] == [
        ("(1)", "H5"), ("(2)", "H6")
    ]
    assert notes.questions[0].bundle_id == "Q1"


def test_explicit_q_tag_maps_to_its_cell():
    workbook = Workbook()
    ws = workbook.active
    ws.title = "學習單"
    ws["B4"] = "題號"
    ws["G4"] = "作答"
    ws["B5"] = 1
    ws["H5"] = "[Q1]"
    buffer = BytesIO()
    workbook.save(buffer)

    notes = parse_guided_notes(buffer.getvalue(), "tagged.xlsx")

    assert [(slot.question_id, slot.cell_coordinate) for slot in notes.questions[0].slots] == [
        ("Q1", "H5")
    ]


def test_fill_answers_preserves_original_workbook_and_layout():
    original = open(f"{FIXTURES}/guided-notes-group.xlsx", "rb").read()
    result = fill_guided_notes(original, "學習單", {"H5": "CPU", "H6": "作業系統"})
    original_wb = load_workbook(BytesIO(original))
    output_wb = load_workbook(BytesIO(result))

    assert original_wb["學習單"]["H5"].value is None
    assert output_wb["學習單"]["H5"].value == "CPU"
    assert output_wb["學習單"]["H6"].value == "作業系統"
    assert "B5:B6" in {str(rng) for rng in output_wb["學習單"].merged_cells.ranges}


def test_rejects_missing_sheet_and_non_xlsx():
    data = open(f"{FIXTURES}/guided-notes-single.xlsx", "rb").read()

    try:
        parse_guided_notes(data, "notes.csv")
    except GuidedNotesError as exc:
        assert ".xlsx" in str(exc)
    else:
        raise AssertionError("CSV upload should be rejected")
