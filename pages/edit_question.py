from nicegui import ui, app
from database import (
    get_question,
    update_question,
    load_questions,
    get_question_parts,
    replace_question_parts,
    get_teacher_modules,
    list_topics,
)
from datetime import datetime
import string


def _label_for_index(index: int) -> str:
    """UK-style lower-case sub-question label: 0 -> 'a', 1 -> 'b', ..."""
    letters = string.ascii_lowercase
    label = ""
    index += 1
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        label = letters[remainder] + label
    return label


def edit_question_page(question_id: int):
    """Edit existing question page."""

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

    # This form only understands plain "text" sub-questions -- it predates
    # "table"/"material"/"image" components (see create_question.py) and
    # was never updated to build/display them. If it read a component of
    # one of those types into the same plain
    # {description, marks, answer, answer_space} shape used below and the
    # user hit Save, replace_question_parts() would overwrite the real
    # question_parts rows with what this form built -- silently discarding
    # the table's rows / material's text / image's data for good, with no
    # warning. Rather than risk that, editing is blocked entirely (with an
    # explanation) whenever any component isn't a plain "text" one.
    unsupported_types = sorted({
        (p.get("Part type") or "text") for p in existing_parts
        if (p.get("Part type") or "text") != "text"
    })
    if unsupported_types:
        with ui.column().classes("w-full max-w-2xl mx-auto p-8 gap-3"):
            ui.label(f"Edit Question #{display_id}").classes("text-3xl font-bold mb-2")
            with ui.card().classes("w-full p-6 bg-orange-50"):
                ui.label("This question can't be edited here yet.").classes("text-lg font-bold")
                ui.label(
                    f"It contains a component type this editor doesn't support yet "
                    f"({', '.join(unsupported_types)}). Editing it here would silently "
                    f"discard that component's data on save, so editing has been "
                    f"disabled for this question instead."
                ).classes("text-sm text-grey-700 mt-1")
            with ui.row().classes("gap-4"):
                ui.button("Back to List", on_click=lambda: ui.navigate.to("/questions"))
                ui.button(
                    "View Question",
                    on_click=lambda: ui.navigate.to(f"/questions/{question_id}"),
                    color="primary",
                )
        return

    # Load existing sub-questions (if any) into the same in-memory shape
    # used by the create page: a list of {"description": str, "marks": number,
    # "answer": str, "answer_space": number}
    def _normalize_answer_space(value):
        """Older rows (or legacy data) may not have a valid 'half'/'full'
        value yet; fall back to 'half' in that case."""
        return value if value in ("half", "full") else "half"

    parts_data = [
        {
            "description": p.get("Description") or "",
            "marks": p.get("Marks") or 0,
            "answer": p.get("Answer") or "",
            "answer_space": _normalize_answer_space(p.get("Answer space")),
        }
        for p in existing_parts
    ]

    with ui.column().classes("w-full max-w-4xl mx-auto p-8"):

        # Header
        ui.label(f"Edit Question #{display_id}").classes("text-3xl font-bold mb-6")

        # Form
        with ui.card().classes("w-full p-6"):

            # Question title
            ui.label("Question Title").classes("font-semibold")
            title_input = ui.input(
                value=question.get("Question", ""),
                placeholder="Enter question title"
            ).classes("w-full mb-4")

            # Module (course module association, e.g. "CO923"). Restricted to
            # whatever courses this teacher has been assigned by an admin --
            # teachers cannot type their own module code here.
            ui.label("Module").classes("font-semibold")
            assigned_modules = get_teacher_modules(username)
            existing_module = question.get("Module") or ""
            # Keep the question's current module selectable even if it's no
            # longer (or never was) part of this teacher's assigned list,
            # so editing the question doesn't silently wipe out its module.
            module_options = list(assigned_modules)
            if existing_module and existing_module not in module_options:
                module_options.append(existing_module)

            if module_options:
                module_input = ui.select(
                    module_options,
                    value=existing_module or None,
                    label="",
                ).classes("w-full mb-1")
            else:
                module_input = ui.select(
                    [],
                    label="",
                ).classes("w-full mb-1").props("disable")
                ui.label(
                    "You have no modules assigned yet. Contact your admin to "
                    "get modules assigned to you before selecting one here."
                ).classes("text-sm text-negative mb-3")

            # Topic / knowledge point (free text, optional) -- separate from
            # the title, since the title alone often doesn't say what the
            # question is actually about (e.g. a title of "Definitions"
            # gives no hint that it covers stacks). Shown as a chip in the
            # question list/detail pages.
            ui.label("Topic / Knowledge Point").classes("font-semibold")
            topic_input = ui.input(
                value=question.get("Topic", ""),
                placeholder='e.g. "Stacks", "Kruskal\'s Algorithm", "Binary Search Trees" (optional)',
                autocomplete=list_topics(username),
            ).classes("w-full mb-4")

            # Optional description / shared context for the main question
            ui.label("Description (optional)").classes("font-semibold")
            main_text_input = ui.textarea(
                value=question.get("Main question", ""),
                placeholder="Optional description or shared context for this question (leave blank if none)"
            ).classes("w-full mb-4").props("rows=4")

            ui.separator().classes("my-2")

            # Sub-questions (子小题). Each major question (大题) can be
            # broken down into multiple sub-questions (子小题); each
            # sub-question carries its own standard answer and a reserved
            # blank-answer area on the exported paper.
            ui.label("Sub-questions").classes("font-semibold")
            ui.label(
                "Break this question down into sub-questions (a), (b), (c)... "
                "Each sub-question should have its own standard answer and a "
                "reserved blank area for the student to write their answer."
            ).classes("text-sm text-grey-600 mb-1")

            parts_container = ui.column().classes("w-full gap-2")

            def recalc_total():
                total = sum((p.get("marks") or 0) for p in parts_data)
                if parts_data:
                    marks_input.value = total
                    marks_input.disable()
                    total_label.text = f"Total marks (auto-calculated from {len(parts_data)} sub-question(s)): {total}"
                    answer_section.set_visibility(False)
                else:
                    marks_input.enable()
                    total_label.text = ""
                    answer_section.set_visibility(True)

            def render_parts():
                parts_container.clear()
                with parts_container:
                    for i, part in enumerate(parts_data):

                        def make_desc_handler(idx):
                            def handler(e):
                                parts_data[idx]["description"] = e.value

                            return handler

                        def make_marks_handler(idx):
                            def handler(e):
                                parts_data[idx]["marks"] = e.value or 0
                                recalc_total()

                            return handler

                        def make_answer_handler(idx):
                            def handler(e):
                                parts_data[idx]["answer"] = e.value

                            return handler

                        def make_answer_space_handler(idx):
                            def handler(e):
                                parts_data[idx]["answer_space"] = e.value or "half"

                            return handler

                        def make_remove_handler(idx):
                            def handler():
                                parts_data.pop(idx)
                                render_parts()
                                recalc_total()

                            return handler

                        with ui.card().classes("w-full border pb-2").props("flat bordered"):
                            with ui.row().classes("w-full items-start gap-2"):
                                ui.label(f"({_label_for_index(i)})").classes("font-semibold w-10 pt-3")
                                ui.textarea(
                                    placeholder="Sub-question text (optional)",
                                    value=part.get("description", ""),
                                    on_change=make_desc_handler(i),
                                ).classes("flex-grow").props("rows=2")
                                ui.number(
                                    label="Marks",
                                    min=0,
                                    step=1,
                                    value=part.get("marks", 0),
                                    on_change=make_marks_handler(i),
                                ).classes("w-28")
                                ui.button(
                                    icon="delete",
                                    color="red",
                                    on_click=make_remove_handler(i),
                                ).props("flat dense round")

                            with ui.row().classes("w-full items-start gap-2 pl-12"):
                                ui.textarea(
                                    label="Standard answer",
                                    placeholder="Standard answer for this sub-question",
                                    value=part.get("answer", ""),
                                    on_change=make_answer_handler(i),
                                ).classes("flex-grow").props("rows=2")
                                ui.select(
                                    {"half": "Half page", "full": "Full page (new page)"},
                                    label="Reserved answer space",
                                    value=part.get("answer_space", "half"),
                                    on_change=make_answer_space_handler(i),
                                ).classes("w-56")

            def add_part():
                parts_data.append({
                    "description": "",
                    "marks": 0,
                    "answer": "",
                    "answer_space": "half",
                })
                render_parts()
                recalc_total()

            ui.button("+ Add sub-question", on_click=add_part, color="secondary").classes("mt-2")

            total_label = ui.label("").classes("text-sm font-semibold mt-2")

            # Marks (manual entry; auto-calculated and locked once
            # sub-questions are added)
            ui.label("Marks").classes("font-semibold mt-4")
            marks_input = ui.number(
                label="",
                value=question.get("Marks", 1),
                min=1,
                step=1
            ).classes("w-full mb-4")

            # Answer (overall answer/marking notes for the question). This
            # only applies to a plain question with no sub-questions: once
            # sub-questions are added, the answer "lives" with each
            # sub-question instead (see "Standard answer" above), so this
            # section is hidden.
            with ui.column().classes("w-full gap-0") as answer_section:
                ui.label("Answer").classes("font-semibold")
                answer_input = ui.textarea(
                    value=question.get("Answer", ""),
                    placeholder="Enter the answer"
                ).classes("w-full mb-4").props("rows=3")

            # Render any pre-existing sub-questions and lock/compute Marks
            # (and hide the overall Answer section) if there are any
            render_parts()
            recalc_total()

            # Status (read-only display)
            ui.label(f"Status: {question.get('Status', 'Unknown')}").classes("text-sm text-grey-600 mb-4")

            # Version (read-only display)
            ui.label(f"Version: {question.get('Version', 1)}").classes("text-sm text-grey-600 mb-4")

            # Buttons
            with ui.row().classes("gap-4 mt-2"):

                def save_changes():
                    """Save the updated question."""

                    title = (title_input.value or "").strip()
                    module = (module_input.value or "").strip().upper()
                    topic = (topic_input.value or "").strip()
                    main_text = (main_text_input.value or "").strip()
                    # answer_input's initial value is question.get("Answer", "")
                    # -- which is None (not "") whenever the question has
                    # sub-questions, since the parent's own "Answer" column is
                    # unused in that case. The field stays hidden but still
                    # exists in the DOM, so .value is still read here every
                    # time Save is clicked, even for questions with parts --
                    # without this guard, editing *any* question that has
                    # sub-questions crashed this whole handler on this line
                    # (silently, since NiceGUI just logs synchronous handler
                    # exceptions server-side -- Save looked like it did
                    # nothing at all).
                    answer = (answer_input.value or "").strip()

                    # Validate inputs
                    if not title:
                        ui.notify("Question title is required.", color="negative")
                        return

                    if not parts_data and not answer:
                        ui.notify("Answer is required.", color="negative")
                        return

                    # Build sub-question payload (if any) and work out marks.
                    # Each sub-question carries its own standard answer and a
                    # reserved answer space ('half' or 'full' page).
                    parts_payload = [
                        {
                            "Description": (p.get("description") or "").strip() or None,
                            "Marks": int(p.get("marks") or 0),
                            "Answer": (p.get("answer") or "").strip() or None,
                            "Answer space": p.get("answer_space") if p.get("answer_space") in ("half", "full") else "half",
                        }
                        for p in parts_data
                    ]

                    if parts_payload:
                        if any(p["Marks"] <= 0 for p in parts_payload):
                            ui.notify("Each sub-question must have marks greater than 0.", color="negative")
                            return
                        if any(not p["Answer"] for p in parts_payload):
                            ui.notify("Each sub-question must have a standard answer.", color="negative")
                            return
                        marks = sum(p["Marks"] for p in parts_payload)
                    else:
                        marks = marks_input.value
                        if not marks or marks <= 0:
                            ui.notify("Marks must be greater than 0.", color="negative")
                            return

                    # Create updated question object (preserve existing fields)
                    updated_question = {
                        "Question": title,
                        "Main question": main_text or None,
                        "Marks": marks,
                        "Answer": answer or None,
                        "Status": question.get("Status", "Draft"),
                        "Version": question.get("Version", 1) + 1,  # Increment version
                        "Created by": question.get("Created by", username),
                        "Created at": question.get("Created at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                        "Updated at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "Usage": question.get("Usage", 0),
                        "Module": module or None,
                        "Topic": topic or None,
                    }

                    # Update in database
                    success = update_question(question_id, updated_question)

                    # Sync sub-questions (replaces old ones, re-sums Marks;
                    # if the list is now empty, the manually-entered Marks
                    # value above is kept as-is)
                    if parts_payload:
                        replace_question_parts(question_id, parts_payload)
                    else:
                        replace_question_parts(question_id, [])

                    if success:
                        ui.notify(
                            "Question updated successfully!",
                            color="positive"
                        )
                        ui.navigate.to("/questions")
                    else:
                        ui.notify(
                            "Failed to update question.",
                            color="negative"
                        )

                ui.button(
                    "Save Changes",
                    on_click=save_changes,
                    color="primary"
                )

                ui.button(
                    "Cancel",
                    on_click=lambda: ui.navigate.to("/questions")
                )

                ui.button(
                    "View Question",
                    on_click=lambda: ui.navigate.to(f"/questions/{question_id}")
                )
