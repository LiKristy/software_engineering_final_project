from dataclasses import asdict, dataclass
from io import BytesIO
import re
from typing import Any

from openpyxl import load_workbook


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
class QuestionPrompt:
    row_order: int
    marker: str
    text: str


@dataclass(frozen=True)
class Question:
    id: str
    ordinal: int
    bundle_id: str
    slots: tuple[AnswerSlot, ...]
    prompts: tuple[QuestionPrompt, ...]


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
                    "prompts": [asdict(prompt) for prompt in q.prompts],
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


def _parse_worksheet(ws) -> ImportedNotes:
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
    prompt_column = header.get("題目")
    question_rows: dict[int, str] = {}
    slots_by_question: dict[str, dict[tuple[str, str], AnswerSlot]] = {}
    prompts_by_question: dict[str, list[QuestionPrompt]] = {}
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
        prompt_text = _text(ws.cell(row, prompt_column).value) if prompt_column else ""
        if prompt_text:
            prompts_by_question.setdefault(question_id, []).append(
                QuestionPrompt(row_order=row, marker=marker, text=prompt_text)
            )

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
            prompts=tuple(sorted(prompts_by_question.get(question_id, []), key=lambda prompt: prompt.row_order)),
        )
        for ordinal, (question_id, slots) in enumerate(ordered, start=1)
    )
    return ImportedNotes(worksheet_name=ws.title, questions=questions)


def parse_guided_notes(data: bytes, filename: str = "notes.xlsx", worksheet_name: str | None = None) -> ImportedNotes:
    if not filename.lower().endswith(".xlsx"):
        raise GuidedNotesError("Google Sheet 匯出的試算表格式不受支援。")
    try:
        workbook = load_workbook(BytesIO(data), data_only=False)
    except Exception as exc:
        raise GuidedNotesError("無法讀取試算表，請確認檔案格式。") from exc

    if worksheet_name is not None:
        candidates = [workbook[worksheet_name]] if worksheet_name in workbook.sheetnames else []
        if not candidates:
            workbook.close()
            raise GuidedNotesError(f"找不到「{worksheet_name}」工作表。")
    else:
        candidates = list(reversed(workbook.worksheets))

    errors = []
    for worksheet in candidates:
        try:
            parsed = _parse_worksheet(worksheet)
            workbook.close()
            return parsed
        except GuidedNotesError as exc:
            errors.append(str(exc))

    workbook.close()
    if not candidates:
        raise GuidedNotesError("試算表中沒有任何工作表。")
    raise GuidedNotesError(errors[0] if errors else "找不到符合格式的工作表。")


