"""NiceGUI page for creating a new exam question.

Renders the "Create New Question" form, built around an ordered list of
*sub-problems* -- (a), (b), (c)... -- that a teacher assembles freely. Every
sub-problem always has marks and, on top of that, an ordered list of
*content blocks* -- text, image, and table (problem table + auto-mirrored
answer table) -- freely added, removed, and reordered, so a sub-problem's
text and its diagram/table can be interleaved in whatever order the actual
question needs (e.g. instructions, then a diagram, then more instructions,
then a tracing table) instead of always "all the text, then the image, then
the table". Handles client-side validation, PDF preview generation via
latex_export, and persisting the finished question with
database.add_question / replace_question_parts.
"""

import base64
import mimetypes
import string
import uuid
from collections import OrderedDict
from datetime import datetime

from fastapi import Response
from nicegui import ui, app, run

from database import (
    add_question,
    replace_question_parts,
    get_teacher_modules,
    list_teacher_topics,
    add_teacher_topic,
)
from latex_export import build_latex, compile_latex_to_pdf, LatexCompileError


_MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB
_GIVEN_BG = "#f3f4f6"
_ANSWER_BG = "#dbeafe"


class _FixedValue:
    """A stand-in for a NiceGUI input when a field's value is locked.

    Used for the Module field on the Create New Question page (see
    render_question_editor()'s `fixed_module` argument): the rest of the
    function reads a field's current value via `.value` and hooks change
    notifications via `.on_value_change(...)`, regardless of whether that
    field is an editable ui.select or (here) a plain read-only display --
    this gives a fixed value the same two-member interface so none of
    that downstream code needs to know the difference.
    """

    def __init__(self, value):
        self.value = value

    def on_value_change(self, handler):
        """No-op: a fixed value never changes, so there's nothing to notify."""
        pass

# In-memory hand-off from a compiled question preview to the
# /questions/preview.pdf route below, so the "Preview PDF" button can open
# the PDF in a new browser tab (viewed inline via the browser's own PDF
# viewer) instead of forcing a download -- same approach as the exam
# export preview (see pages/export_preview.py). Capped and FIFO-evicted so
# it can't grow unbounded across many previews; entries are short-lived (a
# teacher previews, looks, moves on).
_MAX_CACHED_PREVIEWS = 20
_preview_pdfs: "OrderedDict[str, bytes]" = OrderedDict()


def _cache_preview_pdf(pdf_bytes: bytes) -> str:
    """Stash compiled PDF bytes under a fresh token and return that token."""
    token = uuid.uuid4().hex
    _preview_pdfs[token] = pdf_bytes
    while len(_preview_pdfs) > _MAX_CACHED_PREVIEWS:
        _preview_pdfs.popitem(last=False)
    return token


@app.get("/questions/preview.pdf")
def _serve_preview_pdf(token: str = ""):
    """Serve a previously compiled question preview PDF by its one-time token.

    Registered once at import time (not inside create_question_page) --
    this is a plain FastAPI route, not a NiceGUI page. The
    Content-Disposition: inline header tells the browser to display the
    PDF itself rather than downloading it.
    """
    data = _preview_pdfs.get(token)
    if data is None:
        return Response(status_code=404, content=b"Preview expired or not found.")
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline; filename=question_preview.pdf"},
    )


def _label_for_index(index: int) -> str:
    """Convert a zero-based position into a UK-style lower-case label.

    Args:
        index: Zero-based position of the sub-question (0, 1, 2, ...).

    Returns:
        The corresponding label: 0 -> "a", 1 -> "b", ..., 25 -> "z",
        26 -> "aa", and so on.
    """
    letters = string.ascii_lowercase
    label = ""
    index += 1
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        label = letters[remainder] + label
    return label


def _labels_for(parts_data: list) -> list:
    """Compute the display label for each sub-problem in order.

    Every sub-problem is lettered now (there's no non-gradable stimulus
    component any more -- background material just lives in a
    sub-problem's own description), so this is just the letters in order.

    Args:
        parts_data: The page's in-memory list of sub-problem dicts.

    Returns:
        A list with one letter ("a", "b", "c", ...) per entry in parts_data.
    """
    return [_label_for_index(i) for i in range(len(parts_data))]


_ROMAN_VALUES = [
    (1000, "m"), (900, "cm"), (500, "d"), (400, "cd"),
    (100, "c"), (90, "xc"), (50, "l"), (40, "xl"),
    (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i"),
]


def _roman_for_index(index: int) -> str:
    """Convert a zero-based position into a lower-case Roman numeral label.

    Used for the third numbering level -- (i), (ii), (iii)... -- nested
    inside a lettered sub-problem's own sub-parts (see the "subparts" key
    documented on create_question_page()'s parts_data docstring).

    Args:
        index: Zero-based position of the sub-part (0, 1, 2, ...).

    Returns:
        The corresponding Roman numeral label: 0 -> "i", 1 -> "ii",
        2 -> "iii", 8 -> "ix", etc.
    """
    n = index + 1
    result = []
    for value, symbol in _ROMAN_VALUES:
        while n >= value:
            result.append(symbol)
            n -= value
    return "".join(result)


def _part_marks(part: dict) -> int:
    """The effective marks for one sub-problem, accounting for sub-parts.

    A sub-problem broken down further into (i)/(ii)/(iii)... sub-parts
    doesn't carry its own marks value any more -- exactly like the parent
    question's marks become the sum of its sub-problems' once any exist,
    a sub-problem's own marks become the sum of its sub-parts' once it
    has any. Otherwise it's just whatever's in "marks" (its own, directly
    edited value).

    Args:
        part: One sub-problem's raw in-memory state dict.

    Returns:
        The marks this sub-problem is currently worth.
    """
    subparts = part.get("subparts") or []
    if subparts:
        return sum(int(sp.get("marks") or 0) for sp in subparts)
    return int(part.get("marks") or 0)


def _table_spec(block: dict) -> dict:
    """Build the {"given_columns", "answer_columns", "rows"} shape for a *problem* table block.

    This is what the student sees -- whatever a cell holds (including
    blank) is exactly what's printed on the official/example paper. Kept
    directly in this shape on the block dict already -- "given_columns" /
    "answer_columns" (each a list of column-name strings) and "rows" (a
    list of rows, each a list of cell strings, given columns first then
    answer columns) -- built up by the grid editor's add/remove
    column/row handlers, which keep the invariant that every row's
    length always equals len(given_columns) + len(answer_columns).

    Args:
        block: The raw in-memory state dict for one "table" content block.

    Returns:
        A dict with "given_columns", "answer_columns", and "rows" keys,
        matching what database.py's replace_question_parts / latex_export.py's
        table renderer expect as a "table_spec".
    """
    return {
        "given_columns": list(block.get("given_columns") or []),
        "answer_columns": list(block.get("answer_columns") or []),
        "rows": [list(r) for r in (block.get("rows") or [])],
    }


def _answer_table_spec(block: dict) -> dict:
    """Build the {"given_columns", "answer_columns", "rows"} shape for a *answer* table block.

    Structurally this always mirrors the problem table -- same headers,
    same row count, kept in sync by the table editor's add/remove
    column/row handlers -- so a teacher never has to rebuild the table
    twice. Cell *values* are fully independent of the problem table
    though (every cell here, given-column or answer-column, is its own
    freely-editable input in "answer_rows" -- see the table editor's
    cell handlers): the problem table's given-column values are only
    ever copied in as an initial convenience (when a row/column is first
    added, or via the explicit "Copy from problem table" button), never
    forced or re-synced afterwards, so editing one table never silently
    overwrites something already typed into the other.

    Args:
        block: The raw in-memory state dict for one "table" content block.

    Returns:
        A dict with "given_columns", "answer_columns", and "rows" keys,
        matching what database.py's replace_question_parts / latex_export.py's
        table renderer expect as an "answer_table_spec".
    """
    given_cols = list(block.get("given_columns") or [])
    answer_cols = list(block.get("answer_columns") or [])
    n = len(given_cols) + len(answer_cols)
    problem_rows = block.get("rows") or []
    answer_rows = block.get("answer_rows") or []

    rows = []
    for r in range(len(problem_rows)):
        arow = answer_rows[r] if r < len(answer_rows) else []
        rows.append([arow[c] if c < len(arow) else "" for c in range(n)])

    return {"given_columns": given_cols, "answer_columns": answer_cols, "rows": rows}


def _block_payload(block: dict) -> dict:
    """Build the JSON-able dict shape for one content block, as stored in "Content blocks".

    Args:
        block: The raw in-memory state dict for one content block (any
            type).

    Returns:
        A plain dict with a "type" key ("text"/"image"/"table") plus that
        type's own fields -- "text" for a text block; "image_data"/
        "image_filename" for an image block; "table_spec"/
        "answer_table_spec" for a table block (see _table_spec() /
        _answer_table_spec()), plus that table block's optional
        "answer_text_before"/"answer_text_after" -- free text rendered
        immediately before/after the answer table, but only in the
        "solutions" export (see latex_export.py's _render_question) --
        e.g. "Solution: sorted edges: ..." before the table and
        "Final MST total weight: 19" after it.
    """
    btype = block.get("type")
    if btype == "text":
        return {"type": "text", "text": (block.get("text") or "").strip()}
    if btype == "image":
        return {
            "type": "image",
            "image_data": block.get("image_data"),
            "image_filename": block.get("image_filename"),
        }
    if btype == "table":
        return {
            "type": "table",
            "table_spec": _table_spec(block),
            "answer_table_spec": _answer_table_spec(block),
            "answer_text_before": (block.get("answer_text_before") or "").strip(),
            "answer_text_after": (block.get("answer_text_after") or "").strip(),
        }
    return {"type": btype}


def _build_part_dict(label, part: dict, *, for_preview: bool) -> dict:
    """Build the dict shape build_latex() / replace_question_parts() expect.

    Converts one sub-problem's raw create-page state (a list of content
    blocks, see create_question_page()'s parts_data docstring) into the
    normalized dict shape used both for the PDF preview and for the
    actual save: "Content blocks" (the ordered list itself, what
    build_latex() actually renders from) plus, for backward
    compatibility with code that only knows about the old fixed layout
    (edit_question.py's "can this be edited here" check, in particular),
    best-effort single-value summaries derived from those blocks --
    "Description" (every text block's text, joined), "Image data" /
    "Image filename" (the first image block with an uploaded file), and
    "Table spec" / "Answer table spec" (the first table block).

    Recursive: if `part` carries any "subparts" -- the third numbering
    level, (i)/(ii)/(iii)... nested inside this (a)/(b)/(c)... sub-
    problem (see create_question_page()'s parts_data docstring) -- each
    is built into this exact same dict shape (via a Roman-numeral label
    from _roman_for_index()) and collected under "Sub parts". When that's
    non-empty, this sub-problem's own "Marks" becomes the sum of its
    sub-parts' (mirroring how the parent question's marks become the sum
    of its sub-problems'), and "Answer" is left unused (None) -- each
    sub-part carries its own instead, just like this function's caller
    treats a question's own "Answer" as unused once it has sub-problems.

    Args:
        label: This sub-problem's precomputed letter (from _labels_for()),
            or, for a recursive sub-part call, its Roman numeral.
        part: The raw in-memory state dict for this single sub-problem
            (or sub-part).
        for_preview: If True, fills in placeholder text for still-empty
            fields so an incomplete question can still be previewed. If
            False (used when actually saving), leaves them as None
            instead.

    Returns:
        A dict with the keys expected by build_latex() /
        replace_question_parts() ("Label", "Content blocks",
        "Description", "Marks", "Answer space", "Part type", "Table
        spec", "Answer table spec", "Answer", "Image data", "Image
        filename", "Sub parts").
    """
    blocks = part.get("blocks") or []
    subparts = part.get("subparts") or []
    has_subparts = bool(subparts)

    text_bits = [(b.get("text") or "").strip() for b in blocks if b.get("type") == "text"]
    description = "\n\n".join(bit for bit in text_bits if bit)

    image_blocks = [b for b in blocks if b.get("type") == "image" and b.get("image_data")]
    first_image = image_blocks[0] if image_blocks else None

    table_blocks = [b for b in blocks if b.get("type") == "table"]
    first_table = table_blocks[0] if table_blocks else None
    has_table = bool(table_blocks)

    # An image block with no file uploaded yet (still mid-edit) is a
    # placeholder, not real content -- drop it rather than saving/
    # previewing a block that would render as a broken-image message.
    content_blocks = [
        _block_payload(b) for b in blocks
        if not (b.get("type") == "image" and not b.get("image_data"))
    ]

    if has_subparts:
        sub_dicts = [
            _build_part_dict(_roman_for_index(si), sp, for_preview=for_preview)
            for si, sp in enumerate(subparts)
        ]
        marks = sum(sd["Marks"] for sd in sub_dicts)
    else:
        sub_dicts = None
        marks = int(part.get("marks") or 0)

    result = {
        "Label": label,
        "Content blocks": content_blocks,
        "Description": description or ("(no description yet)" if for_preview else None),
        "Marks": marks,
        "Answer space": part.get("answer_space") or "half",
        "Part type": "table" if has_table else "text",
        "Table spec": _table_spec(first_table) if first_table else None,
        "Answer table spec": _answer_table_spec(first_table) if first_table else None,
        "Answer": None,
        "Image data": first_image.get("image_data") if first_image else None,
        "Image filename": first_image.get("image_filename") if first_image else None,
        "Sub parts": sub_dicts,
    }

    if not has_subparts and not has_table:
        answer = (part.get("answer") or "").strip()
        result["Answer"] = answer or ("(no standard answer yet)" if for_preview else None)

    return result


def _build_main_content(main_blocks: list) -> dict:
    """Build the question-level "Main content blocks" / "Main question" payload.

    Converts the "2. Problem" section's raw in-memory block list (the
    same shape a sub-problem's own "blocks" uses -- see
    render_question_editor()'s docstring) into what add_question()/
    update_question() expect: the ordered block list itself, plus a
    best-effort plain-text summary (every text block's text, joined) kept
    in sync on the flat legacy "Main question" column for older code
    paths that only know about it.

    Args:
        main_blocks: The page's in-memory list of content blocks for the
            overall problem statement (possibly empty -- unlike a
            sub-problem, this is optional).

    Returns:
        A dict with "Content blocks" (list, empty if `main_blocks` is)
        and "Text" (the joined plain-text summary, "" if there's no text
        block or every one is blank).
    """
    # Same "drop a still-empty image placeholder" rule _build_part_dict()
    # applies to a sub-problem's own blocks.
    content_blocks = [
        _block_payload(b) for b in main_blocks
        if not (b.get("type") == "image" and not b.get("image_data"))
    ]
    text_bits = [(b.get("text") or "").strip() for b in main_blocks if b.get("type") == "text"]
    text_summary = "\n\n".join(bit for bit in text_bits if bit)
    return {"Content blocks": content_blocks, "Text": text_summary}


def _render_block_editor(blocks: list, *, on_structural_change, on_content_change) -> None:
    """Render the add/edit/reorder UI for one ordered list of content blocks.

    Shared by both numbering levels that carry their own content -- a
    top-level sub-problem's own "blocks" list, and a nested sub-part's
    own "blocks" list (see create_question_page()'s parts_data
    docstring) -- since both are exactly the same shape: an ordered list
    of text/image/table block dicts. `blocks` is the *actual* live list
    object (e.g. `parts_data[idx]["blocks"]` or
    `parts_data[idx]["subparts"][si]["blocks"]`), mutated in place by
    every handler here, so the caller doesn't need to pass an index back
    in -- just re-render (or not) afterwards.

    Args:
        blocks: The live list of block dicts to render/edit.
        on_structural_change: Called after any change that adds/removes/
            reorders a block, or resizes a table (row/column add/remove/
            copy) -- expected to fully redraw the page and recompute
            totals (typing would otherwise lose focus if this re-rendered
            on every keystroke, which is why the two callbacks are kept
            separate).
        on_content_change: Called after a value-only edit (text, a table
            cell, a column rename, an image upload) that doesn't need a
            full re-render -- expected to just re-run validation.
    """

    def make_add_handler(block_type):
        """Return a handler that appends a new `block_type` block."""
        def handler():
            new_block = {"type": block_type}
            if block_type == "text":
                new_block["text"] = ""
            elif block_type == "image":
                new_block["image_data"] = None
                new_block["image_filename"] = None
            elif block_type == "table":
                new_block["given_columns"] = ["Given 1"]
                new_block["answer_columns"] = ["Answer 1"]
                new_block["rows"] = [["", ""]]
                new_block["answer_rows"] = [["", ""]]
                new_block["answer_text_before"] = ""
                new_block["answer_text_after"] = ""
            blocks.append(new_block)
            on_structural_change()

        return handler

    def make_remove_handler(bi):
        """Return a handler that deletes block `bi`."""
        def handler():
            blocks.pop(bi)
            on_structural_change()

        return handler

    def make_move_handler(bi, delta):
        """Return a handler that swaps block `bi` with its neighbour `delta` positions away."""
        def handler():
            j = bi + delta
            if 0 <= j < len(blocks):
                blocks[bi], blocks[j] = blocks[j], blocks[bi]
                on_structural_change()

        return handler

    def make_text_handler(bi):
        """Return a handler that updates the text of block `bi`."""
        def handler(e):
            blocks[bi]["text"] = e.value
            on_content_change()

        return handler

    def make_answer_text_handler(bi, key):
        """Return a handler that updates block `bi`'s "answer_text_before" or "answer_text_after"."""
        def handler(e):
            blocks[bi][key] = e.value
            on_content_change()

        return handler

    def make_image_upload_handler(bi):
        """Return a handler that stores an uploaded image on block `bi`."""
        async def handler(e):
            data = await e.file.read()
            if not data:
                ui.notify("That file appears to be empty.", color="warning")
                return
            blocks[bi]["image_data"] = base64.b64encode(data).decode("ascii")
            blocks[bi]["image_filename"] = e.file.name
            on_structural_change()

        return handler

    def make_rename_col_handler(bi, group, col_i, header_mirror_refs):
        """Return a handler that renames given/answer column `col_i` of block `bi`."""
        key = "given_columns" if group == "given" else "answer_columns"

        def handler(e):
            blocks[bi][key][col_i] = e.value
            mirror = header_mirror_refs.get((group, col_i))
            if mirror is not None:
                mirror.text = (e.value or "").strip()
            on_content_change()

        return handler

    def make_cell_handler(bi, row_i, col_i):
        """Return a handler that updates one cell of block `bi`'s *problem* table."""
        def handler(e):
            blocks[bi]["rows"][row_i][col_i] = e.value
            on_content_change()

        return handler

    def make_answer_cell_handler(bi, row_i, col_i):
        """Return a handler that updates one cell of block `bi`'s *answer* table."""
        def handler(e):
            rows = blocks[bi]["answer_rows"]
            while len(rows) <= row_i:
                rows.append([])
            row = rows[row_i]
            while len(row) <= col_i:
                row.append("")
            row[col_i] = e.value
            on_content_change()

        return handler

    def make_copy_given_handler(bi):
        """Return a handler that copies block `bi`'s problem-table given-column values into its answer table."""
        def handler():
            block = blocks[bi]
            n_given = len(block.get("given_columns") or [])
            problem_rows = block.get("rows") or []
            answer_rows = block.setdefault("answer_rows", [])
            while len(answer_rows) < len(problem_rows):
                answer_rows.append([])
            for r, prow in enumerate(problem_rows):
                arow = answer_rows[r]
                for c in range(n_given):
                    while len(arow) <= c:
                        arow.append("")
                    arow[c] = prow[c] if c < len(prow) else ""
            on_structural_change()

        return handler

    def make_add_col_handler(bi, group):
        """Return a handler that appends a new given/answer column to block `bi`'s table."""
        def handler():
            block = blocks[bi]
            given = block.setdefault("given_columns", [])
            answer = block.setdefault("answer_columns", [])
            problem_rows = block.setdefault("rows", [])
            answer_rows = block.setdefault("answer_rows", [])
            if group == "given":
                boundary = len(given)
                given.append("")
                for row in problem_rows:
                    row.insert(boundary, "")
                for row in answer_rows:
                    row.insert(boundary, "")
            else:
                answer.append("")
                for row in problem_rows:
                    row.append("")
                for row in answer_rows:
                    row.append("")
            on_structural_change()

        return handler

    def make_remove_col_handler(bi, group, col_i):
        """Return a handler that deletes given/answer column `col_i` from block `bi`'s table."""
        def handler():
            block = blocks[bi]
            given = block.get("given_columns", [])
            answer = block.get("answer_columns", [])
            real_i = col_i if group == "given" else len(given) + col_i
            if group == "given":
                if col_i < len(given):
                    given.pop(col_i)
            elif col_i < len(answer):
                answer.pop(col_i)
            for row in block.get("rows", []):
                if real_i < len(row):
                    row.pop(real_i)
            for row in block.get("answer_rows", []):
                if real_i < len(row):
                    row.pop(real_i)
            on_structural_change()

        return handler

    def make_add_row_handler(bi):
        """Return a handler that appends a new, blank row to block `bi`'s table (both problem and answer)."""
        def handler():
            block = blocks[bi]
            total = len(block.get("given_columns", [])) + len(block.get("answer_columns", []))
            block.setdefault("rows", []).append([""] * total)
            block.setdefault("answer_rows", []).append([""] * total)
            on_structural_change()

        return handler

    def make_remove_row_handler(bi, row_i):
        """Return a handler that deletes row `row_i` from block `bi`'s table (both problem and answer)."""
        def handler():
            block = blocks[bi]
            problem_rows = block.get("rows", [])
            answer_rows = block.get("answer_rows", [])
            if row_i < len(problem_rows):
                problem_rows.pop(row_i)
            if row_i < len(answer_rows):
                answer_rows.pop(row_i)
            on_structural_change()

        return handler

    for bi, block in enumerate(blocks):
        btype = block.get("type")
        with ui.card().classes("w-full p-3 bg-grey-50"):
            with ui.row().classes("w-full items-center justify-between no-wrap"):
                ui.label(btype.upper()).classes("text-xs font-bold text-grey-500")
                with ui.row().classes("gap-0 items-center"):
                    up_btn = ui.button(
                        icon="arrow_upward",
                        on_click=make_move_handler(bi, -1),
                    ).props("flat dense round size=sm").tooltip("Move up")
                    if bi == 0:
                        up_btn.disable()
                    down_btn = ui.button(
                        icon="arrow_downward",
                        on_click=make_move_handler(bi, 1),
                    ).props("flat dense round size=sm").tooltip("Move down")
                    if bi == len(blocks) - 1:
                        down_btn.disable()
                    ui.button(
                        icon="delete",
                        color="red",
                        on_click=make_remove_handler(bi),
                    ).props("flat dense round size=sm")

            if btype == "text":
                ui.textarea(
                    placeholder="Text for this sub-problem",
                    value=block.get("text", ""),
                    on_change=make_text_handler(bi),
                ).classes("w-full mt-1").props("rows=2")

            elif btype == "image":
                if block.get("image_data"):
                    mime = mimetypes.guess_type(
                        block.get("image_filename") or ""
                    )[0] or "image/png"
                    with ui.row().classes("items-center gap-2 mt-1"):
                        ui.image(
                            f"data:{mime};base64,{block['image_data']}"
                        ).classes("w-40 border rounded")
                        ui.label(block.get("image_filename") or "").classes(
                            "text-xs text-grey-600"
                        )
                else:
                    ui.upload(
                        label="Upload image",
                        auto_upload=True,
                        max_file_size=_MAX_IMAGE_BYTES,
                        on_upload=make_image_upload_handler(bi),
                        on_rejected=lambda: ui.notify(
                            "That file is too large (max 5 MB) or was rejected.",
                            color="negative",
                        ),
                    ).props('accept=".png,.jpg,.jpeg"').classes("w-full mt-1")

            elif btype == "table":
                given_cols = block.get("given_columns") or []
                answer_cols = block.get("answer_columns") or []
                problem_rows = block.get("rows") or []
                answer_rows = block.get("answer_rows") or []
                total_cols = len(given_cols) + len(answer_cols)
                header_mirror_refs = {}  # (group, col_i) -> answer-table's header label

                ui.label(
                    "Problem table -- what the student sees. Leave a cell "
                    "blank if that's where they should write their answer."
                ).classes("text-xs font-semibold text-grey-600 mt-1")

                if total_cols:
                    grid_style = (
                        f"display:grid; grid-template-columns: "
                        f"repeat({total_cols}, minmax(90px, 1fr)) 40px; "
                        "gap:6px; align-items:center;"
                    )
                    with ui.element("div").style(grid_style).classes("w-full mt-1"):
                        for gi, name in enumerate(given_cols):
                            with ui.row().classes("items-center gap-0 no-wrap"):
                                ui.input(
                                    value=name,
                                    placeholder=f"Given {gi + 1}",
                                    on_change=make_rename_col_handler(
                                        bi, "given", gi, header_mirror_refs
                                    ),
                                ).props("dense outlined").style(
                                    f"background:{_GIVEN_BG}"
                                ).classes("w-full")
                                ui.button(
                                    icon="close",
                                    color="red",
                                    on_click=make_remove_col_handler(bi, "given", gi),
                                ).props("flat dense round size=sm")
                        for ai, name in enumerate(answer_cols):
                            with ui.row().classes("items-center gap-0 no-wrap"):
                                ui.input(
                                    value=name,
                                    placeholder=f"Answer {ai + 1}",
                                    on_change=make_rename_col_handler(
                                        bi, "answer", ai, header_mirror_refs
                                    ),
                                ).props("dense outlined").style(
                                    f"background:{_ANSWER_BG}"
                                ).classes("w-full")
                                ui.button(
                                    icon="close",
                                    color="red",
                                    on_click=make_remove_col_handler(bi, "answer", ai),
                                ).props("flat dense round size=sm")
                        ui.label("")  # spacer above the row-delete button column

                        for ri, row in enumerate(problem_rows):
                            for ci in range(total_cols):
                                is_given = ci < len(given_cols)
                                ui.input(
                                    value=row[ci] if ci < len(row) else "",
                                    on_change=make_cell_handler(bi, ri, ci),
                                ).props("dense outlined").style(
                                    f"background:{_GIVEN_BG if is_given else _ANSWER_BG}"
                                ).classes("w-full")
                            ui.button(
                                icon="delete",
                                color="red",
                                on_click=make_remove_row_handler(bi, ri),
                            ).props("flat dense round size=sm")
                else:
                    ui.label(
                        "No columns yet -- add a given or answer column below to start."
                    ).classes("text-xs text-grey-500 italic mt-1")

                with ui.row().classes("gap-2 mt-2"):
                    ui.button(
                        "+ Given column",
                        icon="add",
                        on_click=make_add_col_handler(bi, "given"),
                    ).props("outline dense size=sm")
                    ui.button(
                        "+ Answer column",
                        icon="add",
                        on_click=make_add_col_handler(bi, "answer"),
                    ).props("outline dense size=sm")
                    ui.button(
                        "+ Row",
                        icon="add",
                        on_click=make_add_row_handler(bi),
                    ).props("outline dense size=sm")

                with ui.row().classes("w-full items-center justify-between mt-3"):
                    ui.label(
                        "Answer table -- the model answer. Headers and row "
                        "count always match the problem table above; every "
                        "cell here is independently editable."
                    ).classes("text-xs font-semibold text-grey-600")
                    ui.button(
                        "Copy given values from problem table",
                        icon="content_copy",
                        on_click=make_copy_given_handler(bi),
                    ).props("outline dense size=sm")

                ui.textarea(
                    label="Solution text before the answer table (optional)",
                    placeholder='e.g. "Solution: sorted edges: (A,C:2), (C,D:3), ..."',
                    value=block.get("answer_text_before", ""),
                    on_change=make_answer_text_handler(bi, "answer_text_before"),
                ).classes("w-full mt-2").props("rows=2 dense outlined")

                if total_cols:
                    grid_style = (
                        f"display:grid; grid-template-columns: "
                        f"repeat({total_cols}, minmax(90px, 1fr)); "
                        "gap:6px; align-items:center;"
                    )
                    with ui.element("div").style(grid_style).classes("w-full mt-1"):
                        for gi, name in enumerate(given_cols):
                            mirror_label = ui.label(
                                (name or "").strip()
                            ).classes("text-sm font-semibold rounded").style(
                                f"background:{_GIVEN_BG}; padding:8px 10px; "
                                "border:1px solid #cbd5e1;"
                            )
                            header_mirror_refs[("given", gi)] = mirror_label
                        for ai, name in enumerate(answer_cols):
                            mirror_label = ui.label(
                                (name or "").strip()
                            ).classes("text-sm font-semibold rounded").style(
                                f"background:{_ANSWER_BG}; padding:8px 10px; "
                                "border:1px solid #93c5fd;"
                            )
                            header_mirror_refs[("answer", ai)] = mirror_label

                        for ri in range(len(problem_rows)):
                            arow = answer_rows[ri] if ri < len(answer_rows) else []
                            for ci in range(total_cols):
                                is_given = ci < len(given_cols)
                                ui.input(
                                    value=arow[ci] if ci < len(arow) else "",
                                    on_change=make_answer_cell_handler(bi, ri, ci),
                                ).props("dense outlined").style(
                                    f"background:{_GIVEN_BG if is_given else _ANSWER_BG}"
                                ).classes("w-full")

                ui.textarea(
                    label="Solution text after the answer table (optional)",
                    placeholder='e.g. "Final MST total weight: 2+3+4+4+6 = 19"',
                    value=block.get("answer_text_after", ""),
                    on_change=make_answer_text_handler(bi, "answer_text_after"),
                ).classes("w-full mt-2").props("rows=2 dense outlined")

                ui.label(
                    "Both solution-text fields above appear only in the "
                    "\"Solutions\" export, immediately before/after the "
                    "answer table -- students never see them."
                ).classes("text-xs text-grey-500 italic mt-1")

    with ui.row().classes("gap-2 mt-1"):
        ui.button(
            "+ Text",
            icon="notes",
            on_click=make_add_handler("text"),
        ).props("outline dense size=sm")
        ui.button(
            "+ Image",
            icon="add_photo_alternate",
            on_click=make_add_handler("image"),
        ).props("outline dense size=sm")
        ui.button(
            "+ Table",
            icon="grid_on",
            on_click=make_add_handler("table"),
        ).props("outline dense size=sm")


def render_question_editor(
    *,
    page_heading: str,
    save_button_label: str,
    assigned_modules: list,
    existing_topics: list,
    initial: dict,
    on_save,
    meta_lines: list = None,
    extra_actions: list = None,
    fixed_module: str = None,
) -> None:
    """Render the shared create/edit question form.

    Built around a single ordered list of *sub-problems* -- (a), (b),
    (c)... -- added and reordered freely. Every sub-problem always has a
    description and marks; on top of that it may optionally carry an
    attached image and/or an attached table (in any combination -- a
    sub-problem can show a diagram and ask the student to fill in a
    table, for instance), and may optionally be broken down further into
    (i)/(ii)/(iii)... sub-parts. Each sub-problem collapses to a
    one-line summary until opened, and the Save button stays disabled
    (with a tooltip explaining why) until the question is actually valid,
    instead of only failing after you click it.

    Shared by create_question_page() (a blank form that creates a new
    question) and edit_question.py's edit_question_page() (the same form
    pre-filled from an existing question's data, which updates it
    instead) -- the two only differ in their starting `initial` values,
    what `on_save` actually persists, and a couple of small display
    extras (`meta_lines`, `extra_actions`) edit_question.py uses to show
    read-only Status/Version and a "View Question" button. This is what
    lets edit_question.py fully support the same content -- attached
    images/tables, multiple/reordered content blocks, and nested
    (i)/(ii)/(iii)... sub-parts -- that create_question.py can produce,
    instead of blocking editing whenever a question contains one.

    Args:
        page_heading: The large heading shown at the top of the page,
            e.g. "Create New Question" or "Edit Question #3".
        save_button_label: Text for the primary save button, e.g. "Save"
            or "Save Changes".
        assigned_modules: This teacher's assigned module codes, offered
            as Module choices.
        existing_topics: This teacher's previously-used Topic labels,
            offered as Topic choices (plus free text entry).
        initial: Starting values for every field -- "title", "module",
            "topic", "marks", "answer" (all strings/numbers), "main_blocks"
            (the in-memory content-block list for the overall problem
            statement -- same shape as one sub-problem's own "blocks",
            below; pass an empty list if there's no problem statement),
            and "parts_data" (the in-memory sub-problem list; see
            create_question_page()'s docstring for its shape -- each
            entry has "marks", "answer", "answer_space", "blocks", and
            "subparts"). Pass an empty "parts_data" list for a blank
            question.
        on_save: Called with a single payload dict once the form
            validates and Save is clicked -- {"title", "module", "topic",
            "main_content_blocks", "main_text", "marks", "answer",
            "parts_payload"} ("main_content_blocks"/"main_text" are the
            two halves of _build_main_content()'s return value -- the
            block list and its plain-text summary, ready for "Main
            content blocks"/"Main question"; "parts_payload" is the list
            of sub-problem dicts built by _build_part_dict(), ready for
            replace_question_parts()). Responsible for everything after
            that: the actual add_question()/update_question() +
            replace_question_parts() calls, add_teacher_topic(),
            notifying the user, and navigating away.
        meta_lines: Optional list of read-only text lines shown near the
            bottom of the form (e.g. ["Status: Draft", "Version: 2"]).
        extra_actions: Optional list of (label, on_click) tuples for
            extra buttons shown alongside Save/Cancel (e.g. a "View
            Question" button on the edit page).
        fixed_module: If given, the Module field is rendered as a
            read-only chip showing this code instead of an editable
            select -- used by create_question_page() so a question is
            always created under whatever module the teacher picked on
            the Module Selection page, with no way to change it here.
            None (the default) keeps Module an editable select, as
            edit_question.py still uses.
    """

    parts_data = list(initial.get("parts_data") or [])

    # Assigned by the button-creation code further down; declared here (and
    # guarded with "is not None" checks) so validation callbacks registered
    # on earlier fields don't blow up if they fire before the buttons at
    # the bottom of the page exist yet -- same pattern export_exam.py uses
    # for its Generate button/tooltip.
    save_btn = None
    save_tooltip = None
    preview_btn = None

    with ui.column().classes("w-full max-w-4xl mx-auto p-8 gap-4"):

        ui.label(page_heading).classes("text-3xl font-bold mb-2")

        # ------------------------------------------------------------
        # 1. Basic info
        # ------------------------------------------------------------
        with ui.card().classes("w-full p-6"):
            ui.label("1. Basic Info").classes("text-lg font-bold mb-3")

            ui.label("Question Title").classes("font-semibold")
            title_input = ui.input(
                value=initial.get("title") or "",
                placeholder='e.g. "Definitions" / "Kruskal\'s Algorithm"'
            ).classes("w-full").mark("title_input")
            title_error_label = ui.label("").classes("text-xs text-red-600 mb-2")

            ui.label("Module").classes("font-semibold mt-1")
            if fixed_module:
                # Locked to whatever module the teacher picked on the
                # Module Selection page -- no select control here at all,
                # so a question can't accidentally be created under the
                # wrong module. "Change module" sends them back to pick a
                # different one (which then applies to their *next* new
                # question, not this in-progress form).
                with ui.row().classes("items-center gap-2 mb-1"):
                    ui.chip(
                        fixed_module, icon="school", color="primary", text_color="white"
                    ).props("dense").mark("module_select")
                    ui.link("Change module", "/modules").classes("text-xs")
                module_input = _FixedValue(fixed_module)
            else:
                # Keep the form's starting module selectable even if it's
                # not (or no longer) part of this teacher's assigned list
                # -- e.g. editing a question whose module an admin has
                # since unassigned -- so opening the form never silently
                # drops it.
                existing_module = (initial.get("module") or "").strip()
                module_options = list(assigned_modules)
                if existing_module and existing_module not in module_options:
                    module_options.append(existing_module)

                if module_options:
                    module_input = ui.select(
                        module_options, value=existing_module or None, label=""
                    ).classes("w-full mb-1").mark("module_select")
                else:
                    module_input = (
                        ui.select([], label="").classes("w-full mb-1").props("disable").mark("module_select")
                    )
                    ui.label(
                        "You haven't been assigned any modules yet. Contact your admin "
                        "to get one assigned before selecting."
                    ).classes("text-sm text-negative mb-1")

            ui.label("Topic / Knowledge Point").classes("font-semibold mt-1")
            # Select-or-add: pick one of this teacher's own previously-used
            # labels, or type a new one -- `new_value_mode="add-unique"`
            # (with `with_input` enabling the search/type box) lets typing
            # something not already in the list add and select it in one
            # step, rather than requiring a separate "create label" flow.
            # Same "keep the starting value selectable" treatment as
            # Module above, so editing a question never silently blanks
            # its topic out.
            existing_topic = (initial.get("topic") or "").strip()
            topic_options = list(existing_topics)
            if existing_topic and existing_topic not in topic_options:
                topic_options.append(existing_topic)
            topic_input = ui.select(
                topic_options,
                value=existing_topic or None,
                label="",
                with_input=True,
                new_value_mode="add-unique",
            ).props(
                'placeholder="e.g. Stacks, Binary Search Trees (optional)"'
            ).classes("w-full mb-1").mark("topic_input")
            ui.label(
                "Helps tell questions apart at a glance in the question list -- "
                "optional but recommended, since the title alone often doesn't say "
                "what the question is actually about."
            ).classes("text-xs text-grey-500 mb-1")

        # ------------------------------------------------------------
        # 2. Problem -- overall problem statement (optional, same block
        # editor a sub-problem's own content uses) plus the sub-problems
        # themselves, merged into one section since the latter builds
        # directly on the former.
        # ------------------------------------------------------------
        with ui.card().classes("w-full p-6"):
            ui.label("2. Problem").classes("text-lg font-bold mb-1")
            ui.label(
                "Optional overall problem statement/stimulus, shown above the "
                "sub-problems below. Build it from text, an image, and/or a "
                "table -- in any combination -- exactly like a sub-problem's "
                "own content; leave it empty if this question doesn't need one."
            ).classes("text-sm text-grey-600 mb-2")

            main_blocks = list(initial.get("main_blocks") or [])
            main_blocks_container = ui.column().classes("w-full gap-2")

            def render_main_blocks():
                """Redraw the overall problem statement's block editor from main_blocks."""
                main_blocks_container.clear()
                with main_blocks_container:
                    if not main_blocks:
                        ui.label(
                            "No problem content yet -- optional; add text, an "
                            "image, and/or a table below if this question needs one."
                        ).classes("text-sm text-grey-500 italic mb-1")
                    _render_block_editor(
                        main_blocks,
                        on_structural_change=lambda: (render_main_blocks(), refresh_validation()),
                        on_content_change=refresh_validation,
                    )

            ui.separator().classes("my-4")
            ui.label("Sub-problems").classes("text-md font-bold mb-1")
            ui.label(
                "Build this question from sub-problems (a), (b), (c)... Each one "
                "always has its own description and marks; optionally attach an "
                "image (a diagram/graph) and/or a table (a gradable step-by-step/"
                "tracing table with its own problem table and answer table) -- "
                "in any combination -- and, optionally, break itself down further "
                "into sub-parts (i), (ii), (iii)... Sub-problems collapse to a "
                "one-line summary by default; click to expand and edit. Total "
                "marks are auto-calculated from all of them (and, for a "
                "sub-problem with sub-parts, from those in turn)."
            ).classes("text-sm text-grey-600 mb-2")

            parts_container = ui.column().classes("w-full gap-2")

            def recalc_total():
                """Recompute total marks from sub-problems and refresh the UI.

                Locks/unlocks the manual Marks field, updates the total-marks
                label, toggles visibility of the overall-answer section, and
                triggers validation -- all in response to sub-problems being
                added, removed, or having their marks edited.
                """
                total = sum(_part_marks(p) for p in parts_data)
                if parts_data:
                    marks_input.value = total
                    marks_input.disable()
                    total_label.text = f"Total marks (auto-calculated from {len(parts_data)} sub-problem(s)): {total}"
                    answer_section.set_visibility(False)
                else:
                    marks_input.enable()
                    total_label.text = ""
                    answer_section.set_visibility(True)
                refresh_validation()

            def _resync_part_marks(idx):
                """Keep sub-problem `idx`'s own "marks" equal to the sum of its sub-parts.

                A no-op while it has none (its "marks" stays whatever was
                directly entered for it). Called after every add/remove/
                marks-edit on a sub-part, before recalc_total() re-sums
                across all sub-problems, so the grand total -- and the
                (disabled) per-sub-problem Marks field the next time it's
                redrawn -- both reflect the sub-parts underneath it.
                """
                subparts = parts_data[idx].get("subparts") or []
                if subparts:
                    parts_data[idx]["marks"] = sum(int(sp.get("marks") or 0) for sp in subparts)

            def render_parts():
                """Redraw the whole sub-problems list from parts_data.

                Clears and rebuilds parts_container so it reflects the
                current parts_data: one collapsible ui.expansion per
                sub-problem, with a one-line summary header and, when
                expanded, its marks/answer-space fields plus its ordered
                list of content blocks (text/image/table, each with
                up/down/remove controls) and the add-block buttons.
                """
                parts_container.clear()
                with parts_container:
                    if not parts_data:
                        ui.label("No sub-problems yet -- click the button below to add one.").classes(
                            "text-sm text-grey-500 italic"
                        )

                    labels = _labels_for(parts_data)

                    # Each of the make_*_handler functions below is a small
                    # factory that closes over this loop iteration's `idx`
                    # (and, for block-level fields, `bi` -- the block's
                    # position within that sub-problem's own "blocks" list
                    # -- plus other loop-local values for the table
                    # fields) and returns the actual NiceGUI event handler
                    # -- needed because a plain closure over the loop
                    # variables would see whatever they ended up being
                    # after the loop finished, not their value at the time
                    # the widget was created.
                    for i, (label, part) in enumerate(zip(labels, parts_data)):
                        blocks = part.setdefault("blocks", [])
                        subparts = part.setdefault("subparts", [])

                        def make_marks_handler(idx):
                            """Return a handler that updates sub-problem `idx`'s marks and recalculates the total."""
                            def handler(e):
                                # Once a sub-problem has sub-parts, its marks
                                # are auto-calculated (see
                                # _resync_part_marks) and this field is
                                # disabled -- guard here too in case an
                                # in-flight event still fires.
                                if parts_data[idx].get("subparts"):
                                    return
                                parts_data[idx]["marks"] = e.value or 0
                                recalc_total()

                            return handler

                        def make_answer_handler(idx):
                            """Return a handler that updates sub-problem `idx`'s standard answer text."""
                            def handler(e):
                                parts_data[idx]["answer"] = e.value
                                refresh_validation()

                            return handler

                        def make_space_handler(idx):
                            """Return a handler that updates sub-problem `idx`'s reserved answer space."""
                            def handler(e):
                                parts_data[idx]["answer_space"] = e.value

                            return handler

                        def make_remove_handler(idx):
                            """Return a handler that deletes sub-problem `idx` and redraws the list."""
                            def handler():
                                parts_data.pop(idx)
                                render_parts()
                                recalc_total()

                            return handler

                        # -- Sub-part handlers -----------------------------
                        # Add/remove a sub-part, or edit its marks/answer/
                        # answer-space -- the third numbering level, (i)/
                        # (ii)/(iii)..., nested inside this sub-problem. All
                        # operate on parts_data[idx]["subparts"][si]; its own
                        # content blocks are handled generically by
                        # _render_block_editor (called below), which
                        # operates directly on the live "blocks" list rather
                        # than needing index-based handlers of its own.

                        def make_subpart_add_handler(idx):
                            """Return a handler that appends a new, empty sub-part to sub-problem `idx`."""
                            def handler():
                                parts_data[idx].setdefault("subparts", []).append({
                                    "marks": 0,
                                    "answer": "",
                                    "answer_space": "half",
                                    "blocks": [{"type": "text", "text": ""}],
                                })
                                _resync_part_marks(idx)
                                render_parts()
                                recalc_total()

                            return handler

                        def make_subpart_remove_handler(idx, si):
                            """Return a handler that deletes sub-part `si` of sub-problem `idx`."""
                            def handler():
                                parts_data[idx]["subparts"].pop(si)
                                _resync_part_marks(idx)
                                render_parts()
                                recalc_total()

                            return handler

                        def make_subpart_marks_handler(idx, si):
                            """Return a handler that updates sub-part `si`'s marks and recalculates totals."""
                            def handler(e):
                                parts_data[idx]["subparts"][si]["marks"] = e.value or 0
                                _resync_part_marks(idx)
                                recalc_total()

                            return handler

                        def make_subpart_answer_handler(idx, si):
                            """Return a handler that updates sub-part `si`'s standard answer text."""
                            def handler(e):
                                parts_data[idx]["subparts"][si]["answer"] = e.value
                                refresh_validation()

                            return handler

                        def make_subpart_space_handler(idx, si):
                            """Return a handler that updates sub-part `si`'s reserved answer space."""
                            def handler(e):
                                parts_data[idx]["subparts"][si]["answer_space"] = e.value

                            return handler

                        has_table = any(b.get("type") == "table" for b in blocks)
                        text_preview = " ".join(
                            (b.get("text") or "").strip() for b in blocks if b.get("type") == "text"
                        ).strip().replace("\n", " ")
                        if len(text_preview) > 60:
                            text_preview = text_preview[:60] + "…"
                        n_images = sum(1 for b in blocks if b.get("type") == "image")
                        n_tables = sum(1 for b in blocks if b.get("type") == "table")
                        badges = []
                        if n_images:
                            badges.append("🖼" if n_images == 1 else f"🖼×{n_images}")
                        if n_tables:
                            badges.append("▦" if n_tables == 1 else f"▦×{n_tables}")
                        if subparts:
                            n_subparts = len(subparts)
                            badges.append(f"{n_subparts} sub-part{'s' if n_subparts != 1 else ''}")
                        badge_str = f"  {' '.join(badges)}" if badges else ""
                        header = f"({label})  {text_preview or '(no description yet)'}{badge_str}  ·  {_part_marks(part)} marks"

                        # A sub-problem broken down into its own (i)/(ii)/
                        # (iii)... sub-parts is "incomplete" based on those
                        # sub-parts, not its own (unused) marks/answer --
                        # same rule the parent question already follows
                        # once it has sub-problems.
                        if subparts:
                            incomplete = False
                            for sp in subparts:
                                sp_blocks = sp.get("blocks") or []
                                sp_table_blocks = [b for b in sp_blocks if b.get("type") == "table"]
                                if not (sp.get("marks") or 0) > 0:
                                    incomplete = True
                                if sp_table_blocks:
                                    for tb in sp_table_blocks:
                                        spec = _table_spec(tb)
                                        if not spec["answer_columns"] or not spec["rows"]:
                                            incomplete = True
                                elif not (sp.get("answer") or "").strip():
                                    incomplete = True
                        else:
                            incomplete = (part.get("marks") or 0) <= 0
                            if has_table:
                                for tb in blocks:
                                    if tb.get("type") != "table":
                                        continue
                                    spec = _table_spec(tb)
                                    if not spec["answer_columns"] or not spec["rows"]:
                                        incomplete = True
                            elif not (part.get("answer") or "").strip():
                                incomplete = True
                        if incomplete:
                            header += "  ⚠ Incomplete"

                        with ui.expansion(
                            header, value=part.get("_expanded", False)
                        ).classes("w-full border") as exp:

                            def make_expand_handler(idx):
                                """Return a handler that records sub-problem `idx`'s expand/collapse state."""
                                def handler(e):
                                    parts_data[idx]["_expanded"] = e.value

                                return handler

                            exp.on_value_change(make_expand_handler(i))

                            with ui.column().classes("w-full gap-2 pt-2"):
                                with ui.row().classes("w-full items-start gap-4"):
                                    ui.label(f"({label})").classes("font-semibold pt-3")
                                    marks_field = ui.number(
                                        label="Marks (auto-calculated)" if subparts else "Marks",
                                        min=0,
                                        max=100,
                                        step=1,
                                        precision=0,
                                        value=_part_marks(part),
                                        on_change=make_marks_handler(i),
                                    ).classes("w-32")
                                    if subparts:
                                        marks_field.disable()
                                    if not has_table and not subparts:
                                        ui.select(
                                            {"half": "Half page", "full": "Full page (new page)"},
                                            label="Answer space",
                                            value=part.get("answer_space", "half"),
                                            on_change=make_space_handler(i),
                                        ).classes("w-52")
                                    ui.button(
                                        icon="delete",
                                        color="red",
                                        on_click=make_remove_handler(i),
                                    ).props("flat dense round")

                                ui.label(
                                    "Content -- add text, an image, and/or a table below, in "
                                    "any order (a diagram between two paragraphs, a table "
                                    "after some instructions, etc.); use the ↑/↓ arrows on a "
                                    "block to move it."
                                ).classes("text-xs text-grey-500")

                                _render_block_editor(
                                    blocks,
                                    on_structural_change=lambda: (render_parts(), recalc_total()),
                                    on_content_change=refresh_validation,
                                )

                                if not has_table and not subparts:
                                    ui.textarea(
                                        label="Standard answer",
                                        placeholder="The standard answer for this sub-problem",
                                        value=part.get("answer", ""),
                                        on_change=make_answer_handler(i),
                                    ).classes("w-full")

                                # -- Sub-parts, (i)/(ii)/(iii)... ----------
                                # The third numbering level: break this
                                # sub-problem down further, the same way
                                # "3. Sub-problems" breaks the question down
                                # into (a)/(b)/(c)... in the first place.
                                ui.separator().classes("my-1")
                                with ui.row().classes("w-full items-center justify-between"):
                                    ui.label(
                                        "Sub-parts -- break this sub-problem down further into "
                                        "(i), (ii), (iii)... (optional)"
                                    ).classes("text-xs font-semibold text-grey-600")
                                    ui.button(
                                        "+ Add sub-part",
                                        icon="add",
                                        on_click=make_subpart_add_handler(i),
                                    ).props("outline dense size=sm")

                                if subparts:
                                    ui.label(
                                        "This sub-problem's marks (above) are the sum of its "
                                        "sub-parts below, and its own standard answer is unused "
                                        "-- each sub-part has its own."
                                    ).classes("text-xs text-grey-500 italic")

                                    for si, subpart in enumerate(subparts):
                                        sub_label = _roman_for_index(si)
                                        sblocks = subpart.setdefault("blocks", [])
                                        sub_has_table = any(b.get("type") == "table" for b in sblocks)

                                        with ui.card().classes("w-full p-3 border-l-4"):
                                            with ui.row().classes("w-full items-start gap-4"):
                                                ui.label(f"({label})({sub_label})").classes("font-semibold pt-3")
                                                ui.number(
                                                    label="Marks",
                                                    min=0,
                                                    max=100,
                                                    step=1,
                                                    precision=0,
                                                    value=subpart.get("marks", 0),
                                                    on_change=make_subpart_marks_handler(i, si),
                                                ).classes("w-32")
                                                if not sub_has_table:
                                                    ui.select(
                                                        {"half": "Half page", "full": "Full page (new page)"},
                                                        label="Answer space",
                                                        value=subpart.get("answer_space", "half"),
                                                        on_change=make_subpart_space_handler(i, si),
                                                    ).classes("w-52")
                                                ui.button(
                                                    icon="delete",
                                                    color="red",
                                                    on_click=make_subpart_remove_handler(i, si),
                                                ).props("flat dense round")

                                            with ui.column().classes("w-full gap-2 mt-1"):
                                                _render_block_editor(
                                                    sblocks,
                                                    on_structural_change=lambda: (render_parts(), recalc_total()),
                                                    on_content_change=refresh_validation,
                                                )

                                            if not sub_has_table:
                                                ui.textarea(
                                                    label="Standard answer",
                                                    placeholder="The standard answer for this sub-part",
                                                    value=subpart.get("answer", ""),
                                                    on_change=make_subpart_answer_handler(i, si),
                                                ).classes("w-full mt-1")

            def add_part():
                """Append a new, expanded sub-problem and collapse the rest.

                Collapses every existing sub-problem and opens only the
                new one, so the list stays scannable instead of growing
                into a wall of open editors. Always starts with a single
                empty text block; the "+ Image"/"+ Table" buttons inside
                it are opt-in, and any block can be reordered or removed
                afterwards.
                """
                for p in parts_data:
                    p["_expanded"] = False
                parts_data.append({
                    "marks": 0,
                    "answer": "",
                    "answer_space": "half",
                    "_expanded": True,
                    "blocks": [{"type": "text", "text": ""}],
                    "subparts": [],
                })
                render_parts()
                recalc_total()

            ui.button("+ Add sub-problem", on_click=add_part, color="secondary").classes("mt-2")

            total_label = ui.label("").classes("text-sm font-semibold mt-2")

        # ------------------------------------------------------------
        # 3. marks + overall answer (only relevant without sub-problems)
        # ------------------------------------------------------------
        with ui.card().classes("w-full p-6"):
            ui.label("3. Marks & Answer (used when there are no sub-problems)").classes("text-lg font-bold mb-3")

            ui.label("Marks").classes("font-semibold")
            marks_input = ui.number(
                label="", min=1, max=100, step=1, precision=0,
                value=initial.get("marks") or 1,
            ).classes("w-full mb-4")

            with ui.column().classes("w-full gap-0") as answer_section:
                ui.label("Answer").classes("font-semibold")
                answer_input = ui.textarea(
                    value=initial.get("answer") or "",
                    placeholder="Enter the answer"
                ).classes("w-full mb-1").props("rows=3").mark("answer_input")
                answer_error_label = ui.label("").classes("text-xs text-red-600 mb-2")

        if meta_lines:
            with ui.row().classes("gap-6"):
                for line in meta_lines:
                    ui.label(line).classes("text-sm text-grey-600")

        # ------------------------------------------------------------
        # Validation (drives the disabled state + tooltip on Save, same
        # idiom export_exam.py uses for its Generate button).
        # ------------------------------------------------------------
        def compute_errors():
            """Collect every reason this question is not yet ready to save.

            Checks title/module/answer requirements, and -- if there are
            sub-problems -- each sub-problem's own completeness rules: if
            it has sub-parts, (i)/(ii)/(iii)... each has its own marks
            plus either a standard answer or a complete table; otherwise
            the sub-problem itself does. If there are no sub-problems at
            all, the plain marks/answer fields are checked instead.

            Returns:
                A list of user-facing error message strings; empty if the
                question is valid and ready to save.
            """
            errors = []
            if not (title_input.value or "").strip():
                errors.append("Question title is required")
            if assigned_modules and not module_input.value:
                errors.append("Please select a module")

            # The overall problem statement is optional, but any table
            # block it does have must still be complete -- same rule a
            # sub-problem's own table blocks follow below.
            main_table_blocks = [b for b in main_blocks if b.get("type") == "table"]
            for tb in main_table_blocks:
                spec = _table_spec(tb)
                if not spec["answer_columns"]:
                    errors.append("Problem's table needs at least one answer column")
                if not spec["rows"]:
                    errors.append("Problem's table needs at least one row of data")

            if parts_data:
                labels = _labels_for(parts_data)
                for p, lbl in zip(parts_data, labels):
                    subparts = p.get("subparts") or []
                    if subparts:
                        for si, sp in enumerate(subparts):
                            sp_label = f"({lbl})({_roman_for_index(si)})"
                            if not (sp.get("marks") or 0) > 0:
                                errors.append(f"Sub-part {sp_label} must have marks greater than 0")
                            sp_table_blocks = [
                                b for b in (sp.get("blocks") or []) if b.get("type") == "table"
                            ]
                            if sp_table_blocks:
                                for tb in sp_table_blocks:
                                    spec = _table_spec(tb)
                                    if not spec["answer_columns"]:
                                        errors.append(f"Sub-part {sp_label}'s table needs at least one answer column")
                                    if not spec["rows"]:
                                        errors.append(f"Sub-part {sp_label}'s table needs at least one row of data")
                            elif not (sp.get("answer") or "").strip():
                                errors.append(f"Sub-part {sp_label} is missing a standard answer")
                        continue
                    if not (p.get("marks") or 0) > 0:
                        errors.append(f"Sub-problem ({lbl}) must have marks greater than 0")
                    table_blocks = [b for b in (p.get("blocks") or []) if b.get("type") == "table"]
                    if table_blocks:
                        for tb in table_blocks:
                            spec = _table_spec(tb)
                            if not spec["answer_columns"]:
                                errors.append(f"Sub-problem ({lbl})'s table needs at least one answer column")
                            if not spec["rows"]:
                                errors.append(f"Sub-problem ({lbl})'s table needs at least one row of data")
                    elif not (p.get("answer") or "").strip():
                        errors.append(f"Sub-problem ({lbl}) is missing a standard answer")
            else:
                if not (marks_input.value or 0) > 0:
                    errors.append("Marks must be greater than 0")
                elif (marks_input.value or 0) > 100:
                    errors.append("Marks must not exceed 100")
                if not (answer_input.value or "").strip():
                    errors.append("Answer is required")

            return errors

        def refresh_validation():
            """Re-run validation and update the inline errors, Save button, and tooltip.

            Called after essentially every field edit so the page's error
            state stays live: updates the title/answer inline error
            labels, then enables or disables the Save button and shows or
            hides its explanatory tooltip based on compute_errors().
            """
            title_ok = bool((title_input.value or "").strip())
            title_error_label.text = "" if title_ok else "Title is required"

            if not parts_data:
                answer_error_label.text = (
                    "" if (answer_input.value or "").strip() else "Answer is required"
                )
            else:
                answer_error_label.text = ""

            errors = compute_errors()
            if save_btn is not None:
                if errors:
                    save_btn.disable()
                else:
                    save_btn.enable()
            if save_tooltip is not None:
                if errors:
                    extra = f" ({len(errors) - 1} more issue(s) to fix)" if len(errors) > 1 else ""
                    save_tooltip.set_text(errors[0] + extra)
                    save_tooltip.set_visibility(True)
                else:
                    save_tooltip.set_visibility(False)

        # Thin wrappers so each field's on_value_change simply re-runs
        # validation.
        def on_title_change(e):
            refresh_validation()

        def on_module_change(e):
            refresh_validation()

        def on_marks_change(e):
            refresh_validation()

        def on_answer_change(e):
            refresh_validation()

        title_input.on_value_change(on_title_change)
        module_input.on_value_change(on_module_change)
        marks_input.on_value_change(on_marks_change)
        answer_input.on_value_change(on_answer_change)

        # ------------------------------------------------------------
        # Preview / Save / Cancel
        # ------------------------------------------------------------
        with ui.row().classes("gap-4 mt-2 items-center"):

            async def on_preview():
                """Compile the question as it currently stands into a preview PDF.

                Builds the LaTeX source and sub-problem payload from the
                current form state (using placeholder text for any
                still-empty fields), compiles it with pdflatex, and opens
                the resulting PDF in a new browser tab for viewing (rather
                than downloading it). Shows a warning/error notification
                instead if the title is empty or the LaTeX compile itself
                fails.
                """
                title = (title_input.value or "").strip()
                if not title:
                    ui.notify("Please fill in the title before previewing.", color="warning")
                    return

                main_content = _build_main_content(main_blocks)
                module = (module_input.value or "").strip().upper() if module_input.value else ""

                if parts_data:
                    labels = _labels_for(parts_data)
                    preview_parts = [
                        _build_part_dict(lbl, p, for_preview=True)
                        for lbl, p in zip(labels, parts_data)
                    ]
                    marks = sum(p["Marks"] for p in preview_parts)
                else:
                    preview_parts = []
                    marks = int(marks_input.value or 0)

                question_dict = {
                    "Question": title,
                    "Main question": main_content["Text"] or None,
                    "Main content blocks": main_content["Content blocks"],
                    "Module": module or None,
                }

                # NOTE: this "description" string is baked into the LaTeX
                # source (see latex_export.py's _HEADER), which is compiled
                # with pdflatex -- pdflatex's default fonts have no CJK
                # glyphs at all, so *any* Chinese/Japanese/etc. character
                # reaching build_latex() (in the title, module, question
                # body, or a sub-problem's description/answer) makes the
                # whole compile fail with a fatal "Unicode character ...
                # not set up for use with LaTeX" error -- not just here,
                # but the same way in the real /exams/export flow. Keeping
                # this particular label in English sidesteps it for the
                # preview button itself; it doesn't fix the underlying
                # limitation for question content a teacher types in
                # Chinese (see the message accompanying this change).
                tex, assets = build_latex(
                    name=title,
                    description="Preview",
                    total_marks=marks,
                    questions_with_marks=[(question_dict, marks, preview_parts)],
                    mode="example",
                )

                preview_btn.props("loading")
                try:
                    try:
                        pdf_bytes = await run.io_bound(compile_latex_to_pdf, tex, 60, assets)
                    except LatexCompileError as exc:
                        ui.notify(str(exc), color="negative", multi_line=True, close_button=True)
                        return
                finally:
                    preview_btn.props(remove="loading")

                token = _cache_preview_pdf(pdf_bytes)
                ui.navigate.to(f"/questions/preview.pdf?token={token}", new_tab=True)
                ui.notify("Preview generated -- opened in a new tab.", color="positive")

            preview_btn = ui.button("Preview PDF", on_click=on_preview, color="secondary").props("outline")

            def save_question():
                """Validate the form and hand the finished payload to `on_save`.

                Re-validates the title/answer/sub-problem requirements
                (defensively, in addition to the Save button's disabled
                state), builds the sub-problem payload, works out the
                total marks, then delegates everything else -- actually
                persisting it, notifying the user, and navigating away --
                to `on_save`. Shows a notification and returns early on
                the first validation failure encountered.
                """
                title = (title_input.value or "").strip()
                module = (module_input.value or "").strip().upper()
                topic = (topic_input.value or "").strip()
                main_content = _build_main_content(main_blocks)
                answer = (answer_input.value or "").strip()

                if not title:
                    ui.notify("Question title is required.", color="negative")
                    return

                if not parts_data and not answer:
                    ui.notify("Answer is required.", color="negative")
                    return

                # Defensive re-check (in addition to the Save button's
                # disabled state): compute_errors() already validates
                # every sub-problem's marks and, per content block, its
                # standard answer/table completeness, so it replaces the
                # old bespoke checks here -- which only ever inspected a
                # sub-problem's *first* table block and would have missed
                # a second, incomplete one now that a sub-problem can
                # carry more than one.
                errors = compute_errors()
                if errors:
                    ui.notify(errors[0], color="negative")
                    return

                # Build the sub-problem payload (if any) and work out marks.
                labels = _labels_for(parts_data)
                parts_payload = [
                    _build_part_dict(lbl, p, for_preview=False)
                    for lbl, p in zip(labels, parts_data)
                ]

                if parts_payload:
                    marks = sum(p["Marks"] for p in parts_payload)
                else:
                    marks = marks_input.value
                    if not marks or marks <= 0:
                        ui.notify("Marks must be greater than 0.", color="negative")
                        return
                    if marks > 100:
                        ui.notify("Marks must not exceed 100.", color="negative")
                        return
                    marks = int(marks)

                on_save({
                    "title": title,
                    "module": module,
                    "topic": topic,
                    "main_content_blocks": main_content["Content blocks"],
                    "main_text": main_content["Text"],
                    "marks": marks,
                    "answer": answer,
                    "parts_payload": parts_payload,
                })

            with ui.element("div") as save_wrapper:
                save_btn = ui.button(save_button_label, on_click=save_question, color="primary")
            save_tooltip = (
                ui.tooltip("")
                .props(f'target="#{save_wrapper.html_id}"')
                .style("font-size: 14px")
            )

            ui.button("Cancel", on_click=lambda: ui.navigate.to("/questions"))

            if extra_actions:
                for action_label, action_handler in extra_actions:
                    ui.button(action_label, on_click=action_handler)

        # Initial paint: render any pre-existing problem-statement blocks
        # and sub-problems (otherwise their containers stay empty until
        # first edited, hiding a question's existing content when
        # editing it), then validate/lock according to the starting
        # values (any pre-existing sub-problems lock+auto-calculate
        # Marks and hide the overall Answer section); Save starts
        # disabled until the required fields above are filled in.
        render_main_blocks()
        render_parts()
        recalc_total()


def create_question_page():
    """Create new question page.

    Thin wrapper around render_question_editor(): starts from a
    completely blank form and, once it validates, persists a brand-new
    question via database.add_question / replace_question_parts. See
    render_question_editor()'s docstring for what the shared form itself
    supports.

    The Module field is not chosen here -- it's fixed to whatever module
    the teacher last picked on the Module Selection page
    (app.storage.user["current_module"]; see module_selection.py). If
    they haven't picked one yet this session, they're sent there first
    instead of seeing a form with no module to save under.
    """

    # Check login
    if not app.storage.user.get("logged_in"):
        ui.navigate.to("/login")
        return

    username = app.storage.user["username"]
    assigned_modules = get_teacher_modules(username)
    existing_topics = list_teacher_topics(username)

    current_module = app.storage.user.get("current_module")
    if not current_module or current_module not in assigned_modules:
        ui.notify("Please select a module first.", color="warning")
        ui.navigate.to("/modules")
        return

    def on_save(payload):
        """Persist a brand-new question from the validated form payload."""
        new_question = {
            "Question": payload["title"],
            "Main question": payload["main_text"] or None,
            "Main content blocks": payload["main_content_blocks"] or None,
            "Marks": payload["marks"],
            "Answer": payload["answer"] or None,
            "Status": "Draft",
            "Version": 1,
            "Created by": username,
            "Created at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Usage": 0,
            "Module": payload["module"] or None,
            "Topic": payload["topic"] or None,
        }

        question_id = add_question(new_question)

        if payload["parts_payload"]:
            replace_question_parts(question_id, payload["parts_payload"])

        if payload["topic"]:
            add_teacher_topic(username, payload["topic"])

        ui.notify(
            f"Question created successfully! (ID: {question_id})",
            color="positive"
        )
        ui.navigate.to("/questions")

    render_question_editor(
        page_heading="Create New Question",
        save_button_label="Save",
        assigned_modules=assigned_modules,
        existing_topics=existing_topics,
        initial={
            "title": "",
            "module": current_module,
            "topic": "",
            "main_blocks": [],
            "marks": 1,
            "answer": "",
            "parts_data": [],
        },
        on_save=on_save,
        fixed_module=current_module,
    )
