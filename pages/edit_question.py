from nicegui import ui, app
from database import (
    get_question,
    update_question,
    load_questions,
    get_question_parts,
    replace_question_parts,
    list_modules,
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

    # Load existing sub-questions (if any) into the same in-memory shape
    # used by the create page: a list of {"description": str, "marks": number}
    parts_data = [
        {"description": p.get("Description") or "", "marks": p.get("Marks") or 0}
        for p in get_question_parts(question_id)
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

            # Module (course module association, e.g. "CO923")
            ui.label("Module").classes("font-semibold")
            module_input = ui.input(
                value=question.get("Module") or "",
                placeholder="e.g. CO923",
                autocomplete=list_modules(),
            ).classes("w-full mb-4")

            # Optional description / shared context for the main question
            ui.label("Description (optional)").classes("font-semibold")
            main_text_input = ui.textarea(
                value=question.get("Main question", ""),
                placeholder="Optional description or shared context for this question (leave blank if none)"
            ).classes("w-full mb-4").props("rows=4")

            ui.separator().classes("my-2")

            # Sub-questions (子问题)
            ui.label("Sub-questions").classes("font-semibold")

            parts_container = ui.column().classes("w-full gap-2")

            def recalc_total():
                total = sum((p.get("marks") or 0) for p in parts_data)
                if parts_data:
                    marks_input.value = total
                    marks_input.disable()
                    total_label.text = f"Total marks (auto-calculated from {len(parts_data)} sub-question(s)): {total}"
                else:
                    marks_input.enable()
                    total_label.text = ""

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

                        def make_remove_handler(idx):
                            def handler():
                                parts_data.pop(idx)
                                render_parts()
                                recalc_total()

                            return handler

                        with ui.row().classes("w-full items-start gap-2 border-b pb-2"):
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

            def add_part():
                parts_data.append({"description": "", "marks": 0})
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

            # Render any pre-existing sub-questions and lock/compute Marks
            # if there are any
            render_parts()
            recalc_total()

            # Answer
            ui.label("Answer").classes("font-semibold")
            answer_input = ui.textarea(
                value=question.get("Answer", ""),
                placeholder="Enter the answer"
            ).classes("w-full mb-4").props("rows=3")

            # Status (read-only display)
            ui.label(f"Status: {question.get('Status', 'Unknown')}").classes("text-sm text-grey-600 mb-4")

            # Version (read-only display)
            ui.label(f"Version: {question.get('Version', 1)}").classes("text-sm text-grey-600 mb-4")

            # Buttons
            with ui.row().classes("gap-4 mt-2"):

                def save_changes():
                    """Save the updated question."""

                    title = title_input.value.strip()
                    module = (module_input.value or "").strip()
                    main_text = (main_text_input.value or "").strip()
                    answer = answer_input.value.strip()

                    # Validate inputs
                    if not title:
                        ui.notify("Question title is required.", color="negative")
                        return

                    if not answer:
                        ui.notify("Answer is required.", color="negative")
                        return

                    # Build sub-question payload (if any) and work out marks
                    parts_payload = [
                        {
                            "Description": (p.get("description") or "").strip() or None,
                            "Marks": int(p.get("marks") or 0),
                            "Answer": None,
                        }
                        for p in parts_data
                    ]

                    if parts_payload:
                        if any(p["Marks"] <= 0 for p in parts_payload):
                            ui.notify("Each sub-question must have marks greater than 0.", color="negative")
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
                        "Answer": answer,
                        "Status": question.get("Status", "Draft"),
                        "Version": question.get("Version", 1) + 1,  # Increment version
                        "Created by": question.get("Created by", username),
                        "Created at": question.get("Created at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                        "Updated at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "Usage": question.get("Usage", 0),
                        "Module": module or None,
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
