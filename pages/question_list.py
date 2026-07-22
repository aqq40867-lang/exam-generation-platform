from nicegui import ui, app
from database import load_questions, delete_question


def question_list_page():

    # Check login
    if not app.storage.user.get("logged_in"):
        ui.navigate.to("/login")
        return

    username = app.storage.user["username"]

    ui.label(f"Welcome, {username}").classes("text-2xl font-bold")

    with ui.row():

        ui.button(
            "Create New Question",
            on_click=lambda: ui.navigate.to("/questions/new")
        )

        if app.storage.user.get("role") == "admin":
            ui.button(
                "User Management",
                on_click=lambda: ui.navigate.to("/admin/users"),
                color="secondary"
            )

        def logout():
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
        {"name": "Status", "label": "Status", "field": "Status"},
        {"name": "Version", "label": "Version", "field": "Version"},
        {"name": "Created by", "label": "Created By", "field": "Created by"},
        {"name": "Marks", "label": "Marks", "field": "Marks"},
        {"name": "Usage", "label": "Usage", "field": "Usage"},
        {"name": "actions", "label": "Actions", "field": "actions"},
    ]

    rows = []

    for q in questions:
        rows.append({
            "id": q["id"],  # real id, used internally for navigation
            "display_id": q["display_id"],
            "Question": q["Question"],
            "Status": q["Status"],
            "Version": q["Version"],
            "Created by": q["Created by"],
            "Marks": q["Marks"],
            "Usage": q["Usage"],
        })

    table = ui.table(
        columns=columns,
        rows=rows,
        row_key="id"
    ).classes("w-full")

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

    # Double click a row to open the detail page
    def open_question(e):
        ui.navigate.to(f'/questions/{e.args["id"]}')

    table.on("rowDblClick", open_question)

    # Dropdown menu actions
    def view_question(e):
        ui.navigate.to(f'/questions/{e.args["id"]}')

    def edit_question(e):
        ui.navigate.to(f'/questions/{e.args["id"]}/edit')

    def delete_question_prompt(e):
        qid = e.args["id"]
        display_id = e.args["display_id"]

        with ui.dialog() as dialog, ui.card():
            ui.label(f"Delete question #{display_id}?")
            ui.label("This action cannot be undone.").classes("text-sm text-grey-600")

            with ui.row().classes("gap-4 mt-4"):
                ui.button("Cancel", on_click=dialog.close)

                def confirm():
                    delete_question(qid)
                    dialog.close()
                    ui.navigate.to("/questions")

                ui.button("Delete", color="red", on_click=confirm)

        dialog.open()

    table.on("view", view_question)
    table.on("edit", edit_question)
    table.on("delete", delete_question_prompt)