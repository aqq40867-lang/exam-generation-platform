from nicegui import ui, app
from database import (
    list_users,
    delete_user,
    update_user_role,
    get_teacher_modules,
    set_teacher_modules,
)


def _format_modules_summary(modules: list, limit: int = 4) -> str:
    """Compact display string for a teacher's module list. Full list is shown
    up to `limit` entries; beyond that it's truncated with a "+N more" tail
    (the full list is still available via the row's tooltip) so a teacher
    with dozens of modules doesn't blow out the table layout."""
    if not modules:
        return "—"
    if len(modules) <= limit:
        return ", ".join(modules)
    return f"{', '.join(modules[:limit])} +{len(modules) - limit} more"


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
                    ui.label("Modules").classes("flex-1")
                    ui.label("Created At").classes("flex-1")
                    ui.label("Last Login").classes("flex-1")
                    ui.label("Actions").classes("w-24 text-center")

                for u in users:
                    username = u["Username"]
                    is_protected = bool(u.get("Protected"))

                    with ui.row().classes(
                        "w-full items-center border-b py-2"
                    ):
                        ui.label(username).classes("flex-1")

                        if is_protected:
                            # This is the top-level admin account: its role is
                            # permanently locked (always "admin"), so there's
                            # no editable dropdown here at all -- just a
                            # static, obviously-not-clickable indicator.
                            with ui.row().classes("w-40 items-center gap-1").tooltip(
                                "Protected account — role is permanently locked as admin."
                            ):
                                ui.icon("lock").classes("text-grey-500")
                                ui.label("admin").classes("font-medium")
                        else:
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

                        # Modules this teacher is allowed to author questions
                        # for (drives the restricted Module dropdown on the
                        # create/edit question pages). Shown alongside an
                        # explicit "Edit" button so it's clear this can be
                        # changed, not just viewed.
                        with ui.row().classes("flex-1 items-center gap-1 flex-nowrap"):
                            teacher_modules_now = get_teacher_modules(username)
                            modules_label = ui.label(
                                _format_modules_summary(teacher_modules_now)
                            ).classes("text-sm")
                            if teacher_modules_now:
                                modules_label.tooltip(", ".join(teacher_modules_now))

                            modules_edit_button = ui.button(
                                "Edit",
                                icon="edit",
                            ).props("flat dense size=sm color=primary").tooltip(
                                "Assign course modules to this teacher"
                            )

                        def make_modules_edit_handler(username, modules_label):
                            def open_edit_dialog():
                                # Local, in-memory working copy of this teacher's module
                                # list for the lifetime of the dialog. Each module is
                                # added one at a time (its own entity/row, with its own
                                # remove button) rather than all typed together into one
                                # field, so it's clear what's already assigned and what's
                                # being added.
                                modules_data = list(get_teacher_modules(username))

                                with ui.dialog() as dialog, ui.card().classes("w-96 max-h-[85vh]"):
                                    ui.label(f"Assign modules to {username}").classes("font-semibold")
                                    ui.label(
                                        "Add one course module at a time. Already-assigned "
                                        "modules are listed below — remove one with its x "
                                        "button, or add another at any time. No limit on how "
                                        "many a teacher can have (works fine with dozens)."
                                    ).classes("text-sm text-grey-600 mb-2")

                                    # Fixed-height, independently scrolling list so that even
                                    # with a large number of modules (tens to ~99), the Add
                                    # input and Save/Cancel buttons stay put and reachable
                                    # instead of the dialog growing off-screen.
                                    modules_list = ui.column().classes(
                                        "w-full gap-1 max-h-64 overflow-y-auto pr-1"
                                    )

                                    def render_modules_list():
                                        modules_list.clear()
                                        with modules_list:
                                            if not modules_data:
                                                ui.label("No modules assigned yet.").classes(
                                                    "text-sm text-grey-500 italic"
                                                )
                                            for i, module in enumerate(modules_data):

                                                def make_remove_handler(idx):
                                                    def handler():
                                                        modules_data.pop(idx)
                                                        render_modules_list()

                                                    return handler

                                                with ui.row().classes(
                                                    "w-full items-center justify-between border rounded px-3 py-1"
                                                ):
                                                    ui.label(module)
                                                    ui.button(
                                                        icon="close",
                                                        on_click=make_remove_handler(i),
                                                    ).props("flat dense round size=sm color=red")

                                    render_modules_list()

                                    with ui.row().classes("w-full items-center gap-2 mt-2"):
                                        new_module_input = ui.input(
                                            placeholder="e.g. CO923"
                                        ).classes("flex-grow")

                                        def add_module():
                                            new_module = (new_module_input.value or "").strip()
                                            if not new_module:
                                                return
                                            if any(
                                                new_module.lower() == m.lower()
                                                for m in modules_data
                                            ):
                                                ui.notify(
                                                    f'"{new_module}" is already in the list.',
                                                    color="warning"
                                                )
                                                new_module_input.value = ""
                                                return
                                            modules_data.append(new_module)
                                            new_module_input.value = ""
                                            render_modules_list()
                                            new_module_input.run_method("focus")

                                        new_module_input.on(
                                            "keydown.enter",
                                            lambda: add_module(),
                                        )

                                        ui.button(
                                            "Add",
                                            icon="add",
                                            on_click=add_module,
                                        )

                                    with ui.row().classes("gap-4 mt-4"):
                                        ui.button("Cancel", on_click=dialog.close)

                                        def save():
                                            set_teacher_modules(username, modules_data)
                                            updated_modules = get_teacher_modules(username)
                                            modules_label.text = _format_modules_summary(updated_modules)
                                            modules_label.tooltip(", ".join(updated_modules))
                                            ui.notify(
                                                f"Updated modules for {username}.",
                                                color="positive"
                                            )
                                            dialog.close()

                                        ui.button("Save", color="primary", on_click=save)

                                dialog.open()

                            return open_edit_dialog

                        modules_edit_button.on_click(
                            make_modules_edit_handler(username, modules_label)
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
                                            deleted = delete_user(username)
                                            dialog.close()
                                            if deleted:
                                                ui.notify(
                                                    f"Account '{username}' deleted.",
                                                    color="positive"
                                                )
                                            else:
                                                ui.notify(
                                                    f"'{username}' is a protected account and "
                                                    "cannot be deleted.",
                                                    color="negative"
                                                )
                                            refresh_table()

                                        ui.button("Delete", color="red", on_click=confirm)

                                dialog.open()

                            return delete_prompt

                        with ui.row().classes("w-24 justify-center gap-0"):
                            if is_protected:
                                ui.button(icon="lock").props(
                                    "flat dense round color=grey disable"
                                ).tooltip("Protected account — cannot be deleted.")
                            else:
                                ui.button(
                                    icon="delete",
                                    on_click=make_delete_handler(username)
                                ).props("flat dense round color=red")

        refresh_table()
