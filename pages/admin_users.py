from nicegui import ui, app
from database import list_users, delete_user, update_user_role


def admin_users_page():
    """User management page. Admins only: change roles and remove accounts."""

    # Check login
    if not app.storage.user.get("logged_in"):
        ui.navigate.to("/login")
        return

    # Check role - only admins may view this page
    if app.storage.user.get("role") != "admin":
        ui.notify("Admins only.", color="negative")
        ui.navigate.to("/questions")
        return

    current_username = app.storage.user["username"]

    with ui.column().classes("w-full max-w-4xl mx-auto p-8"):

        ui.label("User Management").classes("text-3xl font-bold mb-2")
        ui.label(
            "Change roles and remove accounts."
        ).classes("text-grey mb-4")

        with ui.row():
            ui.button(
                "Back to Questions",
                on_click=lambda: ui.navigate.to("/questions")
            )

        ui.separator().classes("my-4")

        # --- Existing users -----------------------------------------------------
        ui.label("Existing Accounts").classes("text-xl font-semibold mb-2")

        table_container = ui.column().classes("w-full gap-0")

        def refresh_table():
            table_container.clear()

            with table_container:
                users = list_users()

                # Header row
                with ui.row().classes(
                    "w-full items-center font-semibold border-b pb-2 mb-1"
                ):
                    ui.label("Username").classes("flex-1")
                    ui.label("Role").classes("w-40")
                    ui.label("Created At").classes("flex-1")
                    ui.label("Last Login").classes("flex-1")
                    ui.label("Actions").classes("w-16 text-center")

                for u in users:
                    username = u["Username"]

                    with ui.row().classes(
                        "w-full items-center border-b py-2"
                    ):
                        ui.label(username).classes("flex-1")

                        role_select = ui.select(
                            ["teacher", "admin"],
                            value=u["Role"]
                        ).classes("w-40")

                        # Tracks the last *confirmed* role for this row, so we
                        # know what to prompt about / revert to on cancel.
                        confirmed_role = {"value": u["Role"]}

                        def make_role_change_handler(username, role_select, confirmed_role):
                            def on_role_change():
                                new_role = role_select.value
                                old_role = confirmed_role["value"]

                                if new_role == old_role:
                                    return

                                with ui.dialog() as dialog, ui.card():
                                    ui.label(
                                        f"Change {username}'s role to '{new_role}'?"
                                    )

                                    with ui.row().classes("gap-4 mt-4"):

                                        def cancel():
                                            # Revert the dropdown without
                                            # touching the database.
                                            role_select.value = old_role
                                            dialog.close()

                                        def confirm():
                                            update_user_role(username, new_role)
                                            confirmed_role["value"] = new_role
                                            ui.notify(
                                                f"{username}'s role updated to {new_role}.",
                                                color="positive"
                                            )
                                            dialog.close()

                                        ui.button("Cancel", on_click=cancel)
                                        ui.button(
                                            "Confirm",
                                            color="primary",
                                            on_click=confirm
                                        )

                                dialog.open()

                            return on_role_change

                        role_select.on_value_change(
                            make_role_change_handler(username, role_select, confirmed_role)
                        )

                        ui.label(u.get("Created at") or "").classes("flex-1")
                        ui.label(u.get("Last login at") or "").classes("flex-1")

                        def make_delete_handler(username):
                            def delete_prompt():
                                if username == current_username:
                                    ui.notify(
                                        "You cannot delete your own account while logged in.",
                                        color="negative"
                                    )
                                    return

                                with ui.dialog() as dialog, ui.card():
                                    ui.label(f"Delete account '{username}'?")
                                    ui.label(
                                        "This action cannot be undone."
                                    ).classes("text-sm text-grey-600")

                                    with ui.row().classes("gap-4 mt-4"):
                                        ui.button("Cancel", on_click=dialog.close)

                                        def confirm():
                                            delete_user(username)
                                            dialog.close()
                                            ui.notify(
                                                f"Account '{username}' deleted.",
                                                color="positive"
                                            )
                                            refresh_table()

                                        ui.button("Delete", color="red", on_click=confirm)

                                dialog.open()

                            return delete_prompt

                        with ui.row().classes("w-16 justify-center"):
                            ui.button(
                                icon="delete",
                                on_click=make_delete_handler(username)
                            ).props("flat dense round color=red")

        refresh_table()
