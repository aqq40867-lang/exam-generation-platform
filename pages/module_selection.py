"""NiceGUI page for selecting a course module, shown right after login.

The first page a teacher lands on after signing in: a grid of cards, one
per module they're assigned to, each labelled with how many of their own
questions already sit in that module. Picking a card sets it as the
Question List page's initial filter and navigates there.
"""

from collections import Counter

from nicegui import ui, app
from database import load_questions, get_teacher_modules, get_user_by_username


def module_selection_page():
    """Renders the module selection grid.

    Redirects to the login page if the user isn't signed in. The set of
    modules shown mirrors the sidebar on the Question List page: every
    module this teacher is assigned to (via an admin, on the User
    Management page), plus any module already used on one of their own
    questions even if it's since been unassigned.
    """

    if not app.storage.user.get("logged_in"):
        ui.navigate.to("/login")
        return

    username = app.storage.user["username"]

    # Re-verify the role fresh from the database, same as question_list.py,
    # so app.storage.user["role"] stays honest for other pages (e.g. the
    # "User Management" button on the Question List page) even if this
    # account's role changed after the current session started. Not used
    # for anything rendered on this page itself.
    current_user = get_user_by_username(username)
    role = current_user.get("Role") if current_user else app.storage.user.get("role", "teacher")
    app.storage.user["role"] = role

    with ui.row().classes("w-full items-center justify-between"):
        ui.label(f"Welcome, {username}").classes("text-2xl font-bold")

        def logout():
            """Clear the session and return the user to the login page."""
            app.storage.user.clear()
            ui.navigate.to("/login")

        ui.button(
            "Logout",
            on_click=logout,
            color="red"
        )

    ui.label("Select a module to get started").classes(
        "w-full text-center text-sm text-grey-600 mt-1"
    )

    ui.separator().classes("my-6")

    # Only this teacher's own questions count towards the per-module
    # counts shown on each card -- matches the scoping question_list.py
    # already uses for its own table/sidebar.
    own_questions = [
        q for q in load_questions() if q.get("Created by") == username
    ]
    module_counts = Counter(
        q["Module"] for q in own_questions if q.get("Module")
    )

    modules = sorted(
        set(get_teacher_modules(username)) | set(module_counts.keys()),
        key=str.lower,
    )

    def select_module(code):
        """Set the chosen module as the Question List page's initial
        filter and navigate there.

        Args:
            code: The module code that was clicked.
        """
        app.storage.user["module_filter"] = code
        ui.navigate.to("/questions")

    if not modules:
        with ui.column().classes("items-center w-full mt-16 gap-1"):
            ui.icon("school", size="48px").classes("text-grey-400")
            ui.label("No modules assigned yet.").classes("text-grey-600")
            ui.label(
                "Ask an admin to assign you a module on the User Management page."
            ).classes("text-sm text-grey-500")
        return

    with ui.grid(columns=2).classes("gap-8 mx-auto mt-4 w-max"):
        for code in modules:
            count = module_counts.get(code, 0)
            with ui.card().classes(
                "cursor-pointer hover:bg-grey-2 hover:shadow-lg transition-shadow "
                "items-center justify-center border"
            ).style("width: 600px; height: 200px").on(
                "click", lambda code=code: select_module(code)
            ):
                ui.label(code).classes("text-4xl font-bold")
                ui.label(
                    f"{count} question{'s' if count != 1 else ''}"
                ).classes("text-lg text-grey-600 mt-2")
