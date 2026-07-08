import json
import os

QUESTIONS_FILE = "questions.json"


def load_questions():
    """Load all questions from the JSON file."""

    if not os.path.exists(QUESTIONS_FILE):
        with open(QUESTIONS_FILE, "w", encoding="utf-8") as f:
            json.dump([], f, indent=4, ensure_ascii=False)

    with open(QUESTIONS_FILE, "r", encoding="utf-8") as f:
        questions = json.load(f)

    return questions


def save_questions(questions):
    """Save all questions to the JSON file."""

    with open(QUESTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(
            questions,
            f,
            indent=4,
            ensure_ascii=False
        )


def get_question(question_id):
    """Return one question by id."""

    questions = load_questions()

    for question in questions:
        if question["id"] == question_id:
            return question

    return None


def add_question(question):
    """Add a new question."""

    questions = load_questions()

    new_id = max(
        [q["id"] for q in questions],
        default=0
    ) + 1

    question["id"] = new_id

    questions.append(question)

    save_questions(questions)

    return new_id


def update_question(question_id, updated_question):
    """Update an existing question."""

    questions = load_questions()

    for index, question in enumerate(questions):
        if question["id"] == question_id:
            updated_question["id"] = question_id
            questions[index] = updated_question
            save_questions(questions)
            return True

    return False


def delete_question(question_id):
    """Delete a question."""

    questions = load_questions()

    questions = [
        q for q in questions
        if q["id"] != question_id
    ]

    save_questions(questions)