from nicegui import ui, app
from database import authenticate_user


def login_page():
    """Login page."""

    # If already logged in, go directly to question list
    if app.storage.user.get("logged_in"):
        ui.navigate.to("/questions")
        return

    with ui.column().classes("w-96 mx-auto mt-20 items-center"):

        ui.label("Exam Platform Login").classes("text-3xl font-bold")

        username = ui.input(
            "Username",
            placeholder="Enter your username"
        ).classes("w-full")

        password = ui.input(
            "Password",
            password=True,
            password_toggle_button=True,
            placeholder="Enter your password"
        ).classes("w-full")

        def login():

            user = username.value.strip()
            pwd = password.value

            authenticated_user = authenticate_user(user, pwd)

            if authenticated_user:

                app.storage.user["logged_in"] = True
                app.storage.user["username"] = authenticated_user["Username"]
                app.storage.user["role"] = authenticated_user["Role"]

                ui.notify(
                    f"Welcome, {authenticated_user['Username']}!",
                    color="positive"
                )

                ui.navigate.to("/questions")

            else:

                ui.notify(
                    "Invalid username or password.",
                    color="negative"
                )

        ui.button(
            "Login",
            on_click=login
        ).classes("w-full")

        ui.button(
            "Create New Account",
            on_click=lambda: ui.navigate.to("/signup")
        ).classes("w-full")