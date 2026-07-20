from nicegui import ui, app

# Username and password
USERS = {
    "Luca": "1",
    "teacher2": "456789",
    "1": "1",
}


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

            if user in USERS and USERS[user] == pwd:

                app.storage.user["logged_in"] = True
                app.storage.user["username"] = user

                ui.notify(
                    f"Welcome, {user}!",
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

        ui.separator()

        ui.label(
            "Please log in using your teacher account."
        ).classes("text-grey")