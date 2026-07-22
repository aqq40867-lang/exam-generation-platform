from nicegui import ui, app
from database import create_user


def signup_page():
    """Create New Account page."""

    # If already logged in, go directly to question list
    if app.storage.user.get("logged_in"):
        ui.navigate.to("/questions")
        return

    with ui.column().classes("w-96 mx-auto mt-20 items-center"):

        ui.label("Create New Account").classes("text-3xl font-bold")

        new_username = ui.input(
            "Username",
            placeholder="Choose a username"
        ).classes("w-full")

        new_password = ui.input(
            "Password",
            password=True,
            password_toggle_button=True,
            placeholder="Choose a password"
        ).classes("w-full")

        confirm_password = ui.input(
            "Confirm Password",
            password=True,
            password_toggle_button=True,
            placeholder="Re-enter your password"
        ).classes("w-full")

        def sign_up():

            new_user = new_username.value.strip()
            pwd = new_password.value
            confirm_pwd = confirm_password.value

            if not new_user:
                ui.notify("Username is required.", color="negative")
                return

            if not pwd:
                ui.notify("Password is required.", color="negative")
                return

            if pwd != confirm_pwd:
                ui.notify("Passwords do not match.", color="negative")
                return

            # New self-service signups are always regular (teacher) accounts.
            # Admin accounts can only be granted by an existing admin, via the
            # User Management page.
            new_id = create_user(new_user, pwd, role="teacher")

            if new_id is None:
                ui.notify(
                    f"Username '{new_user}' is already taken.",
                    color="negative"
                )
                return

            ui.notify(
                f"Account '{new_user}' created. You can now log in.",
                color="positive"
            )

            ui.navigate.to("/login")

        ui.button(
            "Create Account",
            on_click=sign_up
        ).classes("w-full")

        ui.separator().classes("my-4")

        ui.button(
            "Back to Login",
            on_click=lambda: ui.navigate.to("/login")
        ).classes("w-full")
