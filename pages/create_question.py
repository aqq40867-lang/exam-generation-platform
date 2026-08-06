"""NiceGUI page for creating a new exam question.

Renders the "Create New Question" form, built around an ordered list of
components (Text, Table, Material, Image) that a teacher assembles freely.
Handles client-side validation, PDF preview generation via latex_export,
and persisting the finished question with database.add_question /
replace_question_parts.
"""

import base64
import mimetypes
import string
from datetime import datetime

from nicegui import ui, app, run

from database import add_question, replace_question_parts, get_teacher_modules, list_topics
from latex_export import build_latex, compile_latex_to_pdf, LatexCompileError


# Component types a question can be built from. Only "text" and "table" are
# gradable (carry marks, get lettered (a)/(b)/(c)... labels); "material" and
# "image" are stimulus content -- shown inline wherever they sit in the
# order, never graded, never lettered. Mirrors database.py's
# replace_question_parts, which independently enforces the same rules
# server-side (this UI mirroring it is a convenience, not the source of
# truth for what actually gets saved).
_GRADABLE_TYPES = ("text", "table")
_COMPONENT_TYPE_LABELS = {
    "text": "Text",
    "table": "Table",
    "material": "Material",
    "image": "Image",
}
_MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB


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
    """Compute the display label for each component in order.

    Mirrors exactly how database.py's replace_question_parts assigns
    labels when actually saving, so what's previewed here is what gets
    saved.

    Args:
        parts_data: The page's in-memory list of component dicts, each
            with a "part_type" key.

    Returns:
        A list with one entry per item in parts_data: the next letter
        ("a", "b", "c", ...) for a gradable ("text"/"table") component, or
        None for a non-gradable ("material"/"image") one.
    """
    labels = []
    counter = 0
    for p in parts_data:
        if p.get("part_type", "text") in _GRADABLE_TYPES:
            labels.append(_label_for_index(counter))
            counter += 1
        else:
            labels.append(None)
    return labels


def _table_spec(part: dict) -> dict:
    """Build the {"given_columns", "answer_columns", "rows"} shape for a table component.

    A "table"-type component keeps its data directly in this shape in
    parts_data already -- "table_given_columns" / "table_answer_columns"
    (each a list of column-name strings) and "table_rows" (a list of
    rows, each a list of cell strings ordered given-columns-first then
    answer-columns-first) -- built up by the grid editor's add/remove
    column/row handlers, which maintain the invariant that every row's
    length always equals len(given_columns) + len(answer_columns). So,
    unlike the old plain-text fields this replaced, there's no parsing
    (or parse errors) here -- this just reads the three lists back out
    with sensible defaults for a component that's never been switched to
    "table" type yet.

    Args:
        part: The raw in-memory state dict for one component.

    Returns:
        A dict with "given_columns", "answer_columns", and "rows" keys,
        matching what database.py's replace_question_parts / latex_export.py's
        table renderer expect as a "Table spec".
    """
    return {
        "given_columns": list(part.get("table_given_columns") or []),
        "answer_columns": list(part.get("table_answer_columns") or []),
        "rows": [list(r) for r in (part.get("table_rows") or [])],
    }


def _build_part_dict(label, part: dict, *, for_preview: bool) -> dict:
    """Build the dict shape build_latex() / replace_question_parts() expect.

    Converts one component's raw create-page state into the normalized
    dict shape used both for the PDF preview and for the actual save.

    Args:
        label: This component's precomputed letter (from _labels_for()),
            or None for a non-gradable component.
        part: The raw in-memory state dict for this single component.
        for_preview: If True, fills in placeholder text for still-empty
            fields so an incomplete question can still be previewed. If
            False (used when actually saving), leaves them as None
            instead.

    Returns:
        A dict with the keys expected by build_latex() /
        replace_question_parts() ("Label", "Description", "Marks",
        "Answer space", "Part type", "Table spec", "Answer", "Image data",
        "Image filename").
    """
    part_type = part.get("part_type", "text")
    description = (part.get("description") or "").strip()

    result = {
        "Label": label,
        "Description": None,
        "Marks": 0,
        "Answer space": part.get("answer_space") or "half",
        "Part type": part_type,
        "Table spec": None,
        "Answer": None,
        "Image data": None,
        "Image filename": None,
    }

    if part_type == "table":
        result["Description"] = description or ("(no description yet)" if for_preview else None)
        result["Marks"] = int(part.get("marks") or 0)
        result["Table spec"] = _table_spec(part)
    elif part_type == "material":
        result["Description"] = description or ("(no material text yet)" if for_preview else None)
    elif part_type == "image":
        result["Description"] = description or None  # optional caption
        result["Image data"] = part.get("image_data")
        result["Image filename"] = part.get("image_filename")
    else:  # "text"
        result["Description"] = description or ("(no description yet)" if for_preview else None)
        result["Marks"] = int(part.get("marks") or 0)
        answer = (part.get("answer") or "").strip()
        result["Answer"] = answer or ("(no standard answer yet)" if for_preview else None)

    return result


def create_question_page():
    """Create new question page.

    Built around a single ordered list of *components* -- Text (a gradable
    sub-question), Table (a gradable step-by-step/tracing table), Material
    (a block of reading material/stimulus, shown inline wherever it sits,
    not gradable), or Image (an embedded diagram/graph, not gradable) --
    added and reordered freely rather than picked from a fixed set of
    whole-question presets. A new component always defaults to "Text" (the
    most common case), so adding one is never a blank menu to puzzle over.
    Each component collapses to a one-line summary until opened, and the
    Save button stays disabled (with a tooltip explaining why) until the
    question is actually valid, instead of only failing after you click it.
    """

    # Check login
    if not app.storage.user.get("logged_in"):
        ui.navigate.to("/login")
        return

    username = app.storage.user["username"]
    assigned_modules = get_teacher_modules(username)
    existing_topics = list_topics(username)

    # In-memory state for the ordered list of components. Each entry is a
    # plain dict covering every component type's fields at once (only the
    # ones relevant to its current "part_type" are read/shown -- switching
    # a component's type doesn't discard whatever was typed into the
    # others, in case it gets switched back):
    #   part_type: "text" | "table" | "material" | "image"
    #   description: str (sub-question text / material body / image caption)
    #   marks: number (ignored for material/image -- always saved as 0)
    #   answer: str (only used by "text")
    #   answer_space: "half"|"full" (only used by "text")
    #   table_given_columns / table_answer_columns: list[str] (column names)
    #   table_rows: list[list[str]] (each row's cells, given columns first
    #     then answer columns, always kept the same length as
    #     len(table_given_columns) + len(table_answer_columns) by the grid
    #     editor's add/remove column/row handlers)
    #   image_data: base64 str or None, image_filename: str or None
    #   _expanded: bool -- whether this component's editor is open or
    #     collapsed to a one-line summary; stripped out before saving.
    parts_data = []

    # Assigned by the button-creation code further down; declared here (and
    # guarded with "is not None" checks) so validation callbacks registered
    # on earlier fields don't blow up if they fire before the buttons at
    # the bottom of the page exist yet -- same pattern export_exam.py uses
    # for its Generate button/tooltip.
    save_btn = None
    save_tooltip = None
    preview_btn = None

    with ui.column().classes("w-full max-w-4xl mx-auto p-8 gap-4"):

        ui.label("Create New Question").classes("text-3xl font-bold mb-2")

        # ------------------------------------------------------------
        # 1. Basic info
        # ------------------------------------------------------------
        with ui.card().classes("w-full p-6"):
            ui.label("1. Basic Info").classes("text-lg font-bold mb-3")

            ui.label("Question Title").classes("font-semibold")
            title_input = ui.input(
                placeholder='e.g. "Definitions" / "Kruskal\'s Algorithm"'
            ).classes("w-full").mark("title_input")
            title_error_label = ui.label("").classes("text-xs text-red-600 mb-2")

            ui.label("Module").classes("font-semibold mt-1")
            if assigned_modules:
                module_input = ui.select(assigned_modules, label="").classes("w-full mb-1").mark("module_select")
            else:
                module_input = (
                    ui.select([], label="").classes("w-full mb-1").props("disable").mark("module_select")
                )
                ui.label(
                    "You haven't been assigned any modules yet. Contact your admin "
                    "to get one assigned before selecting."
                ).classes("text-sm text-negative mb-1")

            ui.label("Topic / Knowledge Point").classes("font-semibold mt-1")
            topic_input = ui.input(
                placeholder='e.g. "Stacks", "Kruskal\'s Algorithm", "Binary Search Trees" (optional)',
                autocomplete=existing_topics,
            ).classes("w-full mb-1").mark("topic_input")
            ui.label(
                "Helps tell questions apart at a glance in the question list -- "
                "optional but recommended, since the title alone often doesn't say "
                "what the question is actually about."
            ).classes("text-xs text-grey-500 mb-1")

        # ------------------------------------------------------------
        # 2. Introduction (optional)
        # ------------------------------------------------------------
        with ui.card().classes("w-full p-6"):
            ui.label("2. Introduction (optional)").classes("text-lg font-bold mb-1")
            ui.label(
                "A short line of shared context shown once, right under the title, "
                "before any components below (e.g. \"Answer both parts using the "
                "graph on the following page.\"). For material tied to a specific "
                "point in the question -- not just the very top -- add a Material "
                "component below instead; it can go anywhere in the sequence."
            ).classes("text-sm text-grey-600 mb-2")
            main_text_input = ui.textarea(
                placeholder="Optional -- leave blank if this question doesn't need one"
            ).classes("w-full").props("rows=3")

        # ------------------------------------------------------------
        # 3. Components
        # ------------------------------------------------------------
        with ui.card().classes("w-full p-6"):
            ui.label("3. Components").classes("text-lg font-bold mb-1")
            ui.label(
                "Build this question from components, in any order: Text (a "
                "gradable sub-question), Table (a gradable step-by-step/tracing "
                "table), Material (a block of reading material/stimulus, not "
                "gradable), or Image (an embedded diagram/graph, not gradable). "
                "Components collapse to a one-line summary by default; click to "
                "expand and edit. Total marks are auto-calculated from the "
                "gradable ones."
            ).classes("text-sm text-grey-600 mb-2")

            parts_container = ui.column().classes("w-full gap-2")

            def recalc_total():
                """Recompute total marks from gradable components and refresh the UI.

                Locks/unlocks the manual Marks field, updates the total-marks
                label, toggles visibility of the overall-answer section, and
                triggers validation -- all in response to components being
                added, removed, or having their marks edited.
                """
                total = sum((p.get("marks") or 0) for p in parts_data if p.get("part_type", "text") in _GRADABLE_TYPES)
                if parts_data:
                    marks_input.value = total
                    marks_input.disable()
                    total_label.text = f"Total marks (auto-calculated from {len(parts_data)} component(s)): {total}"
                    answer_section.set_visibility(False)
                else:
                    marks_input.enable()
                    total_label.text = ""
                    answer_section.set_visibility(True)
                refresh_validation()

            def render_parts():
                """Redraw the whole components list from parts_data.

                Clears and rebuilds parts_container so it reflects the
                current parts_data: one collapsible ui.expansion per
                component, with a one-line summary header and, when
                expanded, the type-specific editor fields for that
                component.
                """
                parts_container.clear()
                with parts_container:
                    if not parts_data:
                        ui.label("No components yet -- click the button below to add one.").classes(
                            "text-sm text-grey-500 italic"
                        )

                    labels = _labels_for(parts_data)

                    # Each of the make_*_handler functions below is a small
                    # factory that closes over this loop iteration's `idx`
                    # (and, for the table fields, `field`) and returns the
                    # actual NiceGUI event handler -- needed because a
                    # plain closure over the loop variable `i` would see
                    # whatever `i` ended up being after the loop finished,
                    # not the value at the time the widget was created.
                    for i, (label, part) in enumerate(zip(labels, parts_data)):

                        def make_desc_handler(idx):
                            """Return a handler that updates component `idx`'s description text."""
                            def handler(e):
                                parts_data[idx]["description"] = e.value
                                refresh_validation()

                            return handler

                        def make_marks_handler(idx):
                            """Return a handler that updates component `idx`'s marks and recalculates the total."""
                            def handler(e):
                                parts_data[idx]["marks"] = e.value or 0
                                recalc_total()

                            return handler

                        def make_answer_handler(idx):
                            """Return a handler that updates component `idx`'s standard answer text."""
                            def handler(e):
                                parts_data[idx]["answer"] = e.value
                                refresh_validation()

                            return handler

                        def make_space_handler(idx):
                            """Return a handler that updates component `idx`'s reserved answer space."""
                            def handler(e):
                                parts_data[idx]["answer_space"] = e.value

                            return handler

                        def make_part_type_handler(idx):
                            """Return a handler that switches component `idx` to a different type.

                            Unlike marks/description/answer edits, a type
                            change rebuilds the whole components list
                            (rather than just poking the backing dict)
                            because the editor fields shown look
                            completely different per type.
                            """
                            def handler(e):
                                parts_data[idx]["part_type"] = e.value
                                # First time this component becomes a
                                # table, seed one given column, one answer
                                # column, and one row -- an empty grid
                                # with nothing but "+" buttons is a
                                # confusing blank slate; a single starter
                                # row/column pair is easy to rename or
                                # delete, and shows what the grid does.
                                if (
                                    e.value == "table"
                                    and not parts_data[idx].get("table_given_columns")
                                    and not parts_data[idx].get("table_answer_columns")
                                ):
                                    parts_data[idx]["table_given_columns"] = ["Given 1"]
                                    parts_data[idx]["table_answer_columns"] = ["Answer 1"]
                                    parts_data[idx]["table_rows"] = [["", ""]]
                                render_parts()
                                recalc_total()

                            return handler

                        def make_table_rename_col_handler(idx, group, col_i):
                            """Return a handler that renames given/answer column `col_i` of component `idx`.

                            Just updates the name in place -- doesn't touch
                            row data, so it only needs a validation
                            refresh, not a full re-render (typing in the
                            name field would otherwise lose focus on every
                            keystroke).
                            """
                            key = "table_given_columns" if group == "given" else "table_answer_columns"

                            def handler(e):
                                parts_data[idx][key][col_i] = e.value
                                refresh_validation()

                            return handler

                        def make_table_cell_handler(idx, row_i, col_i):
                            """Return a handler that updates one row/column cell of component `idx`'s table.

                            Same reasoning as make_table_rename_col_handler:
                            no re-render needed for a plain value edit.
                            """
                            def handler(e):
                                parts_data[idx]["table_rows"][row_i][col_i] = e.value
                                refresh_validation()

                            return handler

                        def make_table_add_col_handler(idx, group):
                            """Return a handler that appends a new given/answer column to component `idx`'s table.

                            Every row keeps given-columns-first-then-answer-
                            columns order, so a new given column's cell is
                            inserted right at the given/answer boundary in
                            every existing row (pushing answer cells along),
                            while a new answer column's cell is simply
                            appended at the end of every row.
                            """
                            def handler():
                                p = parts_data[idx]
                                given = p.setdefault("table_given_columns", [])
                                answer = p.setdefault("table_answer_columns", [])
                                rows = p.setdefault("table_rows", [])
                                if group == "given":
                                    boundary = len(given)
                                    given.append("")
                                    for row in rows:
                                        row.insert(boundary, "")
                                else:
                                    answer.append("")
                                    for row in rows:
                                        row.append("")
                                render_parts()
                                refresh_validation()

                            return handler

                        def make_table_remove_col_handler(idx, group, col_i):
                            """Return a handler that deletes given/answer column `col_i` from component `idx`'s table.

                            Removes the column's own name entry and, from
                            every row, the one cell at that column's
                            position -- keeping every row's length in sync
                            with the new column count.
                            """
                            def handler():
                                p = parts_data[idx]
                                given = p.get("table_given_columns", [])
                                answer = p.get("table_answer_columns", [])
                                rows = p.get("table_rows", [])
                                real_i = col_i if group == "given" else len(given) + col_i
                                if group == "given":
                                    if col_i < len(given):
                                        given.pop(col_i)
                                elif col_i < len(answer):
                                    answer.pop(col_i)
                                for row in rows:
                                    if real_i < len(row):
                                        row.pop(real_i)
                                render_parts()
                                refresh_validation()

                            return handler

                        def make_table_add_row_handler(idx):
                            """Return a handler that appends a new, blank row to component `idx`'s table."""
                            def handler():
                                p = parts_data[idx]
                                total = len(p.get("table_given_columns", [])) + len(p.get("table_answer_columns", []))
                                p.setdefault("table_rows", []).append([""] * total)
                                render_parts()
                                refresh_validation()

                            return handler

                        def make_table_remove_row_handler(idx, row_i):
                            """Return a handler that deletes row `row_i` from component `idx`'s table."""
                            def handler():
                                rows = parts_data[idx].get("table_rows", [])
                                if row_i < len(rows):
                                    rows.pop(row_i)
                                render_parts()
                                refresh_validation()

                            return handler

                        def make_image_upload_handler(idx):
                            """Return a handler that stores an uploaded image on component `idx`.

                            Reads the uploaded file, base64-encodes it into
                            parts_data, and rejects (with a warning) an
                            empty file.
                            """
                            async def handler(e):
                                data = await e.file.read()
                                if not data:
                                    ui.notify("That file appears to be empty.", color="warning")
                                    return
                                parts_data[idx]["image_data"] = base64.b64encode(data).decode("ascii")
                                parts_data[idx]["image_filename"] = e.file.name
                                render_parts()
                                recalc_total()

                            return handler

                        def make_remove_handler(idx):
                            """Return a handler that deletes component `idx` and redraws the list."""
                            def handler():
                                parts_data.pop(idx)
                                render_parts()
                                recalc_total()

                            return handler

                        part_type = part.get("part_type", "text")

                        if part_type == "table":
                            _spec = _table_spec(part)
                            complete = bool(_spec["answer_columns"]) and bool(_spec["rows"])
                            ncols = len(_spec["given_columns"]) + len(_spec["answer_columns"])
                            nrows = len(_spec["rows"])
                            header = f"({label})  Table · {nrows} row(s), {ncols} column(s)  ·  {part.get('marks') or 0} marks"
                            if not complete or (part.get("marks") or 0) <= 0:
                                header += "  ⚠ Incomplete"
                        elif part_type == "material":
                            preview = (part.get("description") or "").strip().replace("\n", " ")
                            if len(preview) > 60:
                                preview = preview[:60] + "…"
                            header = f"[Material]  {preview or '(empty)'}"
                            if not preview:
                                header += "  ⚠ Incomplete"
                        elif part_type == "image":
                            header = f"[Image]  {part.get('image_filename') or 'no image uploaded yet'}"
                            if not part.get("image_data"):
                                header += "  ⚠ Incomplete"
                        else:
                            preview = (part.get("description") or "").strip().replace("\n", " ")
                            if len(preview) > 60:
                                preview = preview[:60] + "…"
                            header = f"({label})  {preview or '(no description yet)'}  ·  {part.get('marks') or 0} marks"
                            if (part.get("marks") or 0) <= 0 or not (part.get("answer") or "").strip():
                                header += "  ⚠ Incomplete"

                        with ui.expansion(
                            header, value=part.get("_expanded", False)
                        ).classes("w-full border") as exp:

                            def make_expand_handler(idx):
                                """Return a handler that records component `idx`'s expand/collapse state."""
                                def handler(e):
                                    parts_data[idx]["_expanded"] = e.value

                                return handler

                            exp.on_value_change(make_expand_handler(i))

                            with ui.column().classes("w-full gap-2 pt-2"):
                                with ui.row().classes("w-full items-start gap-4"):
                                    ui.select(
                                        _COMPONENT_TYPE_LABELS,
                                        label="Component type",
                                        value=part_type,
                                        on_change=make_part_type_handler(i),
                                    ).classes("w-40")
                                    if part_type in _GRADABLE_TYPES:
                                        ui.number(
                                            label="Marks",
                                            min=0,
                                            step=1,
                                            value=part.get("marks", 0),
                                            on_change=make_marks_handler(i),
                                        ).classes("w-32")
                                    if part_type == "text":
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

                                if part_type == "table":
                                    ui.textarea(
                                        label="Sub-question description",
                                        placeholder="The sub-question's own text (optional, e.g. specific phrasing/requirements)",
                                        value=part.get("description", ""),
                                        on_change=make_desc_handler(i),
                                    ).classes("w-full").props("rows=2")

                                    ui.label(
                                        "Name each column and mark it Given (grey -- information "
                                        "the student can see) or Answer (blue -- left blank on the "
                                        "practice paper, filled in on the answer paper), then fill "
                                        "in each row below."
                                    ).classes("text-xs text-grey-600")

                                    given_cols = part.get("table_given_columns") or []
                                    answer_cols = part.get("table_answer_columns") or []
                                    table_rows = part.get("table_rows") or []
                                    total_cols = len(given_cols) + len(answer_cols)
                                    _GIVEN_BG = "#f3f4f6"
                                    _ANSWER_BG = "#dbeafe"

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
                                                        on_change=make_table_rename_col_handler(i, "given", gi),
                                                    ).props("dense outlined").style(
                                                        f"background:{_GIVEN_BG}"
                                                    ).classes("w-full")
                                                    ui.button(
                                                        icon="close",
                                                        color="red",
                                                        on_click=make_table_remove_col_handler(i, "given", gi),
                                                    ).props("flat dense round size=sm")
                                            for ai, name in enumerate(answer_cols):
                                                with ui.row().classes("items-center gap-0 no-wrap"):
                                                    ui.input(
                                                        value=name,
                                                        placeholder=f"Answer {ai + 1}",
                                                        on_change=make_table_rename_col_handler(i, "answer", ai),
                                                    ).props("dense outlined").style(
                                                        f"background:{_ANSWER_BG}"
                                                    ).classes("w-full")
                                                    ui.button(
                                                        icon="close",
                                                        color="red",
                                                        on_click=make_table_remove_col_handler(i, "answer", ai),
                                                    ).props("flat dense round size=sm")
                                            ui.label("")  # spacer above the row-delete button column

                                            for ri, row in enumerate(table_rows):
                                                for ci in range(total_cols):
                                                    is_given = ci < len(given_cols)
                                                    ui.input(
                                                        value=row[ci] if ci < len(row) else "",
                                                        on_change=make_table_cell_handler(i, ri, ci),
                                                    ).props("dense outlined").style(
                                                        f"background:{_GIVEN_BG if is_given else _ANSWER_BG}"
                                                    ).classes("w-full")
                                                ui.button(
                                                    icon="delete",
                                                    color="red",
                                                    on_click=make_table_remove_row_handler(i, ri),
                                                ).props("flat dense round size=sm")
                                    else:
                                        ui.label(
                                            "No columns yet -- add a given or answer column below to start."
                                        ).classes("text-xs text-grey-500 italic mt-1")

                                    with ui.row().classes("gap-2 mt-2"):
                                        ui.button(
                                            "+ Given column",
                                            icon="add",
                                            on_click=make_table_add_col_handler(i, "given"),
                                        ).props("outline dense size=sm")
                                        ui.button(
                                            "+ Answer column",
                                            icon="add",
                                            on_click=make_table_add_col_handler(i, "answer"),
                                        ).props("outline dense size=sm")
                                        ui.button(
                                            "+ Row",
                                            icon="add",
                                            on_click=make_table_add_row_handler(i),
                                        ).props("outline dense size=sm")

                                elif part_type == "material":
                                    ui.label(
                                        "Material text -- shown inline at this exact point in the "
                                        "question, not gradable and not lettered."
                                    ).classes("text-xs text-grey-600")
                                    ui.textarea(
                                        label="Material text",
                                        placeholder="The reading material / stimulus text shown here",
                                        value=part.get("description", ""),
                                        on_change=make_desc_handler(i),
                                    ).classes("w-full").props("rows=4")

                                elif part_type == "image":
                                    ui.label(
                                        "Image -- shown inline at this exact point in the question, "
                                        "not gradable and not lettered. PNG or JPEG, up to 5 MB."
                                    ).classes("text-xs text-grey-600")

                                    if part.get("image_data"):
                                        mime = mimetypes.guess_type(part.get("image_filename") or "")[0] or "image/png"
                                        ui.image(f"data:{mime};base64,{part['image_data']}").classes(
                                            "w-64 border rounded"
                                        )
                                        ui.label(part.get("image_filename") or "").classes(
                                            "text-xs text-grey-600 mb-1"
                                        )
                                    else:
                                        ui.label("No image uploaded yet.").classes(
                                            "text-xs text-grey-500 italic mb-1"
                                        )

                                    ui.upload(
                                        label="Upload image (replaces the current one)",
                                        auto_upload=True,
                                        max_file_size=_MAX_IMAGE_BYTES,
                                        on_upload=make_image_upload_handler(i),
                                        on_rejected=lambda: ui.notify(
                                            "That file is too large (max 5 MB) or was rejected.",
                                            color="negative",
                                        ),
                                    ).props('accept=".png,.jpg,.jpeg"').classes("w-full")

                                    ui.label("Caption (optional)").classes("text-xs font-semibold mt-1")
                                    ui.input(
                                        value=part.get("description", ""),
                                        placeholder='Shown under the image on the exported paper, e.g. "Figure 1: example graph"',
                                        on_change=make_desc_handler(i),
                                    ).classes("w-full")

                                else:  # "text"
                                    ui.textarea(
                                        label="Sub-question description",
                                        placeholder="The sub-question's own text (optional, e.g. specific phrasing/requirements)",
                                        value=part.get("description", ""),
                                        on_change=make_desc_handler(i),
                                    ).classes("w-full").props("rows=2")
                                    ui.textarea(
                                        label="Standard answer",
                                        placeholder="The standard answer for this sub-question",
                                        value=part.get("answer", ""),
                                        on_change=make_answer_handler(i),
                                    ).classes("w-full").props("rows=3")

            def add_part():
                """Append a new, expanded "Text" component and collapse the rest.

                Collapses every existing component and opens only the new
                one, so the list stays scannable instead of growing into a
                wall of open editors. Always defaults to "Text" -- the
                most common component, so adding one is never a blank
                menu to puzzle over; switch its type afterwards if you
                meant to add a Table/Material/Image instead.
                """
                for p in parts_data:
                    p["_expanded"] = False
                parts_data.append({
                    "part_type": "text",
                    "description": "",
                    "marks": 0,
                    "answer": "",
                    "answer_space": "half",
                    "table_given_columns": [],
                    "table_answer_columns": [],
                    "table_rows": [],
                    "image_data": None,
                    "image_filename": None,
                    "_expanded": True,
                })
                render_parts()
                recalc_total()

            ui.button("+ Add Component", on_click=add_part, color="secondary").classes("mt-2")

            total_label = ui.label("").classes("text-sm font-semibold mt-2")

        # ------------------------------------------------------------
        # 4. marks + overall answer (only relevant without components)
        # ------------------------------------------------------------
        with ui.card().classes("w-full p-6"):
            ui.label("4. Marks & Answer (used when there are no components)").classes("text-lg font-bold mb-3")

            ui.label("Marks").classes("font-semibold")
            marks_input = ui.number(label="", min=1, step=1).classes("w-full mb-4")

            with ui.column().classes("w-full gap-0") as answer_section:
                ui.label("Answer").classes("font-semibold")
                answer_input = ui.textarea(placeholder="Enter the answer").classes("w-full mb-1").props("rows=3").mark("answer_input")
                answer_error_label = ui.label("").classes("text-xs text-red-600 mb-2")

        # ------------------------------------------------------------
        # Validation (drives the disabled state + tooltip on Save, same
        # idiom export_exam.py uses for its Generate button).
        # ------------------------------------------------------------
        def compute_errors():
            """Collect every reason this question is not yet ready to save.

            Checks title/module/answer requirements, and -- if there are
            components -- each component's own completeness rules (marks,
            standard answer, table columns/rows, material text, image
            upload), otherwise the plain marks/answer fields.

            Returns:
                A list of user-facing error message strings; empty if the
                question is valid and ready to save.
            """
            errors = []
            if not (title_input.value or "").strip():
                errors.append("Question title is required")
            if assigned_modules and not module_input.value:
                errors.append("Please select a module")

            if parts_data:
                labels = _labels_for(parts_data)
                has_gradable = False
                for p, lbl in zip(parts_data, labels):
                    part_type = p.get("part_type", "text")

                    if part_type == "text":
                        has_gradable = True
                        if not (p.get("marks") or 0) > 0:
                            errors.append(f"Sub-question ({lbl}) must have marks greater than 0")
                        if not (p.get("answer") or "").strip():
                            errors.append(f"Sub-question ({lbl}) is missing a standard answer")
                    elif part_type == "table":
                        has_gradable = True
                        if not (p.get("marks") or 0) > 0:
                            errors.append(f"Sub-question ({lbl}) must have marks greater than 0")
                        spec = _table_spec(p)
                        if not spec["answer_columns"]:
                            errors.append(f"Sub-question ({lbl})'s table needs at least one answer column")
                        if not spec["rows"]:
                            errors.append(f"Sub-question ({lbl})'s table needs at least one row of data")
                    elif part_type == "material":
                        if not (p.get("description") or "").strip():
                            errors.append("A material component is empty -- add its text or remove it")
                    elif part_type == "image":
                        if not p.get("image_data"):
                            errors.append("An image component has no image uploaded yet")

                if not has_gradable:
                    errors.append("Add at least one Text or Table component so the question has marks to grade")
            else:
                if not (marks_input.value or 0) > 0:
                    errors.append("Marks must be greater than 0")
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

                Builds the LaTeX source and component payload from the
                current form state (using placeholder text for any
                still-empty fields), compiles it with pdflatex, and
                triggers a browser download of the resulting PDF. Shows a
                warning/error notification instead if the title is empty,
                a table component's data is malformed, or the LaTeX
                compile itself fails.
                """
                title = (title_input.value or "").strip()
                if not title:
                    ui.notify("Please fill in the title before previewing.", color="warning")
                    return

                main_text = (main_text_input.value or "").strip()
                module = (module_input.value or "").strip().upper() if module_input.value else ""

                if parts_data:
                    labels = _labels_for(parts_data)
                    try:
                        preview_parts = [
                            _build_part_dict(lbl, p, for_preview=True)
                            for lbl, p in zip(labels, parts_data)
                        ]
                    except ValueError as exc:
                        ui.notify(str(exc), color="negative")
                        return
                    marks = sum(p["Marks"] for p in preview_parts)
                else:
                    preview_parts = []
                    marks = int(marks_input.value or 0)

                question_dict = {
                    "Question": title,
                    "Main question": main_text or None,
                    "Module": module or None,
                }

                # NOTE: this "description" string is baked into the LaTeX
                # source (see latex_export.py's _HEADER), which is compiled
                # with pdflatex -- pdflatex's default fonts have no CJK
                # glyphs at all, so *any* Chinese/Japanese/etc. character
                # reaching build_latex() (in the title, module, question
                # body, or a component's description/answer) makes the
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

                ui.download(pdf_bytes, filename="question_preview.pdf")
                ui.notify("Preview generated -- check your downloaded PDF.", color="positive")

            preview_btn = ui.button("Preview PDF", on_click=on_preview, color="secondary").props("outline")

            def save_question():
                """Validate the form and persist the new question to the database.

                Re-validates the title/answer/component requirements
                (defensively, in addition to the Save button's disabled
                state), builds the component payload, then calls
                database.add_question and, if there are components,
                replace_question_parts, before navigating back to the
                question list. Shows a notification and returns early on
                the first validation failure encountered.
                """
                title = title_input.value.strip()
                module = (module_input.value or "").strip().upper()
                topic = (topic_input.value or "").strip()
                main_text = (main_text_input.value or "").strip()
                answer = answer_input.value.strip()

                if not title:
                    ui.notify("Question title is required.", color="negative")
                    return

                if not parts_data and not answer:
                    ui.notify("Answer is required.", color="negative")
                    return

                # Build the component payload (if any) and work out marks.
                labels = _labels_for(parts_data)
                try:
                    parts_payload = [
                        _build_part_dict(lbl, p, for_preview=False)
                        for lbl, p in zip(labels, parts_data)
                    ]
                except ValueError as exc:
                    ui.notify(str(exc), color="negative")
                    return

                if parts_payload:
                    gradable = [p for p in parts_payload if p["Part type"] in _GRADABLE_TYPES]
                    if not gradable:
                        ui.notify(
                            "Add at least one Text or Table component so the question has marks to grade.",
                            color="negative",
                        )
                        return
                    if any(p["Marks"] <= 0 for p in gradable):
                        ui.notify("Each sub-question must have marks greater than 0.", color="negative")
                        return
                    if any(p["Part type"] == "text" and not p["Answer"] for p in parts_payload):
                        ui.notify("Each sub-question must have a standard answer.", color="negative")
                        return
                    if any(
                        p["Part type"] == "table" and not (p["Table spec"] or {}).get("rows")
                        for p in parts_payload
                    ):
                        ui.notify("Each table sub-question must have at least one row.", color="negative")
                        return
                    if any(p["Part type"] == "material" and not p["Description"] for p in parts_payload):
                        ui.notify("Each material component needs its text filled in.", color="negative")
                        return
                    if any(p["Part type"] == "image" and not p["Image data"] for p in parts_payload):
                        ui.notify("Each image component needs an image uploaded.", color="negative")
                        return
                    marks = sum(p["Marks"] for p in gradable)
                else:
                    marks = marks_input.value
                    if not marks or marks <= 0:
                        ui.notify("Marks must be greater than 0.", color="negative")
                        return

                new_question = {
                    "Question": title,
                    "Main question": main_text or None,
                    "Marks": marks,
                    "Answer": answer or None,
                    "Status": "Draft",
                    "Version": 1,
                    "Created by": username,
                    "Created at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "Usage": 0,
                    "Module": module or None,
                    "Topic": topic or None,
                }

                question_id = add_question(new_question)

                if parts_payload:
                    replace_question_parts(question_id, parts_payload)

                ui.notify(
                    f"Question created successfully! (ID: {question_id})",
                    color="positive"
                )

                ui.navigate.to("/questions")

            with ui.element("div") as save_wrapper:
                save_btn = ui.button("Save", on_click=save_question, color="primary")
            save_tooltip = (
                ui.tooltip("")
                .props(f'target="#{save_wrapper.html_id}"')
                .style("font-size: 14px")
            )

            ui.button("Cancel", on_click=lambda: ui.navigate.to("/questions"))

        # Initial paint: no components yet, so the answer/marks section is
        # visible; Save starts disabled until the required fields above
        # are filled in.
        recalc_total()
        refresh_validation()
