from nicegui import ui, app
from database import get_question, update_question, load_questions
from datetime import datetime


def edit_question_page(question_id: int):
    """Edit existing question page."""
    
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
    
    # Only the creator can edit this question
    if question.get("Created by") != username:
        ui.notify("You do not have permission to edit this question.", color="negative")
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
        ui.label(f"Edit Question #{display_id}").classes("text-3xl font-bold mb-6")
        
        # Form
        with ui.card().classes("w-full p-6"):
            
            # Question title
            ui.label("Question Title").classes("font-semibold")
            title_input = ui.input(
                value=question.get("Question", ""),
                placeholder="Enter question title"
            ).classes("w-full mb-4")
            
            # Main question text
            ui.label("Main Question Text").classes("font-semibold")
            main_text_input = ui.textarea(
                value=question.get("Main question", ""),
                placeholder="Enter the main question text"
            ).classes("w-full mb-4").props("rows=5")
            
            # Marks
            ui.label("Marks").classes("font-semibold")
            marks_input = ui.number(
                label="",
                value=question.get("Marks", 1),
                min=1,
                step=1
            ).classes("w-full mb-4")
            
            # Answer
            ui.label("Answer").classes("font-semibold")
            answer_input = ui.textarea(
                value=question.get("Answer", ""),
                placeholder="Enter the answer"
            ).classes("w-full mb-4").props("rows=3")
            
            # Status (read-only display)
            ui.label(f"Status: {question.get('Status', 'Unknown')}").classes("text-sm text-grey-600 mb-4")
            
            # Version (read-only display)
            ui.label(f"Version: {question.get('Version', 1)}").classes("text-sm text-grey-600 mb-4")
            
            # Buttons
            with ui.row().classes("gap-4 mt-2"):
                
                def save_changes():
                    """Save the updated question."""
                    
                    title = title_input.value.strip()
                    main_text = main_text_input.value.strip()
                    marks = marks_input.value
                    answer = answer_input.value.strip()
                    
                    # Validate inputs
                    if not title:
                        ui.notify("Question title is required.", color="negative")
                        return
                    
                    if not main_text:
                        ui.notify("Main question text is required.", color="negative")
                        return
                    
                    if not marks or marks <= 0:
                        ui.notify("Marks must be greater than 0.", color="negative")
                        return
                    
                    if not answer:
                        ui.notify("Answer is required.", color="negative")
                        return
                    
                    # Create updated question object (preserve existing fields)
                    updated_question = {
                        "Question": title,
                        "Main question": main_text,
                        "Marks": marks,
                        "Answer": answer,
                        "Status": question.get("Status", "Draft"),
                        "Version": question.get("Version", 1) + 1,  # Increment version
                        "Created by": question.get("Created by", username),
                        "Created at": question.get("Created at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                        "Updated at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "Usage": question.get("Usage", 0),
                    }
                    
                    # Update in database
                    success = update_question(question_id, updated_question)
                    
                    if success:
                        ui.notify(
                            "Question updated successfully!",
                            color="positive"
                        )
                        ui.navigate.to("/questions")
                    else:
                        ui.notify(
                            "Failed to update question.",
                            color="negative"
                        )
                
                ui.button(
                    "Save Changes",
                    on_click=save_changes,
                    color="primary"
                )
                
                ui.button(
                    "Cancel",
                    on_click=lambda: ui.navigate.to("/questions")
                )
                
                ui.button(
                    "View Question",
                    on_click=lambda: ui.navigate.to(f"/questions/{question_id}")
                )