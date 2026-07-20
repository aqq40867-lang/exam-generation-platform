"""
Simple SQLite-backed data layer for the exam platform.

Why SQLite:
- Built into Python's standard library (the `sqlite3` module) -> no install,
  no account, no cost, ever.
- The whole database is a single file (exam_platform.db) that lives next to
  this script, so it's easy to back up / submit with your assignment.
- Perfectly fine for a single small table like this with hundreds/thousands
  of rows and a handful of users.
"""

import sqlite3
import os

# The .db file will be created next to this file, in the same folder.
DB_PATH = os.path.join(os.path.dirname(__file__), "exam_platform.db")


def get_connection():
    """Open a connection to the SQLite database file.

    row_factory = sqlite3.Row lets us access columns by name (like a dict),
    which matches how the rest of the app already uses question.get("Question")
    etc.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create the questions table if it doesn't exist yet.

    Column names with spaces (like "Created by") are quoted with double
    quotes, which SQLite allows.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            "Question" TEXT NOT NULL,
            "Main question" TEXT,
            "Marks" INTEGER,
            "Answer" TEXT,
            "Status" TEXT,
            "Version" INTEGER,
            "Created by" TEXT,
            "Created at" TEXT,
            "Updated at" TEXT,
            "Usage" INTEGER DEFAULT 0
        )
    """)

    conn.commit()
    conn.close()


def load_questions():
    """Return all questions as a list of dicts."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM questions")
    rows = cursor.fetchall()

    conn.close()

    return [dict(row) for row in rows]


def get_question(question_id: int):
    """Return a single question as a dict, or None if it doesn't exist."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM questions WHERE id = ?", (question_id,))
    row = cursor.fetchone()

    conn.close()

    return dict(row) if row else None


def add_question(question: dict) -> int:
    """Insert a new question and return its new id."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO questions (
            "Question", "Main question", "Marks", "Answer",
            "Status", "Version", "Created by", "Created at", "Usage"
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        question.get("Question"),
        question.get("Main question"),
        question.get("Marks"),
        question.get("Answer"),
        question.get("Status"),
        question.get("Version"),
        question.get("Created by"),
        question.get("Created at"),
        question.get("Usage", 0),
    ))

    conn.commit()
    new_id = cursor.lastrowid
    conn.close()

    return new_id


def update_question(question_id: int, updated_question: dict) -> bool:
    """Update an existing question. Returns True if a row was updated."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE questions
        SET "Question" = ?,
            "Main question" = ?,
            "Marks" = ?,
            "Answer" = ?,
            "Status" = ?,
            "Version" = ?,
            "Created by" = ?,
            "Created at" = ?,
            "Updated at" = ?,
            "Usage" = ?
        WHERE id = ?
    """, (
        updated_question.get("Question"),
        updated_question.get("Main question"),
        updated_question.get("Marks"),
        updated_question.get("Answer"),
        updated_question.get("Status"),
        updated_question.get("Version"),
        updated_question.get("Created by"),
        updated_question.get("Created at"),
        updated_question.get("Updated at"),
        updated_question.get("Usage", 0),
        question_id,
    ))

    conn.commit()
    success = cursor.rowcount > 0
    conn.close()

    return success


def delete_question(question_id: int) -> bool:
    """Delete a question by id. Returns True if a row was deleted."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM questions WHERE id = ?", (question_id,))

    conn.commit()
    success = cursor.rowcount > 0
    conn.close()

    return success


# Make sure the table exists as soon as this module is imported.
init_db()