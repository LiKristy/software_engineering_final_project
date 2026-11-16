from io import BytesIO

from openpyxl import Workbook, load_workbook

from app.guided_notes import GuidedNotesError, parse_guided_notes


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


def test_rejects_unsupported_parser_input_format():
    data = open(f"{FIXTURES}/guided-notes-single.xlsx", "rb").read()

    try:
        parse_guided_notes(data, "notes.csv")
    except GuidedNotesError as exc:
        assert "格式不受支援" in str(exc)
    else:
        raise AssertionError("Unsupported parser input should be rejected")
