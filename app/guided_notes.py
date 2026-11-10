from dataclasses import asdict, dataclass
from io import BytesIO
import re
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils.cell import coordinate_to_tuple


class GuidedNotesError(ValueError):
    """The workbook is not one of the supported Guided Notes formats."""


@dataclass(frozen=True)
class AnswerSlot:
    id: str
    question_id: str
    marker: str
    worksheet_name: str
    cell_coordinate: str


@dataclass(frozen=True)
class Question:
    id: str
    ordinal: int
    bundle_id: str
    slots: tuple[AnswerSlot, ...]


@dataclass(frozen=True)
class ImportedNotes:
    worksheet_name: str
    questions: tuple[Question, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "worksheet_name": self.worksheet_name,
            "questions": [
                {
                    "id": q.id,
                    "ordinal": q.ordinal,
                    "bundle_id": q.bundle_id,
                    "slots": [asdict(slot) for slot in q.slots],
                }
                for q in self.questions
            ],
        }


_QUESTION_TAG = re.compile(r"\[\s*Q(\d+)\s*\]", re.IGNORECASE)
_QUESTION_NUMBER = re.compile(r"^\s*(?:Q\s*)?(\d+)(?:\.0+)?\s*$", re.IGNORECASE)
_SLOT_MARKER = re.compile(r"^[（(]\s*(\d+)\s*[）)]$")


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _normalize_question(value: Any) -> str | None:
    match = _QUESTION_NUMBER.fullmatch(_text(value))
    return f"Q{int(match.group(1))}" if match else None


def _merged_anchor(ws, row: int, column: int) -> str:
    for merged_range in ws.merged_cells.ranges:
        if (
            merged_range.min_row <= row <= merged_range.max_row
            and merged_range.min_col <= column <= merged_range.max_col
        ):
            return ws.cell(merged_range.min_row, merged_range.min_col).coordinate
    return ws.cell(row, column).coordinate


def parse_guided_notes(data: bytes, filename: str = "notes.xlsx") -> ImportedNotes:
    if not filename.lower().endswith(".xlsx"):
        raise GuidedNotesError("請上傳從範本匯出的 .xlsx 檔案。")
    try:
        workbook = load_workbook(BytesIO(data), data_only=False)
    except Exception as exc:
        raise GuidedNotesError("無法讀取試算表，請確認檔案格式。") from exc

    if "學習單" not in workbook.sheetnames:
        raise GuidedNotesError("找不到「學習單」工作表。")
    ws = workbook["學習單"]

    header = None
    for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 40)):
        labels = {_text(cell.value): cell.column for cell in row if cell.value is not None}
        if "題號" in labels and "作答" in labels:
            header = labels
            break
    if header is None:
        raise GuidedNotesError("找不到「題號」與「作答」欄位標題。")

    number_column = header["題號"]
    answer_column = header["作答"]
    question_rows: dict[int, str] = {}
    slots_by_question: dict[str, dict[tuple[str, str], AnswerSlot]] = {}
    explicit_tag_rows: set[tuple[str, int]] = set()

    for row in range(1, ws.max_row + 1):
        question_id = _normalize_question(ws.cell(row, number_column).value)
        if question_id:
            question_rows[row] = question_id
            slots_by_question.setdefault(question_id, {})

    # A vertically merged question-number cell owns every row in the merged range.
    for merged_range in ws.merged_cells.ranges:
        if merged_range.min_col == number_column and merged_range.max_col == number_column:
            question_id = _normalize_question(ws.cell(merged_range.min_row, number_column).value)
            if question_id:
                for row in range(merged_range.min_row, merged_range.max_row + 1):
                    question_rows[row] = question_id

    # Explicit [Qn] cells are self-addressing blanks and can be anywhere in the sheet.
    for row in ws.iter_rows():
        for cell in row:
            value = _text(cell.value)
            match = _QUESTION_TAG.fullmatch(value)
            if match:
                question_id = f"Q{int(match.group(1))}"
                explicit_tag_rows.add((question_id, cell.row))
                slots_by_question.setdefault(question_id, {})
                slot = AnswerSlot(
                    id=f"{question_id}:{cell.coordinate}",
                    question_id=question_id,
                    marker="",
                    worksheet_name=ws.title,
                    cell_coordinate=cell.coordinate,
                )
                slots_by_question[question_id][("", cell.coordinate)] = slot

    for row, question_id in question_rows.items():
        if (question_id, row) in explicit_tag_rows:
            continue
        marker = _text(ws.cell(row, answer_column).value)
        marker_match = _SLOT_MARKER.fullmatch(marker)
        if marker_match:
            marker = f"({int(marker_match.group(1))})"
            target_column = answer_column + 1
        else:
            marker = ""
            target_column = answer_column

        coordinate = _merged_anchor(ws, row, target_column)
        slot = AnswerSlot(
            id=f"{question_id}:{marker or coordinate}",
            question_id=question_id,
            marker=marker,
            worksheet_name=ws.title,
            cell_coordinate=coordinate,
        )
        slots_by_question[question_id][(marker, coordinate)] = slot

    if not slots_by_question:
        raise GuidedNotesError("找不到可辨識的題號或 [Qn] 填空標籤。")
    if any(not slots for slots in slots_by_question.values()):
        missing = next(qid for qid, slots in slots_by_question.items() if not slots)
        raise GuidedNotesError(f"{missing} 沒有可辨識的作答空格。")

    ordered = sorted(
        slots_by_question.items(),
        key=lambda item: int(item[0][1:]),
    )
    questions = tuple(
        Question(
            id=question_id,
            ordinal=ordinal,
            bundle_id=question_id,
            slots=tuple(sorted(slots.values(), key=lambda slot: (slot.marker, slot.cell_coordinate))),
        )
        for ordinal, (question_id, slots) in enumerate(ordered, start=1)
    )
    workbook.close()
    return ImportedNotes(worksheet_name=ws.title, questions=questions)


def fill_guided_notes(
    data: bytes,
    worksheet_name: str,
    answers: dict[str, str],
) -> bytes:
    workbook = load_workbook(BytesIO(data))
    if worksheet_name not in workbook.sheetnames:
        raise GuidedNotesError("來源工作表不存在，無法回填。")
    ws = workbook[worksheet_name]
    for coordinate, answer in answers.items():
        try:
            coordinate_to_tuple(coordinate)
            cell = ws[coordinate]
        except Exception as exc:
            raise GuidedNotesError("答案空格位置無效。") from exc
        if cell.__class__.__name__ == "MergedCell":
            raise GuidedNotesError(f"答案空格 {coordinate} 不是合併儲存格的起始格。")
        cell.value = answer
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()
