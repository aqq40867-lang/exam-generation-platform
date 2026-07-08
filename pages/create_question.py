from nicegui import ui, app
from database import add_question
from datetime import datetime


def create_question_page():
    """Create new question page."""
    
    # Check login
    if not app.storage.user.get("logged_in"):
        ui.navigate.to("/login")
        return
    
    username = app.storage.user["username"]
    
    with ui.column().classes("w-full max-w-4xl mx-auto p-8"):
        
        # Header
        ui.label("Create New Question").classes("text-3xl font-bold mb-6")
        
        # Form
        with ui.card().classes("w-full p-6"):
            
            # Question title
            ui.label("Question Title").classes("font-semibold")
            title_input = ui.input(
                placeholder="Enter question title"
            ).classes("w-full mb-4")
            
            # Main question text
            ui.label("Main Question Text").classes("font-semibold")
            main_text_input = ui.textarea(
                placeholder="Enter the main question text"
            ).classes("w-full mb-4").props("rows=5")
            
            # Marks
            ui.label("Marks").classes("font-semibold")
            marks_input = ui.number(
                label="",
                min=1,
                step=1
            ).classes("w-full mb-4")
            
            # Answer
            ui.label("Answer").classes("font-semibold")
            answer_input = ui.textarea(
                placeholder="Enter the answer"
            ).classes("w-full mb-4").props("rows=3")
            
            # Buttons
            with ui.row().classes("gap-4 mt-2"):
                
                def save_question():
                    """Save the new question."""
                    
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
                    
                    # Create question object
                    new_question = {
                        "Question": title,
                        "Main question": main_text,
                        "Marks": marks,
                        "Answer": answer,
                        "Status": "Draft",
                        "Version": 1,
                        "Created by": username,
                        "Created at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "Usage": 0,
                    }
                    
                    # Save to database
                    question_id = add_question(new_question)
                    
                    ui.notify(
                        f"Question created successfully! (ID: {question_id})",
                        color="positive"
                    )
                    
                    # Navigate back to question list
                    ui.navigate.to("/questions")
                
                ui.button(
                    "Save",
                    on_click=save_question,
                    color="primary"
                )
                
                ui.button(
                    "Cancel",
                    on_click=lambda: ui.navigate.to("/questions")
                )