from nicegui import ui, app
from database import get_question, delete_question, load_questions, get_question_parts


def question_detail_page(question_id: int):
    """View question detail page."""
    
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
    
    # Only the creator can view this question
    if question.get("Created by") != username:
        ui.notify("You do not have permission to view this question.", color="negative")
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
    
    with ui.column().classes("w-full max-w-4xl mx-auto p-8"):
        
        # Header
        ui.label(f"Question Detail #{display_id}").classes("text-3xl font-bold mb-6")
        
        # Question details card
        with ui.card().classes("w-full p-6"):
            
            # Question Title
            ui.label("Question Title:").classes("font-semibold text-grey-600")
            ui.label(question.get("Question", "N/A")).classes("text-lg mb-4")
            
            # Module
            ui.label("Module:").classes("font-semibold text-grey-600")
            ui.label(question.get("Module") or "N/A").classes("text-lg mb-4")

            # Description (optional shared context for the question)
            ui.label("Description:").classes("font-semibold text-grey-600")
            ui.label(question.get("Main question") or "N/A").classes("text-lg mb-4")

            # Sub-questions (if this question was broken into parts)
            parts = get_question_parts(question_id)
            if parts:
                ui.label("Sub-questions:").classes("font-semibold text-grey-600")
                with ui.column().classes("w-full gap-2 mb-4"):
                    for part in parts:
                        with ui.row().classes("w-full items-start gap-3 border-b pb-2"):
                            ui.label(f"({part.get('Label')})").classes("font-semibold w-10")
                            ui.label(part.get("Description") or "—").classes("flex-grow")
                            ui.label(f"[{part.get('Marks', 0)} marks]").classes("text-grey-600")

            # Marks
            ui.label("Marks (total):" if parts else "Marks:").classes("font-semibold text-grey-600")
            ui.label(str(question.get("Marks", "N/A"))).classes("text-lg mb-4")

            # Answer
            ui.label("Answer:").classes("font-semibold text-grey-600")
            with ui.card().classes("bg-grey-100 w-full p-3 mb-4"):
                ui.label(question.get("Answer", "N/A")).classes("text-md")
            
            # Status
            ui.label("Status:").classes("font-semibold text-grey-600")
            status = question.get("Status", "N/A")
            status_color = "green" if status == "Published" else "orange" if status == "Draft" else "grey"
            ui.label(status).classes(f"text-{status_color}-600 text-lg mb-4")
            
            # Version
            ui.label("Version:").classes("font-semibold text-grey-600")
            ui.label(str(question.get("Version", 1))).classes("text-lg mb-4")
            
            # Created By
            ui.label("Created By:").classes("font-semibold text-grey-600")
            ui.label(question.get("Created by", "N/A")).classes("text-lg mb-4")
            
            # Created At
            ui.label("Created At:").classes("font-semibold text-grey-600")
            ui.label(question.get("Created at", "N/A")).classes("text-lg mb-4")
            
            # Updated At (if exists)
            if "Updated at" in question:
                ui.label("Updated At:").classes("font-semibold text-grey-600")
                ui.label(question.get("Updated at", "N/A")).classes("text-lg mb-4")
            
            # Usage
            ui.label("Usage:").classes("font-semibold text-grey-600")
            ui.label(str(question.get("Usage", 0))).classes("text-lg mb-4")
        
        # Action buttons
        with ui.row().classes("gap-4 mt-4"):
            
            ui.button(
                "Back to List",
                on_click=lambda: ui.navigate.to("/questions")
            )
            
            ui.button(
                "Edit",
                on_click=lambda: ui.navigate.to(f"/questions/{question_id}/edit"),
                color="primary"
            )
            
            # Delete button with confirmation
            def confirm_delete():
                with ui.dialog() as dialog, ui.card():
                    ui.label("Delete this question?").classes("text-lg")
                    ui.label("This action cannot be undone.").classes("text-sm text-grey-600")
                    
                    with ui.row().classes("gap-4 mt-4"):
                        ui.button(
                            "Cancel",
                            on_click=dialog.close
                        )
                        
                        def delete_question_confirmed():
                            delete_question(question_id)
                            dialog.close()
                            ui.notify("Question deleted successfully.", color="positive")
                            ui.navigate.to("/questions")
                        
                        ui.button(
                            "Delete",
                            color="red",
                            on_click=delete_question_confirmed
                        )
                
                dialog.open()
            
            ui.button(
                "Delete",
                color="red",
                on_click=confirm_delete
            )