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
import hashlib
import secrets
import string
from datetime import datetime
from typing import Optional, Tuple

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
    # Needed so that ON DELETE CASCADE (used by exam_questions) is enforced.
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create all tables if they don't exist yet.

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
            "Usage" INTEGER DEFAULT 0,
            "Module" TEXT
        )
    """)

    # Migration: older DB files may already have a `questions` table that
    # was created before the "Module" column existed. ALTER TABLE ... ADD
    # COLUMN is a no-op-safe way to bring old databases up to date without
    # losing data.
    existing_columns = {row["name"] for row in cursor.execute("PRAGMA table_info(questions)")}
    if "Module" not in existing_columns:
        cursor.execute('ALTER TABLE questions ADD COLUMN "Module" TEXT')

    # Sub-questions (子问题) belonging to a single "main question" row in
    # `questions` (e.g. main question "A. Binary Tree" -> parts (a), (b), (c)).
    # A main question may have zero sub-questions (plain question, uses the
    # "Marks" column on `questions` directly) or many (in which case the
    # main question's "Marks" is auto-computed as the sum of its parts).
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS question_parts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
            "Label" TEXT,
            "Order" INTEGER,
            "Description" TEXT,
            "Marks" INTEGER NOT NULL DEFAULT 0,
            "Answer" TEXT
        )
    """)

    # Accounts. Passwords are never stored in plain text: we keep a random
    # per-user salt plus a PBKDF2-SHA256 hash of (password + salt).
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            "Username" TEXT NOT NULL UNIQUE,
            "Password hash" TEXT NOT NULL,
            "Salt" TEXT NOT NULL,
            "Role" TEXT NOT NULL DEFAULT 'teacher',
            "Created at" TEXT,
            "Last login at" TEXT
        )
    """)

    # Exams / exam papers.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS exams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            "Name" TEXT NOT NULL,
            "Description" TEXT,
            "Total marks" INTEGER,
            "Status" TEXT DEFAULT 'Draft',
            "Created by" TEXT,
            "Created at" TEXT,
            "Updated at" TEXT
        )
    """)

    # Which questions belong to which exam, in what order, and whether the
    # question's default mark value is overridden for that specific exam.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS exam_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_id INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
            question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
            "Order" INTEGER,
            "Marks override" INTEGER,
            UNIQUE(exam_id, question_id)
        )
    """)

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def _hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    """Return (password_hash_hex, salt_hex) using PBKDF2-HMAC-SHA256.

    A fresh random salt is generated when one isn't supplied (i.e. when
    creating a new user). The same salt must be passed back in to verify
    a password later.
    """
    if salt is None:
        salt = secrets.token_hex(16)

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        100_000,
    )

    return digest.hex(), salt


def create_user(username: str, password: str, role: str = "teacher") -> Optional[int]:
    """Create a new user with a hashed password. Returns new id, or None if
    the username is already taken."""
    conn = get_connection()
    cursor = conn.cursor()

    password_hash, salt = _hash_password(password)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        cursor.execute("""
            INSERT INTO users ("Username", "Password hash", "Salt", "Role", "Created at")
            VALUES (?, ?, ?, ?, ?)
        """, (username, password_hash, salt, role, now))
        conn.commit()
        new_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        new_id = None
    finally:
        conn.close()

    return new_id


def get_user_by_username(username: str):
    """Return a single user as a dict, or None if it doesn't exist."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM users WHERE "Username" = ?', (username,))
    row = cursor.fetchone()

    conn.close()

    return dict(row) if row else None


def authenticate_user(username: str, password: str):
    """Check username/password against the DB.

    Returns the user dict (password fields excluded) on success, else None.
    Also updates "Last login at" on success.
    """
    user = get_user_by_username(username)
    if not user:
        return None

    expected_hash, _ = _hash_password(password, salt=user["Salt"])
    if not secrets.compare_digest(expected_hash, user["Password hash"]):
        return None

    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        'UPDATE users SET "Last login at" = ? WHERE id = ?',
        (now, user["id"]),
    )
    conn.commit()
    conn.close()

    return {
        "id": user["id"],
        "Username": user["Username"],
        "Role": user["Role"],
        "Created at": user["Created at"],
        "Last login at": now,
    }


def update_user_password(username: str, new_password: str) -> bool:
    """Reset a user's password. Returns True if a row was updated."""
    conn = get_connection()
    cursor = conn.cursor()

    password_hash, salt = _hash_password(new_password)
    cursor.execute("""
        UPDATE users SET "Password hash" = ?, "Salt" = ?
        WHERE "Username" = ?
    """, (password_hash, salt, username))

    conn.commit()
    success = cursor.rowcount > 0
    conn.close()

    return success


def update_user_role(username: str, new_role: str) -> bool:
    """Change a user's role. Returns True if a row was updated."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        'UPDATE users SET "Role" = ? WHERE "Username" = ?',
        (new_role, username),
    )

    conn.commit()
    success = cursor.rowcount > 0
    conn.close()

    return success


def delete_user(username: str) -> bool:
    """Delete a user by username. Returns True if a row was deleted."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('DELETE FROM users WHERE "Username" = ?', (username,))

    conn.commit()
    success = cursor.rowcount > 0
    conn.close()

    return success


def list_users():
    """Return all users (without password hash/salt) as a list of dicts."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('SELECT id, "Username", "Role", "Created at", "Last login at" FROM users')
    rows = cursor.fetchall()

    conn.close()

    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Questions（题库）
# ---------------------------------------------------------------------------
# 存单个题目本身：题干、主问题、分值、答案、状态、版本、创建人等。
# 一道题创建一次，可以被反复复用到不同的考试里，跟"考试"没有直接关系。

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
            "Status", "Version", "Created by", "Created at", "Usage", "Module"
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        question.get("Module"),
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
            "Usage" = ?,
            "Module" = ?
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
        updated_question.get("Module"),
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


def list_modules():
    """Return a sorted list of the distinct, non-empty course modules
    ("Module", e.g. "CO923") already used across all questions.

    Used to populate the module dropdown/combobox on the create/edit forms
    and the filter dropdown on the question list page.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT DISTINCT "Module" FROM questions
        WHERE "Module" IS NOT NULL AND TRIM("Module") != ''
        ORDER BY "Module" COLLATE NOCASE
    """)
    rows = cursor.fetchall()

    conn.close()

    return [row["Module"] for row in rows]


# ---------------------------------------------------------------------------
# Question parts (子问题 / sub-questions)
# ---------------------------------------------------------------------------
# A "main question" (a row in `questions`, e.g. "A. Binary Tree") can be
# broken down into several sub-questions, following the UK university
# convention of labelling them (a), (b), (c), ... Each part carries its own
# mark value; the parent question's total "Marks" is auto-computed as the
# sum of all of its parts whenever it has at least one.

def _label_for_index(index: int) -> str:
    """Return the UK-style lower-case letter label for a 0-based index:
    0 -> 'a', 1 -> 'b', ..., 25 -> 'z', 26 -> 'aa', etc. (Displayed in the
    UI wrapped in parentheses, e.g. "(a)".)
    """
    letters = string.ascii_lowercase
    label = ""
    index += 1
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        label = letters[remainder] + label
    return label


def get_question_parts(question_id: int):
    """Return all sub-questions for a main question, in order."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM question_parts
        WHERE question_id = ?
        ORDER BY "Order" IS NULL, "Order"
    """, (question_id,))
    rows = cursor.fetchall()

    conn.close()

    return [dict(row) for row in rows]


def replace_question_parts(question_id: int, parts: list) -> int:
    """Replace all sub-questions belonging to `question_id` with `parts`.

    `parts` is a list of dicts, each with (at least) "Description" (may be
    empty/None) and "Marks" (int), in the desired display order. Labels
    ((a), (b), (c)...) are (re)assigned automatically from the list order,
    so callers never need to manage labels themselves.

    The parent question's "Marks" column is then set to the sum of the
    parts' marks (this is the auto total-marks calculation) and the new
    total is returned. If `parts` is empty, the parent's "Marks" is left
    untouched and 0 is returned.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM question_parts WHERE question_id = ?", (question_id,))

    total_marks = 0
    for order, part in enumerate(parts):
        marks = int(part.get("Marks") or 0)
        total_marks += marks
        cursor.execute("""
            INSERT INTO question_parts (question_id, "Label", "Order", "Description", "Marks", "Answer")
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            question_id,
            _label_for_index(order),
            order,
            part.get("Description"),
            marks,
            part.get("Answer"),
        ))

    if parts:
        cursor.execute('UPDATE questions SET "Marks" = ? WHERE id = ?', (total_marks, question_id))

    conn.commit()
    conn.close()

    return total_marks


def delete_question_parts(question_id: int) -> None:
    """Delete all sub-questions for a main question (also happens
    automatically via ON DELETE CASCADE when the question itself is
    deleted, but exposed here for explicit use, e.g. converting a
    multi-part question back into a plain one)."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM question_parts WHERE question_id = ?", (question_id,))

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Exams
# ---------------------------------------------------------------------------
# 存一场考试的整体信息：
# 名字、说明、总分、状态（草稿/发布）、创建人等。它本身不包含具体题目内容，只是一个"壳"。

def load_exams():
    """Return all exams as a list of dicts."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM exams")
    rows = cursor.fetchall()

    conn.close()

    return [dict(row) for row in rows]


def get_exam(exam_id: int):
    """Return a single exam as a dict, or None if it doesn't exist."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM exams WHERE id = ?", (exam_id,))
    row = cursor.fetchone()

    conn.close()

    return dict(row) if row else None


def add_exam(exam: dict) -> int:
    """Insert a new exam and return its new id."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO exams (
            "Name", "Description", "Total marks", "Status",
            "Created by", "Created at"
        ) VALUES (?, ?, ?, ?, ?, ?)
    """, (
        exam.get("Name"),
        exam.get("Description"),
        exam.get("Total marks"),
        exam.get("Status", "Draft"),
        exam.get("Created by"),
        exam.get("Created at"),
    ))

    conn.commit()
    new_id = cursor.lastrowid
    conn.close()

    return new_id


def update_exam(exam_id: int, updated_exam: dict) -> bool:
    """Update an existing exam. Returns True if a row was updated."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE exams
        SET "Name" = ?,
            "Description" = ?,
            "Total marks" = ?,
            "Status" = ?,
            "Updated at" = ?
        WHERE id = ?
    """, (
        updated_exam.get("Name"),
        updated_exam.get("Description"),
        updated_exam.get("Total marks"),
        updated_exam.get("Status"),
        updated_exam.get("Updated at"),
        exam_id,
    ))

    conn.commit()
    success = cursor.rowcount > 0
    conn.close()

    return success


def delete_exam(exam_id: int) -> bool:
    """Delete an exam by id (its exam_questions links cascade). Returns
    True if a row was deleted."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM exams WHERE id = ?", (exam_id,))

    conn.commit()
    success = cursor.rowcount > 0
    conn.close()

    return success


# ---------------------------------------------------------------------------
# Exam <-> Question links (exam_questions)
# ---------------------------------------------------------------------------
# 单独存"哪场考试用了哪些题"，是 exams 和 questions 之间的多对多关系表。
# 每一行代表"某场考试里的某一道题"，还带两个额外信息：
# Order：这道题在这场考试里排第几
# Marks override：这道题在这场考试里的分值，如果需要跟题库里的默认分值不一样，可以在这里覆盖

def add_question_to_exam(exam_id: int, question_id: int, order: Optional[int] = None,
                          marks_override: Optional[int] = None) -> int:
    """Attach a question to an exam. Returns the new exam_questions row id."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO exam_questions (exam_id, question_id, "Order", "Marks override")
        VALUES (?, ?, ?, ?)
    """, (exam_id, question_id, order, marks_override))

    conn.commit()
    new_id = cursor.lastrowid
    conn.close()

    return new_id


def remove_question_from_exam(exam_id: int, question_id: int) -> bool:
    """Detach a question from an exam. Returns True if a row was deleted."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM exam_questions WHERE exam_id = ? AND question_id = ?",
        (exam_id, question_id),
    )

    conn.commit()
    success = cursor.rowcount > 0
    conn.close()

    return success


def get_exam_questions(exam_id: int):
    """Return the full question rows attached to an exam, in order, each
    annotated with its exam-specific "Marks override" (may be None)."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT q.*, eq."Order" AS "Order", eq."Marks override" AS "Marks override"
        FROM exam_questions eq
        JOIN questions q ON q.id = eq.question_id
        WHERE eq.exam_id = ?
        ORDER BY eq."Order" IS NULL, eq."Order"
    """, (exam_id,))
    rows = cursor.fetchall()

    conn.close()

    return [dict(row) for row in rows]


# Make sure all tables exist as soon as this module is imported.
init_db()