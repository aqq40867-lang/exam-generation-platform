from nicegui import ui
from pages.login import login_page
from pages.question_list import question_list_page
from pages.question_detail import question_detail_page
from pages.create_question import create_question_page
from pages.edit_question import edit_question_page


# Home page
@ui.page('/')
def home():
    ui.navigate.to('/login')


# Login
@ui.page('/login')
def login():
    login_page()


# Question list
@ui.page('/questions')
def questions():
    question_list_page()


# Create question
@ui.page('/questions/new')
def create_question():
    create_question_page()


# Question detail
@ui.page('/questions/{question_id}')
def question_detail(question_id: int):
    question_detail_page(question_id)


# Edit question
@ui.page('/questions/{question_id}/edit')
def edit_question(question_id: int):
    edit_question_page(question_id)


ui.run(
    title='Exam Platform',
    reload=True,
    storage_secret='exam-platform-secret'
)