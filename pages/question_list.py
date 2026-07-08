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

        def logout():
            app.storage.user.clear()
            ui.navigate.to("/login")

        ui.button(
            "Logout",
            on_click=logout,
            color="red"
        )

    ui.separator()

    questions = load_questions()

    columns = [
        {"name": "id", "label": "ID", "field": "id"},
        {"name": "Question", "label": "Question", "field": "Question"},
        {"name": "Status", "label": "Status", "field": "Status"},
        {"name": "Version", "label": "Version", "field": "Version"},
        {"name": "Created by", "label": "Created By", "field": "Created by"},
        {"name": "Marks", "label": "Marks", "field": "Marks"},
        {"name": "Usage", "label": "Usage", "field": "Usage"},
    ]

    rows = []

    for q in questions:
        rows.append({
            "id": q["id"],
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

    # Double click to open detail page
    def open_question(e):
        ui.navigate.to(f'/questions/{e.args["id"]}')

    table.on("rowDblClick", open_question)

    ui.separator()

    ui.label("Actions").classes("text-xl")

    for q in questions:

        with ui.card().classes("w-full"):

            ui.label(
                f'#{q["id"]} - {q["Question"]}'
            ).classes("text-lg font-bold")

            with ui.row():

                ui.button(
                    "View",
                    on_click=lambda qid=q["id"]:
                    ui.navigate.to(f"/questions/{qid}")
                )

                ui.button(
                    "Edit",
                    on_click=lambda qid=q["id"]:
                    ui.navigate.to(f"/questions/{qid}/edit")
                )

                def delete(qid=q["id"]):

                    with ui.dialog() as dialog, ui.card():

                        ui.label(
                            "Delete this question?"
                        )

                        with ui.row():

                            ui.button(
                                "Cancel",
                                on_click=dialog.close
                            )

                            def confirm():

                                delete_question(qid)

                                dialog.close()

                                ui.navigate.to("/questions")

                            ui.button(
                                "Delete",
                                color="red",
                                on_click=confirm
                            )

                    dialog.open()

                ui.button(
                    "Delete",
                    color="red",
                    on_click=delete
                )