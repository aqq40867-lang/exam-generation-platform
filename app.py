"""Application entry point that wires NiceGUI routes to their page modules.

Each route below is a thin wrapper that delegates rendering to the
corresponding `*_page` function in `pages/`; running this module starts the
NiceGUI web server.
"""

from nicegui import ui
from pages.login import login_page
from pages.signup import signup_page
from pages.question_list import question_list_page
from pages.question_detail import question_detail_page
from pages.create_question import create_question_page
from pages.edit_question import edit_question_page
from pages.admin_users import admin_users_page
from pages.export_exam import export_exam_page


@ui.page('/')
def home():
    """Redirects the root URL to the login page."""
    ui.navigate.to('/login')


@ui.page('/login')
def login():
    """Renders the login page."""
    login_page()


@ui.page('/signup')
def signup():
    """Renders the create-new-account page."""
    signup_page()


@ui.page('/questions')
def questions():
    """Renders the question bank list page."""
    question_list_page()


@ui.page('/questions/new')
def create_question():
    """Renders the page for creating a new question."""
    create_question_page()


@ui.page('/questions/{question_id}')
def question_detail(question_id: int):
    """Renders the detail page for a single question.

    Args:
        question_id: ID of the question to display.
    """
    question_detail_page(question_id)


@ui.page('/questions/{question_id}/edit')
def edit_question(question_id: int):
    """Renders the page for editing an existing question.

    Args:
        question_id: ID of the question to edit.
    """
    edit_question_page(question_id)


@ui.page('/exams/export')
def export_exam():
    """Renders the exam export page (select questions, generate PDF via LaTeX)."""
    export_exam_page()


@ui.page('/admin/users')
def admin_users():
    """Renders the user management page (admin only)."""
    admin_users_page()


ui.run(
    title='Exam Platform',
    reload=True,
    storage_secret='exam-platform-secret'
)