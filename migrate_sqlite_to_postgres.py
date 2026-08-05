"""
One-time data migration: copy everything out of the old exam_platform.db
SQLite file into the new Postgres database.

Run this ONCE, after Postgres is up (e.g. `docker compose up -d postgres`)
and before you start using the app for real on Postgres:

    python migrate_sqlite_to_postgres.py

By default it looks for exam_platform.db next to this script and writes to
whatever DATABASE_URL database.py is configured to use (same env var, so
if you're running this from your host machine against the Postgres
container, set DATABASE_URL first, e.g.:

    # Windows PowerShell
    $env:DATABASE_URL = "postgresql://exam_platform:exam_platform@localhost:5432/exam_platform"
    python migrate_sqlite_to_postgres.py

Row IDs are preserved exactly as they were in SQLite (not re-assigned),
so foreign keys (question_parts -> questions, exam_questions -> exams /
questions) stay valid. After copying the data, each table's Postgres
auto-increment sequence is bumped past the highest migrated id, so the
app's normal INSERTs afterwards continue from the right number instead
of colliding with migrated rows.

Safe to run against an empty/fresh Postgres database. NOT safe to run
twice against the same Postgres database that already has data in it --
it will fail on the primary key / unique constraints instead of silently
duplicating anything, which is the right failure mode here.
"""

import os
import sqlite3
import sys

# Make sure "python migrate_sqlite_to_postgres.py" finds models.py/database.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text

from database import engine, SessionLocal  # noqa: E402  (import after sys.path tweak)
from models import (  # noqa: E402
    Base,
    Question,
    QuestionPart,
    User,
    Exam,
    ExamQuestion,
    TeacherModule,
)

SQLITE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exam_platform.db")


def _sqlite_rows(table: str):
    """Yield every row of `table` from the old SQLite file as a dict."""
    if not os.path.exists(SQLITE_PATH):
        print(f"No {SQLITE_PATH} found -- nothing to migrate.")
        return
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        for row in conn.execute(f"SELECT * FROM {table}"):
            yield dict(row)
    finally:
        conn.close()


def _bump_sequence(session, table: str):
    """Advance Postgres's auto-increment sequence for `table` past the
    highest id we just inserted, so the app's next INSERT (which doesn't
    specify an id) doesn't collide with migrated rows. Only meaningful on
    Postgres (SQLite has no sequences to bump -- e.g. if DATABASE_URL is
    pointed at a sqlite:/// URL for a quick local test of this script)."""
    if session.get_bind().dialect.name != "postgresql":
        return
    session.execute(text(
        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
        f"COALESCE((SELECT MAX(id) FROM {table}), 1), "
        f"(SELECT MAX(id) FROM {table}) IS NOT NULL)"
    ))


def migrate():
    if not os.path.exists(SQLITE_PATH):
        print(f"No {SQLITE_PATH} found next to this script -- nothing to migrate.")
        return

    # Make sure the Postgres schema exists (harmless no-op if it already does).
    Base.metadata.create_all(engine)

    session = SessionLocal()
    try:
        counts = {}

        # Order matters: parent tables (users, questions, exams) before the
        # tables that reference them (question_parts, exam_questions).
        # teacher_modules has no real FK (it's a plain text username), so
        # it can go anywhere.

        for row in _sqlite_rows("users"):
            session.add(User(
                id=row["id"],
                username=row["Username"],
                password_hash=row["Password hash"],
                salt=row["Salt"],
                role=row["Role"],
                created_at=row["Created at"],
                last_login_at=row["Last login at"],
                protected=row["Protected"],
            ))
        counts["users"] = session.query(User).count()

        for row in _sqlite_rows("questions"):
            session.add(Question(
                id=row["id"],
                question=row["Question"],
                main_question=row["Main question"],
                marks=row["Marks"],
                answer=row["Answer"],
                status=row["Status"],
                version=row["Version"],
                created_by=row["Created by"],
                created_at=row["Created at"],
                updated_at=row["Updated at"],
                usage=row["Usage"],
                module=row["Module"],
            ))

        for row in _sqlite_rows("exams"):
            session.add(Exam(
                id=row["id"],
                name=row["Name"],
                description=row["Description"],
                total_marks=row["Total marks"],
                status=row["Status"],
                created_by=row["Created by"],
                created_at=row["Created at"],
                updated_at=row["Updated at"],
            ))

        # Flush parents before children that FK-reference them.
        session.flush()

        for row in _sqlite_rows("question_parts"):
            session.add(QuestionPart(
                id=row["id"],
                question_id=row["question_id"],
                label=row["Label"],
                order_index=row["Order"],
                description=row["Description"],
                marks=row["Marks"],
                answer=row["Answer"],
                answer_space=row["Answer space"],
            ))

        for row in _sqlite_rows("exam_questions"):
            session.add(ExamQuestion(
                id=row["id"],
                exam_id=row["exam_id"],
                question_id=row["question_id"],
                order_index=row["Order"],
                marks_override=row["Marks override"],
            ))

        for row in _sqlite_rows("teacher_modules"):
            session.add(TeacherModule(
                id=row["id"],
                username=row["Username"],
                module=row["Module"],
            ))

        session.flush()

        for table in ("users", "questions", "exams", "question_parts", "exam_questions", "teacher_modules"):
            _bump_sequence(session, table)

        session.commit()

        for table, model in (
            ("users", User), ("questions", Question), ("exams", Exam),
            ("question_parts", QuestionPart), ("exam_questions", ExamQuestion),
            ("teacher_modules", TeacherModule),
        ):
            print(f"{table}: {session.query(model).count()} row(s) migrated")

        print("Migration complete.")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    migrate()
