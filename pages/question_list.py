"""NiceGUI page listing the current teacher's own questions.

Shows a filterable/sortable table of the signed-in user's questions,
with a module sidebar, per-row View/Edit/Delete actions, and buttons for
creating a new question, exporting an exam paper, and (for admins)
managing users.
"""

from collections import Counter

from nicegui import ui, app
from database import load_questions, delete_question, get_teacher_modules, get_user_by_username


def question_list_page():
    """Render the question list page.

    Redirects to the login page if the user isn't signed in. Only shows
    questions created by the current user, numbered per-user (1, 2, 3...)
    independently of the underlying database id.
    """

    # Check login
    if not app.storage.user.get("logged_in"):
        ui.navigate.to("/login")
        return

    username = app.storage.user["username"]

    # Re-verify the role fresh from the database rather than trusting the
    # "role" cached in session storage at login time -- see the matching
    # note in admin_users.py. Keeps the "User Management" button's
    # visibility (and the "Role:" label below) honest even if this
    # account's role changed after the current session started, instead
    # of only catching up the next time this user logs back in.
    current_user = get_user_by_username(username)
    role = current_user.get("Role") if current_user else app.storage.user.get("role", "teacher")
    app.storage.user["role"] = role

    ui.label(f"Welcome, {username}").classes("text-2xl font-bold")
    # Read-only: a teacher can see what their own role is, but there's no
    # control here to change it -- only an admin can do that, from the User
    # Management page.
    ui.label(f"Role: {role}").classes("text-sm text-grey-600 mb-2")

    with ui.row():

        ui.button(
            "Create New Question",
            on_click=lambda: ui.navigate.to("/questions/new")
        )

        ui.button(
            "Export Exam Paper",
            on_click=lambda: ui.navigate.to("/exams/export"),
            color="secondary"
        )

        if role == "admin":
            ui.button(
                "User Management",
                on_click=lambda: ui.navigate.to("/admin/users"),
                color="secondary"
            )

        def logout():
            """Clear the session and return the user to the login page."""
            app.storage.user.clear()
            ui.navigate.to("/login")

        ui.button(
            "Logout",
            on_click=logout,
            color="red"
        )

    ui.separator()

    # Only show questions created by the current user
    all_questions = load_questions()
    questions = [q for q in all_questions if q.get("Created by") == username]

    # Sort by real id so the per-user display numbering is stable/consistent
    questions.sort(key=lambda q: q["id"])

    # Assign a display number that starts at 1 for each user, independent
    # of the real (globally unique) database id used for navigation/actions
    for display_id, q in enumerate(questions, start=1):
        q["display_id"] = display_id

    columns = [
        {"name": "display_id", "label": "ID", "field": "display_id"},
        {"name": "Question", "label": "Question", "field": "Question"},
        {"name": "Topic", "label": "Topic", "field": "Topic", "align": "center"},
        {"name": "Module", "label": "Module", "field": "Module", "align": "center"},
        {"name": "Status", "label": "Status", "field": "Status"},
        {"name": "Version", "label": "Version", "field": "Version"},
        {"name": "Created by", "label": "Created By", "field": "Created by"},
        {"name": "Marks", "label": "Marks", "field": "Marks"},
        {"name": "Usage", "label": "Usage", "field": "Usage"},
        {"name": "actions", "label": "Actions", "field": "actions"},
    ]

    # Give every column an equal share of the table width (ID, Question,
    # Module, Status, Version, Created By, Marks, Usage, Actions), so the
    # header row is evenly split rather than sized purely by content.
    equal_width = f"{100 / len(columns):.4f}%"
    for col in columns:
        col["style"] = f"width: {equal_width}"
        col["headerStyle"] = f"width: {equal_width}"

    all_rows = []

    for q in questions:
        all_rows.append({
            "id": q["id"],  # real id, used internally for navigation
            "display_id": q["display_id"],
            "Question": q["Question"],
            "Topic": q.get("Topic") or "—",
            "Module": q.get("Module") or "—",
            "Status": q["Status"],
            "Version": q["Version"],
            "Created by": q["Created by"],
            "Marks": q["Marks"],
            "Usage": q["Usage"],
        })

    # Module filter: a left sidebar listing every module this teacher is
    # assigned to (plus any module already used on one of their questions,
    # even if it's since been unassigned -- same "don't hide existing data"
    # principle used on the create/edit question forms), each annotated
    # with how many of their questions are in it. Clicking a module filters
    # the table down to just that module; "All Questions" clears the filter.
    module_counts = Counter(r["Module"] for r in all_rows if r["Module"] != "—")
    sidebar_modules = sorted(
        set(get_teacher_modules(username)) | set(module_counts.keys()),
        key=str.lower,
    )

    table = ui.table(
        columns=columns,
        rows=list(all_rows),
        row_key="id",
        selection="multiple",
    ).classes("w-full")

    # table-layout: fixed makes every column actually honour the equal
    # "width" percentages set above, instead of auto-sizing to content.
    table.props('table-style="table-layout: fixed; width: 100%"')

    # -- Exam question selection ------------------------------------------
    # A teacher builds an exam by ticking questions here (checkbox column,
    # added automatically by selection="multiple"), then clicking "Export
    # Exam Paper" to hand the selection off to /exams/export, which lets
    # them reorder/remove/mark up the picks and generate the PDF. The
    # selection itself lives in app.storage.user (keyed "exam_selection",
    # an ordered list of question ids) so it survives navigating away from
    # this page -- e.g. opening a question's detail view mid-pick -- and
    # persists until the teacher clears it or generates an exam.
    selected_ids = set(app.storage.user.get("exam_selection", []))
    table.selected = [r for r in all_rows if r["id"] in selected_ids]

    def on_select(e):
        """Persist the current tick-box selection, preserving pick order.

        Keeps whatever relative order previously-selected ids already had
        in storage, and appends newly-ticked ids at the end -- so the
        export page's initial question order matches the order they were
        ticked in, before any manual drag-reordering there.
        """
        current_ids = {row["id"] for row in e.selection}
        previous_order = app.storage.user.get("exam_selection", [])
        new_order = [qid for qid in previous_order if qid in current_ids]
        new_order += [qid for qid in current_ids if qid not in previous_order]
        app.storage.user["exam_selection"] = new_order

    table.on_select(on_select)

    with ui.left_drawer(value=True, bordered=True).classes("bg-grey-1"):
        ui.label("MODULES").classes(
            "text-xs font-bold text-grey-600 tracking-wide px-3 pt-3 pb-1"
        )

        sidebar_items = {}  # module code (or None for "All") -> ui.item element

        def set_active(selected_code):
            """Highlight the selected module in the sidebar list.

            Args:
                selected_code: The module code that should appear active,
                    or None for the "All Questions" item.
            """
            for code, item in sidebar_items.items():
                if code == selected_code:
                    item.classes(add="bg-primary text-white", remove="text-grey-9")
                else:
                    item.classes(remove="bg-primary text-white", add="text-grey-9")

        def select_module(code):
            """Filter the table to a module and mark it active in the sidebar.

            Args:
                code: The module code to filter to, or None to show every
                    question ("All Questions").
            """
            set_active(code)
            if code is None:
                table.rows = list(all_rows)
            else:
                table.rows = [r for r in all_rows if r["Module"] == code]
            table.update()

        with ui.list().props("dense separator").classes("px-1"):
            sidebar_items[None] = ui.item(
                f"All Questions ({len(all_rows)})",
                on_click=lambda: select_module(None),
            ).classes("rounded-borders cursor-pointer")

            for code in sidebar_modules:
                sidebar_items[code] = ui.item(
                    f"{code} ({module_counts.get(code, 0)})",
                    on_click=lambda code=code: select_module(code),
                ).classes("rounded-borders cursor-pointer")

        # If we got here via a module card on the Module Selection page,
        # that page left its pick in session storage -- consume it as a
        # one-shot initial filter (popped, not left sticky, so a plain
        # revisit to this page later still starts on "All Questions").
        # Falls back to "All Questions" if the stashed module no longer
        # appears in this teacher's sidebar (e.g. it was unassigned in
        # between).
        pending_filter = app.storage.user.pop("module_filter", None)
        if pending_filter not in sidebar_modules:
            pending_filter = None
        select_module(pending_filter)

    # Custom "Actions" cell: a dropdown (kebab) menu with View / Edit / Delete
    table.add_slot("body-cell-actions", r"""
        <q-td :props="props" auto-width>
            <q-btn flat dense round icon="more_vert">
                <q-menu auto-close>
                    <q-list style="min-width: 120px">
                        <q-item clickable @click="$parent.$emit('view', props.row)">
                            <q-item-section avatar>
                                <q-icon name="visibility" />
                            </q-item-section>
                            <q-item-section>View</q-item-section>
                        </q-item>
                        <q-item clickable @click="$parent.$emit('edit', props.row)">
                            <q-item-section avatar>
                                <q-icon name="edit" />
                            </q-item-section>
                            <q-item-section>Edit</q-item-section>
                        </q-item>
                        <q-item clickable @click="$parent.$emit('delete', props.row)">
                            <q-item-section avatar>
                                <q-icon name="delete" color="red" />
                            </q-item-section>
                            <q-item-section class="text-red">Delete</q-item-section>
                        </q-item>
                    </q-list>
                </q-menu>
            </q-btn>
        </q-td>
    """)

    # Custom "Topic" cell: rendered as a chip rather than plain text, so it
    # reads as metadata at a glance instead of another text column -- a
    # question titled e.g. "Definitions" otherwise gives no hint what it's
    # actually about until you open it.
    table.add_slot("body-cell-Topic", r"""
        <q-td :props="props">
            <q-chip v-if="props.value && props.value !== '—'"
                    dense square color="blue-1" text-color="blue-9"
                    :label="props.value" />
            <span v-else class="text-grey-5">—</span>
        </q-td>
    """)

    def open_question(e):
        """Navigate to a question's detail page on row double-click.

        Args:
            e: The NiceGUI table event; `e.args["id"]` is the row's
                question id.
        """
        ui.navigate.to(f'/questions/{e.args["id"]}')

    table.on("rowDblClick", open_question)

    # Dropdown menu actions
    def view_question(e):
        """Navigate to a question's detail page (View menu action).

        Args:
            e: The NiceGUI menu event; `e.args["id"]` is the row's
                question id.
        """
        ui.navigate.to(f'/questions/{e.args["id"]}')

    def edit_question(e):
        """Navigate to a question's edit page (Edit menu action).

        Args:
            e: The NiceGUI menu event; `e.args["id"]` is the row's
                question id.
        """
        ui.navigate.to(f'/questions/{e.args["id"]}/edit')

    def delete_question_prompt(e):
        """Show a confirmation dialog before deleting a question.

        Args:
            e: The NiceGUI menu event; `e.args["id"]` is the row's
                question id and `e.args["display_id"]` is its per-user
                display number shown in the confirmation text.
        """
        qid = e.args["id"]
        display_id = e.args["display_id"]

        with ui.dialog() as dialog, ui.card():
            ui.label(f"Delete question #{display_id}?")
            ui.label("This action cannot be undone.").classes("text-sm text-grey-600")

            with ui.row().classes("gap-4 mt-4"):
                ui.button("Cancel", on_click=dialog.close)

                def confirm():
                    """Delete the question and close the confirmation dialog."""
                    delete_question(qid)
                    dialog.close()
                    ui.navigate.to("/questions")

                ui.button("Delete", color="red", on_click=confirm)

        dialog.open()

    table.on("view", view_question)
    table.on("edit", edit_question)
    table.on("delete", delete_question_prompt)