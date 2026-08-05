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
import json
import secrets
import string
from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy import create_engine, func, or_, text
from sqlalchemy import inspect as sa_inspect
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
    """Opens a new SQLAlchemy ORM session.

    Mirrors the old sqlite get_connection()/conn.close() pattern used
    throughout this file: every function below opens one session, does
    its work, and closes it, rather than sharing a long-lived session.
    Callers are responsible for closing the returned session.

    Returns:
        A new SQLAlchemy Session bound to the module's engine.
    """
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

    # Migration: add "Part type" / "Table spec" to question_parts if this
    # is an existing database from before the "table"-type sub-question
    # feature existed -- create_all() only creates missing *tables*, not
    # missing *columns* on a table that's already there (see the
    # docstring above), so a question_parts table created by an older
    # version of this app needs these two columns bolted on explicitly.
    # Safe to run on every startup; a no-op once both columns exist.
    inspector = sa_inspect(engine)
    if "question_parts" in inspector.get_table_names():
        existing_columns = {col["name"] for col in inspector.get_columns("question_parts")}
        with engine.begin() as conn:
            if "Part type" not in existing_columns:
                conn.execute(text(
                    "ALTER TABLE question_parts ADD COLUMN \"Part type\" TEXT NOT NULL DEFAULT 'text'"
                ))
            if "Table spec" not in existing_columns:
                conn.execute(text('ALTER TABLE question_parts ADD COLUMN "Table spec" TEXT'))
            if "Image data" not in existing_columns:
                conn.execute(text('ALTER TABLE question_parts ADD COLUMN "Image data" TEXT'))
            if "Image filename" not in existing_columns:
                conn.execute(text('ALTER TABLE question_parts ADD COLUMN "Image filename" TEXT'))

    # Migration: add "Topic" to questions if this is an existing database
    # from before the topic/knowledge-point field existed. Same
    # create_all()-only-creates-missing-tables caveat as above.
    if "questions" in inspector.get_table_names():
        existing_question_columns = {col["name"] for col in inspector.get_columns("questions")}
        if "Topic" not in existing_question_columns:
            with engine.begin() as conn:
                conn.execute(text('ALTER TABLE questions ADD COLUMN "Topic" TEXT'))

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
    """Normalizes a course module code to a single consistent case.

    Uppercases the value and strips surrounding whitespace, so the same
    module always compares and displays equal regardless of who typed it
    or when (e.g. "25cop923" vs "25COP923" are the same module). Used by
    every code path that writes a Module value.

    Args:
        module: The raw module code, or None/blank.

    Returns:
        The normalized (uppercase, trimmed) module code, or None if
        `module` is missing or blank.
    """
    if module is None:
        return None
    module = str(module).strip().upper()
    return module or None


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def _hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    """Hashes a password with PBKDF2-HMAC-SHA256.

    A fresh random salt is generated when one isn't supplied (i.e. when
    creating a new user). The same salt must be passed back in to verify
    a password later.

    Args:
        password: The plaintext password to hash.
        salt: Hex-encoded salt to reuse (e.g. when verifying an existing
            user's password). A new random salt is generated if omitted.

    Returns:
        A (password_hash_hex, salt_hex) tuple.
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
    """Creates a new user in the `users` table with a hashed password.

    `protected=True` marks this as a top-level admin account: its role can
    never be changed and the account can never be deleted through the app
    (see `update_user_role` / `delete_user`), guaranteeing there's always at
    least one admin who can manage everyone else's role.

    Args:
        username: The new account's unique username.
        password: The new account's plaintext password (hashed before
            storage).
        role: The account's role, e.g. "teacher" or "admin".
        protected: Whether this account's role/existence should be locked
            (see `update_user_role` / `delete_user`).

    Returns:
        The new user's id, or None if `username` is already taken.
    """
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
    """Fetches a single user from the `users` table by username.

    Args:
        username: The username to look up.

    Returns:
        The user as a dict, or None if it doesn't exist.
    """
    session = get_session()
    try:
        user = session.query(User).filter(User.username == username).first()
        return _row_to_dict(user)
    finally:
        session.close()


def authenticate_user(username: str, password: str):
    """Checks a username/password combination against the `users` table.

    Updates "Last login at" on success.

    Args:
        username: The username to authenticate.
        password: The plaintext password to verify.

    Returns:
        The user dict (password fields excluded) on success, else None.
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
    """Resets a user's password in the `users` table.

    Args:
        username: The username whose password should be reset.
        new_password: The new plaintext password (hashed before storage).

    Returns:
        True if a row was updated, False if no such user exists.
    """
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


def update_user_role(username: str, new_role: str, actor_username: Optional[str] = None) -> bool:
    """Changes a user's role in the `users` table.

    Refuses (returns False, no-op) if the account is protected -- a
    protected account's role is permanently locked as whatever it was
    created with (always "admin" in practice), so it can't be demoted by
    another admin, accidentally or otherwise.

    Also refuses if `actor_username` (the user *performing* the change,
    supplied by the caller -- this function has no notion of "who's
    logged in" on its own) equals `username`: nobody can change their own
    role, even an admin. This exists as a backend-enforced guard in
    addition to the admin_users.py page already hiding the control for
    your own row -- the point is that this is the authoritative check, not
    just a UI nicety that a direct call could bypass. Without it, an admin
    demoting themselves would leave their own already-open session's
    cached role stale until they happened to log out and back in (see the
    matching "re-verify from DB" notes in admin_users.py / question_list.py
    for the other half of that problem).

    Args:
        username: The username whose role should change.
        new_role: The role to assign, e.g. "teacher" or "admin".
        actor_username: The username of whoever is performing the change.
            If it equals `username`, the change is refused.

    Returns:
        True if a row was updated, False if no such user exists, the
        account is protected, or the actor is changing their own role.
    """
    if actor_username is not None and actor_username == username:
        return False

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
    """Deletes a user from the `users` table by username.

    Refuses (returns False, no-op) if the account is protected.

    Args:
        username: The username to delete.

    Returns:
        True if a row was deleted, False if no such user exists or the
        account is protected.
    """
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
    """Checks whether a user account is protected.

    Args:
        username: The username to check.

    Returns:
        True if the account's role/existence is locked (see
        `update_user_role` / `delete_user`), False otherwise (including
        if the user doesn't exist).
    """
    session = get_session()
    try:
        user = session.query(User).filter(User.username == username).first()
        return bool(user and user.protected)
    finally:
        session.close()


def list_users():
    """Lists all users in the `users` table, without password hash/salt.

    Protected accounts (the top-level admin) are sorted first, so they
    always show up at the top of the User Management list regardless of
    when they were created; everyone else follows in creation order.

    Returns:
        A list of user dicts, each with "Password hash" and "Salt"
        omitted.
    """
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
    """Lists every row in the `questions` table.

    Returns:
        A list of question dicts.
    """
    session = get_session()
    try:
        return [_row_to_dict(q) for q in session.query(Question).all()]
    finally:
        session.close()


def get_question(question_id: int):
    """Fetches a single question from the `questions` table by id.

    Args:
        question_id: The question's primary key.

    Returns:
        The question as a dict, or None if it doesn't exist.
    """
    session = get_session()
    try:
        q = session.query(Question).filter(Question.id == question_id).first()
        return _row_to_dict(q)
    finally:
        session.close()


def add_question(question: dict) -> int:
    """Inserts a new row into the `questions` table.

    Args:
        question: A dict of question fields (e.g. "Question",
            "Main question", "Marks", "Answer", "Status", "Version",
            "Created by", "Created at", "Usage", "Module", "Topic"),
            keyed by the same column names used elsewhere in this file.

    Returns:
        The new question's id.
    """
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
            topic=(question.get("Topic") or "").strip() or None,
        )
        session.add(q)
        session.commit()
        return q.id
    finally:
        session.close()


def update_question(question_id: int, updated_question: dict) -> bool:
    """Updates an existing row in the `questions` table.

    Args:
        question_id: The question's primary key.
        updated_question: A dict of the new question fields (see
            `add_question` for the expected keys).

    Returns:
        True if a row was updated, False if no such question exists.
    """
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
        q.topic = (updated_question.get("Topic") or "").strip() or None
        session.commit()
        return True
    finally:
        session.close()


def delete_question(question_id: int) -> bool:
    """Deletes a row from the `questions` table by id.

    Args:
        question_id: The question's primary key.

    Returns:
        True if a row was deleted, False if no such question exists.
    """
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
    """Lists every distinct course module already used on a question.

    Used to populate the module dropdown/combobox on the create/edit forms
    and the filter dropdown on the question list page.

    Returns:
        A sorted list of distinct, non-empty "Module" values (e.g.
        "CO923") from the `questions` table.
    """
    session = get_session()
    try:
        # NOTE: sorted in Python, not via .order_by(func.lower(...)) --
        # Postgres rejects a SELECT DISTINCT query whose ORDER BY
        # expression isn't the exact same expression that's selected
        # ("ORDER BY expressions must appear in select list"). SQLite is
        # lenient about this, which is why this only surfaces once the app
        # runs against real Postgres.
        rows = (
            session.query(Question.module)
            .filter(Question.module.isnot(None), func.trim(Question.module) != "")
            .distinct()
            .all()
        )
        return sorted((r[0] for r in rows), key=str.lower)
    finally:
        session.close()


def list_topics(username: str):
    """Lists every distinct "Topic" value already used by one teacher.

    "Topic" is a free-text field (not a controlled list), so this exists
    purely to power an autocomplete suggestion list on the create/edit
    forms -- it keeps a teacher from typing "Stack" on one question and
    "Stacks" on another purely by accident, without forcing a rigid
    taxonomy on them.

    Args:
        username: The teacher whose own questions ("Created by") should
            be scanned for topics.

    Returns:
        A sorted list of distinct, non-empty "Topic" values.
    """
    session = get_session()
    try:
        # See the matching NOTE in list_modules() -- same Postgres
        # DISTINCT + ORDER BY restriction, sorted in Python instead.
        rows = (
            session.query(Question.topic)
            .filter(
                Question.created_by == username,
                Question.topic.isnot(None),
                func.trim(Question.topic) != "",
            )
            .distinct()
            .all()
        )
        return sorted((r[0] for r in rows), key=str.lower)
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
    """Lists the modules a teacher has been assigned in `teacher_modules`.

    Args:
        username: The teacher's username.

    Returns:
        A sorted list of module code strings.
    """
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
    """Replaces a teacher's assigned modules in `teacher_modules`.

    Args:
        username: The teacher's username.
        modules: The full list of module codes the teacher should be
            assigned. Blank/duplicate entries are ignored.
    """
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
    """Lists every module code known to the system so far.

    Includes modules already used on a question, or already assigned to
    some teacher, for use as suggestions when an admin assigns modules to
    a teacher.

    Returns:
        A sorted list of distinct module code strings.
    """
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
    """Converts a 0-based index into a UK-style lower-case letter label.

    E.g. 0 -> 'a', 1 -> 'b', ..., 25 -> 'z', 26 -> 'aa', etc. Displayed in
    the UI wrapped in parentheses, e.g. "(a)".

    Args:
        index: The 0-based position of the sub-question.

    Returns:
        The letter label for that position.
    """
    letters = string.ascii_lowercase
    label = ""
    index += 1
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        label = letters[remainder] + label
    return label


def get_question_parts(question_id: int):
    """Lists all sub-questions belonging to a main question, in order.

    Each dict includes "Part type" ("text", "table", "material", or
    "image") and, for "table" parts, "Table spec" -- decoded back from
    JSON into a plain dict/list structure (see replace_question_parts'
    docstring for its shape). "Table spec" is None for every other type.
    "material"/"image" parts have "Label" as None (they aren't lettered
    sub-questions) and "Marks" forced to 0.

    Args:
        question_id: The parent question's primary key.

    Returns:
        A list of question-part dicts, ordered by "order_index".
    """
    session = get_session()
    try:
        rows = (
            session.query(QuestionPart)
            .filter(QuestionPart.question_id == question_id)
            .order_by(QuestionPart.order_index.is_(None), QuestionPart.order_index)
            .all()
        )
        parts = []
        for p in rows:
            d = _row_to_dict(p)
            raw_spec = d.get("Table spec")
            d["Table spec"] = json.loads(raw_spec) if raw_spec else None
            parts.append(d)
        return parts
    finally:
        session.close()


_GRADABLE_PART_TYPES = ("text", "table")
_NON_GRADABLE_PART_TYPES = ("material", "image")
_ALL_PART_TYPES = _GRADABLE_PART_TYPES + _NON_GRADABLE_PART_TYPES


def replace_question_parts(question_id: int, parts: list) -> int:
    """Replaces all sub-questions belonging to `question_id` with `parts`.

    Applies `parts` in the desired display order.

    `parts` is a list of dicts. Every part carries "Part type" -- one of:

        "text"     -- a gradable sub-question. "Description" (may be
                      empty/None), "Marks" (int), "Answer" (its standard
                      answer), and "Answer space" ('half' or 'full' -- how
                      much blank space to reserve on the exported paper;
                      'full' forces a page break) all apply as before.

        "table"    -- a gradable step-by-step/tracing sub-question.
                      "Marks" applies; "Table spec" is a plain dict shaped
                      like:
                          {
                              "given_columns": ["Step", "Edge", "Weight"],
                              "answer_columns": ["Taken?", "Current MST edges"],
                              "rows": [["1", "P-R", "3", "Yes", "P-R"], ...],
                          }
                      "given_columns" are shown filled-in on every export
                      (information the student is given); "answer_columns"
                      are left blank on the official/example paper and
                      filled in on the solutions export. Each row must have
                      len(given_columns) + len(answer_columns) entries,
                      given values first. JSON-encoded before storage (a
                      Postgres Text column, no native JSON column needed).
                      "Answer" is unused -- the row data carries the answer.

        "material" -- a non-gradable block of reading material/stimulus
                      text (from "Description"), shown inline wherever it
                      sits in the order -- not confined to the top of the
                      question like the parent "Main question" field.

        "image"    -- a non-gradable embedded image. "Image data" is the
                      raw image bytes, base64-encoded; "Image filename" is
                      the original uploaded filename (display only --
                      export sniffs the real format from the bytes).
                      "Description" doubles as an optional caption.

    Falls back to "text" if "Part type" is missing/unrecognised.

    Only "text" and "table" parts are lettered (a), (b), (c)... and count
    towards the parent's total marks -- "material"/"image" parts get
    "Label" set to None and "Marks" forced to 0 regardless of what's
    passed in, since they're stimulus content, not something a student
    answers. Callers never need to manage labels themselves; they're
    (re)assigned from the list order, skipping non-gradable parts.

    The parent question's "Marks" column is then set to the sum of the
    (gradable) parts' marks and the new total is returned. If `parts` is
    empty, the parent's "Marks" is left untouched and 0 is returned.

    Args:
        question_id: The parent question's primary key.
        parts: The new list of sub-question dicts, in the desired display
            order (see above for each dict's shape).

    Returns:
        The parent question's new total marks (0 if `parts` is empty).
    """
    session = get_session()
    try:
        session.query(QuestionPart).filter(QuestionPart.question_id == question_id).delete()

        total_marks = 0
        letter_index = 0
        for order, part in enumerate(parts):
            part_type = part.get("Part type") if part.get("Part type") in _ALL_PART_TYPES else "text"
            is_gradable = part_type in _GRADABLE_PART_TYPES

            if is_gradable:
                label = _label_for_index(letter_index)
                letter_index += 1
                marks = int(part.get("Marks") or 0)
            else:
                label = None
                marks = 0
            total_marks += marks

            answer_space = part.get("Answer space")
            table_spec = part.get("Table spec")
            image_data = part.get("Image data")

            session.add(QuestionPart(
                question_id=question_id,
                label=label,
                order_index=order,
                description=part.get("Description"),
                marks=marks,
                answer=part.get("Answer") if part_type == "text" else None,
                answer_space=answer_space if answer_space in ("half", "full") else "half",
                part_type=part_type,
                table_spec=json.dumps(table_spec) if (part_type == "table" and table_spec) else None,
                image_data=image_data if (part_type == "image" and image_data) else None,
                image_filename=part.get("Image filename") if part_type == "image" else None,
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
    """Deletes all sub-questions for a main question.

    This also happens automatically via ON DELETE CASCADE when the
    question itself is deleted, but is exposed here for explicit use,
    e.g. converting a multi-part question back into a plain one.

    Args:
        question_id: The parent question's primary key.
    """
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
    """Lists every row in the `exams` table.

    Returns:
        A list of exam dicts.
    """
    session = get_session()
    try:
        return [_row_to_dict(e) for e in session.query(Exam).all()]
    finally:
        session.close()


def get_exam(exam_id: int):
    """Fetches a single exam from the `exams` table by id.

    Args:
        exam_id: The exam's primary key.

    Returns:
        The exam as a dict, or None if it doesn't exist.
    """
    session = get_session()
    try:
        e = session.query(Exam).filter(Exam.id == exam_id).first()
        return _row_to_dict(e)
    finally:
        session.close()


def add_exam(exam: dict) -> int:
    """Inserts a new row into the `exams` table.

    Args:
        exam: A dict of exam fields ("Name", "Description",
            "Total marks", "Status", "Created by", "Created at").

    Returns:
        The new exam's id.
    """
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
    """Updates an existing row in the `exams` table.

    Args:
        exam_id: The exam's primary key.
        updated_exam: A dict of the new exam fields (see `add_exam` plus
            "Updated at").

    Returns:
        True if a row was updated, False if no such exam exists.
    """
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
    """Deletes a row from the `exams` table by id.

    Its exam_questions links cascade-delete along with it.

    Args:
        exam_id: The exam's primary key.

    Returns:
        True if a row was deleted, False if no such exam exists.
    """
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
    """Attaches a question to an exam via the `exam_questions` link table.

    Args:
        exam_id: The exam's primary key.
        question_id: The question's primary key.
        order: The question's display position within the exam, if any.
        marks_override: An exam-specific marks value overriding the
            question's default "Marks", if any.

    Returns:
        The new exam_questions row id.
    """
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
    """Detaches a question from an exam in the `exam_questions` table.

    Args:
        exam_id: The exam's primary key.
        question_id: The question's primary key.

    Returns:
        True if a row was deleted, False if no such link exists.
    """
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
    """Lists the full question rows attached to an exam, in order.

    Args:
        exam_id: The exam's primary key.

    Returns:
        A list of question dicts, each annotated with "Order" and
        "Marks override" (may be None) from the exam_questions link.
    """
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
