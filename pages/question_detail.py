from nicegui import ui, app
from database import get_question, delete_question


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
    
    with ui.column().classes("w-full max-w-4xl mx-auto p-8"):
        
        # Header
        ui.label(f"Question Detail #{question_id}").classes("text-3xl font-bold mb-6")
        
        # Question details card
        with ui.card().classes("w-full p-6"):
            
            # Question Title
            ui.label("Question Title:").classes("font-semibold text-grey-600")
            ui.label(question.get("Question", "N/A")).classes("text-lg mb-4")
            
            # Main Question
            ui.label("Main Question:").classes("font-semibold text-grey-600")
            ui.label(question.get("Main question", "N/A")).classes("text-lg mb-4")
            
            # Marks
            ui.label("Marks:").classes("font-semibold text-grey-600")
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