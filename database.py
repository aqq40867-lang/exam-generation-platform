"""
SQLAlchemy/Postgres-backed data layer for the exam platform.

This used to be hand-written SQLite queries (see git history). It's now
built on the ORM models in models.py, talking to Postgres by default --
but every public function here still takes/returns exactly the same
shapes (plain dicts keyed by the original column names, e.g. "Question",
"Main question", "Created by") as before, so none of the pages/*.py files
needed to change.

Connection: reads DATABASE_URL from the environment (see docker-compose.yml
for the value used when running via Docker). Falls back to a local
Postgres instance on localhost for running the app directly without
Docker (you'll need Postgres installed and a matching database/role
created yourself in that case).
"""

import os
import hashlib
import secrets
import string
from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy import create_engine, func, or_
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError

from models import (
    Base,
    Question,
    QuestionPart,
    User,
    Exam,
    ExamQuestion,
    TeacherModule,
    _row_to_dict,
)

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://exam_platform:exam_platform@localhost:5432/exam_platform",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)


def get_session():
    """Open a new ORM session. Callers are responsible for closing it
    (mirrors the old sqlite get_connection()/conn.close() pattern used
    throughout this file -- every function below opens one session, does
    its work, and closes it, rather than sharing a long-lived session)."""
    return SessionLocal()


def init_db():
    """Create all tables if they don't exist yet, then run one-time data
    migrations that clean up historically bad data.

    Unlike the old SQLite version, there's no hand-rolled "does this
    column exist yet, if not ALTER TABLE" logic here: Base.metadata.create_all()
    creates the full current schema (as defined in models.py) on a fresh
    database, and is a safe no-op on one that already has the tables.
    """
    Base.metadata.create_all(engine)

    session = get_session()
    try:
        # Migration: normalize existing "Module" casing to uppercase.
        # Module codes were previously stored exactly as typed, so the
        # same module could end up as "25COP923" (typed by an admin
        # assigning it) and "25cop923" (typed earlier on a question) --
        # two different strings that don't match anywhere they're
        # compared (the question list's Module filter, the create/edit
        # dropdown, teacher_modules lookups). Safe to run on every
        # startup; a no-op once everything is already uppercase.
        for q in session.query(Question).filter(Question.module.isnot(None)):
            normalized = _normalize_module(q.module)
            if q.module != normalized:
                q.module = normalized

        # teacher_modules has a UNIQUE(username, module) constraint, so a
        # plain uppercase-in-place update could collide if a teacher was
        # ever assigned both "25cop923" and "25COP923". Walk each
        # teacher's rows (oldest first) and drop later duplicates instead.
        usernames = [
            row[0] for row in session.query(TeacherModule.username).distinct()
        ]
        for uname in usernames:
            rows = (
                session.query(TeacherModule)
                .filter(TeacherModule.username == uname)
                .order_by(TeacherModule.id.asc())
                .all()
            )
            seen = set()
            for row in rows:
                normalized = _normalize_module(row.module)
                if not normalized or normalized in seen:
                    session.delete(row)
                else:
                    seen.add(normalized)
                    row.module = normalized

        # Migration: some question_parts rows have a garbage "Answer
        # space" value (e.g. a bare number) instead of 'half'/'full' --python database.py
        # likely from data written before the 'half'/'full' convention
        # existed, or edited directly. latex_export.py calls .strip() on
        # this value when building the exported PDF, so anything that
        # isn't already a valid string crashes the export with no
        # visible error to the user. Normalize invalid values to 'half'.
        session.query(QuestionPart).filter(
            or_(
                QuestionPart.answer_space.is_(None),
                ~QuestionPart.answer_space.in_(["half", "full"]),
            )
        ).update({QuestionPart.answer_space: "half"}, synchronize_session=False)

        session.commit()
    finally:
        session.close()


def _normalize_module(module) -> Optional[str]:
    """Normalize a course module code to a single consistent case (upper)
    and strip surrounding whitespace, so the same module always compares
    and displays equal regardless of who typed it or when (e.g. "25cop923"
    vs "25COP923" are the same module). Returns None for blank/missing
    input. Used by every code path that writes a Module value."""
    if module is None:
        return None
    module = str(module).strip().upper()
    return module or None


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


def create_user(username: str, password: str, role: str = "teacher", protected: bool = False) -> Optional[int]:
    """Create a new user with a hashed password. Returns new id, or None if
    the username is already taken.

    `protected=True` marks this as a top-level admin account: its role can
    never be changed and the account can never be deleted through the app
    (see `update_user_role` / `delete_user`), guaranteeing there's always at
    least one admin who can manage everyone else's role."""
    session = get_session()

    password_hash, salt = _hash_password(password)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        user = User(
            username=username,
            password_hash=password_hash,
            salt=salt,
            role=role,
            created_at=now,
            protected=1 if protected else 0,
        )
        session.add(user)
        session.commit()
        new_id = user.id
    except IntegrityError:
        session.rollback()
        new_id = None
    finally:
        session.close()

    return new_id


def get_user_by_username(username: str):
    """Return a single user as a dict, or None if it doesn't exist."""
    session = get_session()
    try:
        user = session.query(User).filter(User.username == username).first()
        return _row_to_dict(user)
    finally:
        session.close()


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

    session = get_session()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        db_user = session.query(User).filter(User.id == user["id"]).first()
        db_user.last_login_at = now
        session.commit()
    finally:
        session.close()

    return {
        "id": user["id"],
        "Username": user["Username"],
        "Role": user["Role"],
        "Created at": user["Created at"],
        "Last login at": now,
    }


def update_user_password(username: str, new_password: str) -> bool:
    """Reset a user's password. Returns True if a row was updated."""
    session = get_session()
    try:
        user = session.query(User).filter(User.username == username).first()
        if not user:
            return False
        password_hash, salt = _hash_password(new_password)
        user.password_hash = password_hash
        user.salt = salt
        session.commit()
        return True
    finally:
        session.close()


def update_user_role(username: str, new_role: str) -> bool:
    """Change a user's role. Returns True if a row was updated.

    Refuses (returns False, no-op) if the account is protected -- a
    protected account's role is permanently locked as whatever it was
    created with (always "admin" in practice), so it can't be demoted by
    another admin, accidentally or otherwise."""
    session = get_session()
    try:
        user = (
            session.query(User)
            .filter(User.username == username, User.protected == 0)
            .first()
        )
        if not user:
            return False
        user.role = new_role
        session.commit()
        return True
    finally:
        session.close()


def delete_user(username: str) -> bool:
    """Delete a user by username. Returns True if a row was deleted.

    Refuses (returns False, no-op) if the account is protected."""
    session = get_session()
    try:
        user = (
            session.query(User)
            .filter(User.username == username, User.protected == 0)
            .first()
        )
        if not user:
            return False
        session.delete(user)
        session.commit()
        return True
    finally:
        session.close()


def is_protected_user(username: str) -> bool:
    """Return True if this account's role/existence is locked (see
    `update_user_role` / `delete_user`)."""
    session = get_session()
    try:
        user = session.query(User).filter(User.username == username).first()
        return bool(user and user.protected)
    finally:
        session.close()


def list_users():
    """Return all users (without password hash/salt) as a list of dicts.

    Protected accounts (the top-level admin) are sorted first, so they
    always show up at the top of the User Management list regardless of
    when they were created; everyone else follows in creation order."""
    session = get_session()
    try:
        rows = (
            session.query(User)
            .order_by(User.protected.desc(), User.id.asc())
            .all()
        )
        result = []
        for u in rows:
            d = _row_to_dict(u)
            d.pop("Password hash", None)
            d.pop("Salt", None)
            result.append(d)
        return result
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Questions（题库）
# ---------------------------------------------------------------------------
# 存单个题目本身：题干、主问题、分值、答案、状态、版本、创建人等。
# 一道题创建一次，可以被反复复用到不同的考试里，跟"考试"没有直接关系。

def load_questions():
    """Return all questions as a list of dicts."""
    session = get_session()
    try:
        return [_row_to_dict(q) for q in session.query(Question).all()]
    finally:
        session.close()


def get_question(question_id: int):
    """Return a single question as a dict, or None if it doesn't exist."""
    session = get_session()
    try:
        q = session.query(Question).filter(Question.id == question_id).first()
        return _row_to_dict(q)
    finally:
        session.close()


def add_question(question: dict) -> int:
    """Insert a new question and return its new id."""
    session = get_session()
    try:
        q = Question(
            question=question.get("Question"),
            main_question=question.get("Main question"),
            marks=question.get("Marks"),
            answer=question.get("Answer"),
            status=question.get("Status"),
            version=question.get("Version"),
            created_by=question.get("Created by"),
            created_at=question.get("Created at"),
            usage=question.get("Usage", 0),
            module=_normalize_module(question.get("Module")),
        )
        session.add(q)
        session.commit()
        return q.id
    finally:
        session.close()


def update_question(question_id: int, updated_question: dict) -> bool:
    """Update an existing question. Returns True if a row was updated."""
    session = get_session()
    try:
        q = session.query(Question).filter(Question.id == question_id).first()
        if not q:
            return False
        q.question = updated_question.get("Question")
        q.main_question = updated_question.get("Main question")
        q.marks = updated_question.get("Marks")
        q.answer = updated_question.get("Answer")
        q.status = updated_question.get("Status")
        q.version = updated_question.get("Version")
        q.created_by = updated_question.get("Created by")
        q.created_at = updated_question.get("Created at")
        q.updated_at = updated_question.get("Updated at")
        q.usage = updated_question.get("Usage", 0)
        q.module = _normalize_module(updated_question.get("Module"))
        session.commit()
        return True
    finally:
        session.close()


def delete_question(question_id: int) -> bool:
    """Delete a question by id. Returns True if a row was deleted."""
    session = get_session()
    try:
        q = session.query(Question).filter(Question.id == question_id).first()
        if not q:
            return False
        session.delete(q)
        session.commit()
        return True
    finally:
        session.close()


def list_modules():
    """Return a sorted list of the distinct, non-empty course modules
    ("Module", e.g. "CO923") already used across all questions.

    Used to populate the module dropdown/combobox on the create/edit forms
    and the filter dropdown on the question list page.
    """
    session = get_session()
    try:
        rows = (
            session.query(Question.module)
            .filter(Question.module.isnot(None), func.trim(Question.module) != "")
            .distinct()
            .order_by(func.lower(Question.module))
            .all()
        )
        return [r[0] for r in rows]
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Teacher <-> Module assignments (teacher_modules)
# ---------------------------------------------------------------------------
# Which course modules a teacher is allowed to author questions for. This is
# assigned by admins (User Management page); the create/edit question pages
# then restrict a teacher's Module dropdown to only these, so teachers can't
# type an arbitrary course code themselves.

def get_teacher_modules(username: str):
    """Return the sorted list of modules a teacher has been assigned."""
    session = get_session()
    try:
        rows = (
            session.query(TeacherModule.module)
            .filter(TeacherModule.username == username)
            .order_by(func.lower(TeacherModule.module))
            .all()
        )
        return [r[0] for r in rows]
    finally:
        session.close()


def set_teacher_modules(username: str, modules: list) -> None:
    """Replace the full set of modules assigned to a teacher with `modules`
    (a list of strings). Blank/duplicate entries are ignored."""
    session = get_session()
    try:
        session.query(TeacherModule).filter(TeacherModule.username == username).delete()

        seen = set()
        for module in modules:
            module = _normalize_module(module)
            if not module or module in seen:
                continue
            seen.add(module)
            session.add(TeacherModule(username=username, module=module))

        session.commit()
    finally:
        session.close()


def list_all_assignable_modules():
    """Return a sorted list of every module code known to the system so far
    (already used on a question, or already assigned to some teacher), to
    use as suggestions when an admin assigns modules to a teacher."""
    session = get_session()
    try:
        from_questions = (
            session.query(Question.module)
            .filter(Question.module.isnot(None), func.trim(Question.module) != "")
            .distinct()
            .all()
        )
        from_teachers = session.query(TeacherModule.module).distinct().all()
        all_modules = {r[0] for r in from_questions} | {r[0] for r in from_teachers}
        return sorted(all_modules, key=str.lower)
    finally:
        session.close()


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
    session = get_session()
    try:
        rows = (
            session.query(QuestionPart)
            .filter(QuestionPart.question_id == question_id)
            .order_by(QuestionPart.order_index.is_(None), QuestionPart.order_index)
            .all()
        )
        return [_row_to_dict(p) for p in rows]
    finally:
        session.close()


def replace_question_parts(question_id: int, parts: list) -> int:
    """Replace all sub-questions belonging to `question_id` with `parts`.

    `parts` is a list of dicts, each with (at least) "Description" (may be
    empty/None), "Marks" (int), "Answer" (the sub-question's standard
    answer) and "Answer space" ('half' or 'full' -- how much blank space to
    reserve for the student's answer on the exported paper; 'full' forces a
    page break so the answer gets a whole page to itself), in the desired
    display order. Labels ((a), (b), (c)...) are (re)assigned automatically
    from the list order, so callers never need to manage labels themselves.

    The parent question's "Marks" column is then set to the sum of the
    parts' marks (this is the auto total-marks calculation) and the new
    total is returned. If `parts` is empty, the parent's "Marks" is left
    untouched and 0 is returned.
    """
    session = get_session()
    try:
        session.query(QuestionPart).filter(QuestionPart.question_id == question_id).delete()

        total_marks = 0
        for order, part in enumerate(parts):
            marks = int(part.get("Marks") or 0)
            total_marks += marks
            answer_space = part.get("Answer space")
            session.add(QuestionPart(
                question_id=question_id,
                label=_label_for_index(order),
                order_index=order,
                description=part.get("Description"),
                marks=marks,
                answer=part.get("Answer"),
                answer_space=answer_space if answer_space in ("half", "full") else "half",
            ))

        if parts:
            q = session.query(Question).filter(Question.id == question_id).first()
            if q:
                q.marks = total_marks

        session.commit()
        return total_marks
    finally:
        session.close()


def delete_question_parts(question_id: int) -> None:
    """Delete all sub-questions for a main question (also happens
    automatically via ON DELETE CASCADE when the question itself is
    deleted, but exposed here for explicit use, e.g. converting a
    multi-part question back into a plain one)."""
    session = get_session()
    try:
        session.query(QuestionPart).filter(QuestionPart.question_id == question_id).delete()
        session.commit()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Exams
# ---------------------------------------------------------------------------
# 存一场考试的整体信息：
# 名字、说明、总分、状态（草稿/发布）、创建人等。它本身不包含具体题目内容，只是一个"壳"。

def load_exams():
    """Return all exams as a list of dicts."""
    session = get_session()
    try:
        return [_row_to_dict(e) for e in session.query(Exam).all()]
    finally:
        session.close()


def get_exam(exam_id: int):
    """Return a single exam as a dict, or None if it doesn't exist."""
    session = get_session()
    try:
        e = session.query(Exam).filter(Exam.id == exam_id).first()
        return _row_to_dict(e)
    finally:
        session.close()


def add_exam(exam: dict) -> int:
    """Insert a new exam and return its new id."""
    session = get_session()
    try:
        e = Exam(
            name=exam.get("Name"),
            description=exam.get("Description"),
            total_marks=exam.get("Total marks"),
            status=exam.get("Status", "Draft"),
            created_by=exam.get("Created by"),
            created_at=exam.get("Created at"),
        )
        session.add(e)
        session.commit()
        return e.id
    finally:
        session.close()


def update_exam(exam_id: int, updated_exam: dict) -> bool:
    """Update an existing exam. Returns True if a row was updated."""
    session = get_session()
    try:
        e = session.query(Exam).filter(Exam.id == exam_id).first()
        if not e:
            return False
        e.name = updated_exam.get("Name")
        e.description = updated_exam.get("Description")
        e.total_marks = updated_exam.get("Total marks")
        e.status = updated_exam.get("Status")
        e.updated_at = updated_exam.get("Updated at")
        session.commit()
        return True
    finally:
        session.close()


def delete_exam(exam_id: int) -> bool:
    """Delete an exam by id (its exam_questions links cascade). Returns
    True if a row was deleted."""
    session = get_session()
    try:
        e = session.query(Exam).filter(Exam.id == exam_id).first()
        if not e:
            return False
        session.delete(e)
        session.commit()
        return True
    finally:
        session.close()


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
    session = get_session()
    try:
        eq = ExamQuestion(
            exam_id=exam_id,
            question_id=question_id,
            order_index=order,
            marks_override=marks_override,
        )
        session.add(eq)
        session.commit()
        return eq.id
    finally:
        session.close()


def remove_question_from_exam(exam_id: int, question_id: int) -> bool:
    """Detach a question from an exam. Returns True if a row was deleted."""
    session = get_session()
    try:
        deleted = (
            session.query(ExamQuestion)
            .filter(ExamQuestion.exam_id == exam_id, ExamQuestion.question_id == question_id)
            .delete()
        )
        session.commit()
        return deleted > 0
    finally:
        session.close()


def get_exam_questions(exam_id: int):
    """Return the full question rows attached to an exam, in order, each
    annotated with its exam-specific "Marks override" (may be None)."""
    session = get_session()
    try:
        rows = (
            session.query(Question, ExamQuestion)
            .join(ExamQuestion, ExamQuestion.question_id == Question.id)
            .filter(ExamQuestion.exam_id == exam_id)
            .order_by(ExamQuestion.order_index.is_(None), ExamQuestion.order_index)
            .all()
        )
        result = []
        for question, eq in rows:
            d = _row_to_dict(question)
            d["Order"] = eq.order_index
            d["Marks override"] = eq.marks_override
            result.append(d)
        return result
    finally:
        session.close()


# Make sure all tables exist as soon as this module is imported.
init_db()


if __name__ == "__main__":
    # Running "python database.py" directly is a quick way to (re)create
    # tables and re-run the data migrations against DATABASE_URL without
    # starting the full app -- init_db() already ran above via the import,
    # this just gives visible confirmation instead of exiting silently.
    print(f"Connected to: {DATABASE_URL}")
    table_names = sorted(Base.metadata.tables.keys())
    print(f"Tables ready: {', '.join(table_names)}")
    print("init_db() completed successfully (tables created + migrations applied).")
