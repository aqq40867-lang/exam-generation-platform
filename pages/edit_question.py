"""NiceGUI page for editing an existing exam question.

Renders the "Edit Question" form for a question, pre-filled from its
existing data. Reuses create_question.py's shared render_question_editor()
-- the same (a)/(b)/(c)... sub-problem editor (with attached images/
tables and nested (i)/(ii)/(iii)... sub-parts) that "Create New Question"
uses -- so this page can now fully round-trip everything that page can
produce, instead of blocking editing whenever a question contained one of
those richer shapes.

Only the handful of legacy, non-gradable component types ("material"/
"image" standalone parts -- see models.py's QuestionPart.part_type) that
predate create_question.py's current sub-problem model are still shown a
read-only notice instead of the edit form: they're unlettered stimulus
content interspersed between lettered sub-problems, a shape the (a)/(b)/
(c)... editor has no way to represent, so editing here would silently
drop them.
"""

from nicegui import ui, app
from database import (
    get_question,
    update_question,
    load_questions,
    get_question_parts,
    replace_question_parts,
    get_teacher_modules,
    list_teacher_topics,
    add_teacher_topic,
)
from pages.create_question import render_question_editor
from datetime import datetime


def _hydrate_block(block: dict) -> dict:
    """Convert one stored content block into the editor's live block shape.

    get_question_parts() returns each "table" block with its problem
    table nested under "table_spec" (see models.py's
    QuestionPart.content_blocks); create_question.py's
    _render_block_editor instead expects a table block with those
    columns/rows flattened directly onto the block dict ("given_columns",
    "answer_columns", "rows") so its handlers can mutate them in place.
    "text" and "image" blocks already match shape as-is. A legacy row may
    still carry an old "answer_table_spec" (and "answer_text_before"/
    "answer_text_after") from before the table-answer grid was removed --
    those are simply dropped here; the table's standard answer now lives
    entirely in its owning sub-problem's own free-text "Answer" field
    (see _hydrate_part below).

    Args:
        block: One block dict as returned in a part's "Content blocks"
            list.

    Returns:
        The equivalent block dict in the shape create_question.py's
        block editor expects.
    """
    btype = block.get("type")

    if btype == "table":
        spec = block.get("table_spec") or {}
        return {
            "type": "table",
            "given_columns": list(spec.get("given_columns") or []),
            "answer_columns": list(spec.get("answer_columns") or []),
            "rows": [list(r) for r in (spec.get("rows") or [])],
        }

    if btype == "image":
        return {
            "type": "image",
            "image_data": block.get("image_data"),
            "image_filename": block.get("image_filename"),
        }

    # "text" (and defensively, anything unrecognised -- treated as an
    # empty text block rather than crashing the page).
    return {"type": "text", "text": block.get("text") or ""}


def _hydrate_blocks(content_blocks) -> list:
    """Convert a stored "Content blocks" list into the editor's live shape.

    Always returns at least one block -- a single empty text block if
    `content_blocks` is empty -- matching create_question.py's own
    convention that a sub-problem/sub-part never starts with a
    completely empty block list.

    Args:
        content_blocks: The raw "Content blocks" list from
            get_question_parts() (possibly empty/None).

    Returns:
        A list of block dicts in the editor's live shape.
    """
    blocks = [_hydrate_block(b) for b in (content_blocks or [])]
    return blocks or [{"type": "text", "text": ""}]


def _hydrate_sub_part(sub_part: dict) -> dict:
    """Convert one stored sub-part (the (i)/(ii)/(iii)... level) into the editor's live shape.

    Args:
        sub_part: One entry from a part's "Sub parts" list (see
            models.py's QuestionPart.sub_parts for the shape -- the same
            dict shape create_question.py's _build_part_dict() produces
            for any part, minus its own further "Sub parts").

    Returns:
        A dict with "marks", "answer", "answer_space", and "blocks",
        matching a sub-part entry in parts_data[i]["subparts"].
    """
    answer_space = sub_part.get("Answer space")
    return {
        "marks": int(sub_part.get("Marks") or 0),
        "answer": sub_part.get("Answer") or "",
        "answer_space": answer_space if answer_space in ("half", "full") else "half",
        "blocks": _hydrate_blocks(sub_part.get("Content blocks")),
    }


def _hydrate_main_blocks(question: dict) -> list:
    """Convert a question's stored problem statement into the editor's live block shape.

    get_question() already decodes "Main content blocks" from JSON (or,
    for a row saved before that column existed, synthesizes a single
    text block from the legacy flat "Main question" field -- see
    database.py's _decode_main_blocks), so this just needs to run each
    block through _hydrate_block() the same way a sub-problem's own
    blocks are. Unlike a sub-problem, an empty result stays an empty
    list rather than being padded to one placeholder block -- the
    overall problem statement is optional.

    Args:
        question: A question dict from get_question(), with "Main
            content blocks" already decoded to a list.

    Returns:
        A list of block dicts in the editor's live shape (possibly
        empty).
    """
    return [_hydrate_block(b) for b in (question.get("Main content blocks") or [])]


def _hydrate_part(part: dict) -> dict:
    """Convert one get_question_parts() row into a parts_data entry.

    Args:
        part: One dict from get_question_parts(question_id) -- a
            lettered (a)/(b)/(c)... sub-problem, with "Content blocks"
            and "Sub parts" already decoded from JSON.

    Returns:
        A dict with "marks", "answer", "answer_space", "_expanded",
        "blocks", and "subparts", matching render_question_editor()'s
        expected parts_data entry shape.
    """
    answer_space = part.get("Answer space")
    return {
        "marks": int(part.get("Marks") or 0),
        "answer": part.get("Answer") or "",
        "answer_space": answer_space if answer_space in ("half", "full") else "half",
        "_expanded": False,
        "blocks": _hydrate_blocks(part.get("Content blocks")),
        "subparts": [_hydrate_sub_part(sp) for sp in (part.get("Sub parts") or [])],
    }


def edit_question_page(question_id: int):
    """Render the edit form for an existing question, or a block-edit notice.

    Verifies the caller is logged in and is the question's creator, then
    either renders the shared sub-problem editor (see
    create_question.render_question_editor), pre-filled from the
    question's existing data, or -- only if the question contains a
    legacy non-gradable "material"/"image" standalone part, a shape the
    editor has no way to represent -- a read-only explanation instead, so
    saving can't silently discard that content.

    Args:
        question_id: Database id of the question to edit.
    """

    # Check login
    if not app.storage.user.get("logged_in"):
        ui.navigate.to("/login")
        return

    # Get question data
    question = get_question(question_id)

    if not question:
        ui.notify("Question not found.", color="negative")
        ui.navigate.to("/questions")
        return

    username = app.storage.user["username"]

    # Only the creator can edit this question
    if question.get("Created by") != username:
        ui.notify("You do not have permission to edit this question.", color="negative")
        ui.navigate.to("/questions")
        return

    # Work out this question's per-user display number (1, 2, 3... per creator),
    # independent of the real database id used in the URL
    user_questions = sorted(
        (q for q in load_questions() if q.get("Created by") == username),
        key=lambda q: q["id"]
    )
    user_question_ids = [q["id"] for q in user_questions]
    display_id = user_question_ids.index(question_id) + 1 if question_id in user_question_ids else question_id

    existing_parts = get_question_parts(question_id)

    # Every part shape create_question.py's editor can itself produce --
    # an attached image, a table, multiple/reordered content blocks, and
    # nested (i)/(ii)/(iii)... sub-parts -- is now fully editable via
    # render_question_editor() below (see _hydrate_part()/_hydrate_block()
    # above). Only the legacy, non-gradable "material" (stimulus text)
    # and "image" (standalone image) part types -- unlettered rows that
    # can be interspersed between lettered sub-problems -- predate that
    # model and have no equivalent in it, so editing here would silently
    # drop them; block editing for those, same as before.
    unsupported_types = sorted({
        (p.get("Part type") or "text") for p in existing_parts
        if (p.get("Part type") or "text") in ("material", "image")
    })
    if unsupported_types:
        with ui.column().classes("w-full max-w-2xl mx-auto p-8 gap-3"):
            ui.label(f"Edit Question #{display_id}").classes("text-3xl font-bold mb-2")
            with ui.card().classes("w-full p-6 bg-orange-50"):
                ui.label("This question can't be edited here yet.").classes("text-lg font-bold")
                ui.label(
                    f"It contains something this editor doesn't support yet "
                    f"({', '.join(unsupported_types)} content). Editing it here "
                    f"would silently discard that data on save, so editing has "
                    f"been disabled for this question instead."
                ).classes("text-sm text-grey-700 mt-1")
            with ui.row().classes("gap-4"):
                ui.button("Back to List", on_click=lambda: ui.navigate.to("/questions"))
                ui.button(
                    "View Question",
                    on_click=lambda: ui.navigate.to(f"/questions/{question_id}"),
                    color="primary",
                )
        return

    parts_data = [_hydrate_part(p) for p in existing_parts]

    assigned_modules = get_teacher_modules(username)
    existing_topics = list_teacher_topics(username)

    def on_save(payload):
        """Persist the edited question from the validated form payload.

        Builds the updated question row (preserving fields the form
        doesn't touch -- Status, Created by/at, Usage -- and bumping
        Version), saves it via database.update_question, then replaces
        every sub-question row via replace_question_parts (an empty list
        if the question no longer has any), before notifying the user
        and navigating back to the question list.
        """
        updated_question = {
            "Question": payload["title"],
            "Main question": payload["main_text"] or None,
            "Main content blocks": payload["main_content_blocks"] or None,
            "Marks": payload["marks"],
            "Answer": payload["answer"] or None,
            "Status": question.get("Status", "Draft"),
            "Version": question.get("Version", 1) + 1,
            "Created by": question.get("Created by", username),
            "Created at": question.get("Created at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            "Updated at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Usage": question.get("Usage", 0),
            "Module": payload["module"] or None,
            "Topic": payload["topic"] or None,
        }

        success = update_question(question_id, updated_question)

        # Sync sub-questions (replaces old ones, re-sums Marks; if the
        # list is now empty, the manually-entered Marks value above is
        # kept as-is).
        replace_question_parts(question_id, payload["parts_payload"] or [])

        if payload["topic"]:
            add_teacher_topic(username, payload["topic"])

        if success:
            ui.notify("Question updated successfully!", color="positive")
            ui.navigate.to("/questions")
        else:
            ui.notify("Failed to update question.", color="negative")

    render_question_editor(
        page_heading=f"Edit Question #{display_id}",
        save_button_label="Save Changes",
        assigned_modules=assigned_modules,
        existing_topics=existing_topics,
        initial={
            "title": question.get("Question", ""),
            "module": question.get("Module") or "",
            "topic": question.get("Topic") or "",
            "main_blocks": _hydrate_main_blocks(question),
            "marks": question.get("Marks") or 1,
            "answer": question.get("Answer") or "",
            "parts_data": parts_data,
        },
        meta_lines=[
            f"Status: {question.get('Status', 'Unknown')}",
            f"Version: {question.get('Version', 1)}",
        ],
        extra_actions=[
            ("View Question", lambda: ui.navigate.to(f"/questions/{question_id}")),
        ],
        on_save=on_save,
    )
