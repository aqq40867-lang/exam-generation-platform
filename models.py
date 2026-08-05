"""
SQLAlchemy ORM models for the exam platform.

These map onto the exact same table/column names the app has always used,
including columns with spaces (e.g. "Created by", "Main question") -- the
Python attribute is a normal lower_snake_case name, but the underlying DB
column keeps its original name via Column("Original Name", ...). This
means the SQLite -> Postgres data migration script doesn't need to rename
or reshape anything, and database.py can convert any model instance back
into a dict keyed by the *original* column names generically (see
`_row_to_dict` below), which is what every page in pages/*.py already
expects (e.g. question.get("Question"), q.get("Module")).
"""

from sqlalchemy import Column, Integer, Text, ForeignKey, UniqueConstraint, event
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Question(Base):
    """A single exam question, optionally split into graded sub-parts."""

    __tablename__ = "questions"

    id = Column(Integer, primary_key=True)
    question = Column("Question", Text, nullable=False)
    main_question = Column("Main question", Text)
    marks = Column("Marks", Integer)
    answer = Column("Answer", Text)
    status = Column("Status", Text)
    version = Column("Version", Integer)
    created_by = Column("Created by", Text)
    created_at = Column("Created at", Text)
    updated_at = Column("Updated at", Text)
    usage = Column("Usage", Integer, default=0)
    module = Column("Module", Text)
    # Free-text knowledge point / topic label (e.g. "Stacks", "Kruskal's
    # Algorithm"), separate from "Question" (which is a short title and
    # often doesn't say what the question is actually about, e.g. a title
    # of "Definitions" gives no hint that it covers stacks). Optional;
    # purely organisational -- shown in the question list/detail pages,
    # never used in the exported PDF.
    topic = Column("Topic", Text)

    parts = relationship(
        "QuestionPart",
        cascade="all, delete-orphan",
        order_by="QuestionPart.order_index",
        passive_deletes=True,
    )


class QuestionPart(Base):
    """Sub-question (a)/(b)/(c)... belonging to a single Question."""

    __tablename__ = "question_parts"

    id = Column(Integer, primary_key=True)
    question_id = Column(Integer, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    label = Column("Label", Text)
    order_index = Column("Order", Integer)
    description = Column("Description", Text)
    marks = Column("Marks", Integer, nullable=False, default=0)
    answer = Column("Answer", Text)
    answer_space = Column("Answer space", Text, nullable=False, default="half")
    # One of four component types (see database.py's replace_question_parts
    # docstring for the full picture):
    #   "text"     -- free-form answer (the original behaviour). Gradable:
    #                 carries "Marks" and a lettered (a)/(b)/(c)... label.
    #   "table"    -- step-by-step/tracing table; `table_spec` holds the
    #                 column/row definition (JSON-encoded). Gradable.
    #   "material" -- a block of reading material/stimulus text (reuses
    #                 `description`), shown inline wherever it sits in the
    #                 component order. Not gradable: no marks, no letter
    #                 label, no answer.
    #   "image"    -- an embedded image (a diagram, graph, screenshot,
    #                 etc.), stored as base64 in `image_data`. Also not
    #                 gradable; `description` doubles as an optional
    #                 caption.
    part_type = Column("Part type", Text, nullable=False, default="text")
    table_spec = Column("Table spec", Text)
    # Base64-encoded raw image bytes for an "image" part, and the original
    # uploaded filename (kept for display/debugging only -- the actual
    # embedded format is sniffed from the bytes themselves at export time,
    # not trusted from this name/extension).
    image_data = Column("Image data", Text)
    image_filename = Column("Image filename", Text)


class User(Base):
    """A login account (teacher or admin) for the exam platform."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column("Username", Text, nullable=False, unique=True)
    password_hash = Column("Password hash", Text, nullable=False)
    salt = Column("Salt", Text, nullable=False)
    role = Column("Role", Text, nullable=False, default="teacher")
    created_at = Column("Created at", Text)
    last_login_at = Column("Last login at", Text)
    protected = Column("Protected", Integer, nullable=False, default=0)


class Exam(Base):
    """An exam paper assembled from a selection of questions."""

    __tablename__ = "exams"

    id = Column(Integer, primary_key=True)
    name = Column("Name", Text, nullable=False)
    description = Column("Description", Text)
    total_marks = Column("Total marks", Integer)
    status = Column("Status", Text, default="Draft")
    created_by = Column("Created by", Text)
    created_at = Column("Created at", Text)
    updated_at = Column("Updated at", Text)


class ExamQuestion(Base):
    """Which questions belong to which exam, in what order, with an
    optional per-exam marks override. Many-to-many link table between
    exams and questions."""

    __tablename__ = "exam_questions"
    __table_args__ = (UniqueConstraint("exam_id", "question_id"),)

    id = Column(Integer, primary_key=True)
    exam_id = Column(Integer, ForeignKey("exams.id", ondelete="CASCADE"), nullable=False)
    question_id = Column(Integer, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    order_index = Column("Order", Integer)
    marks_override = Column("Marks override", Integer)


class TeacherModule(Base):
    """Which course modules a teacher is allowed to author questions for
    (assigned by an admin on the User Management page)."""

    __tablename__ = "teacher_modules"
    __table_args__ = (UniqueConstraint("Username", "Module"),)

    id = Column(Integer, primary_key=True)
    username = Column("Username", Text, nullable=False)
    module = Column("Module", Text, nullable=False)


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
    """Turns on SQLite foreign-key enforcement for a newly opened connection.

    Only relevant if this is ever pointed at a SQLite file (e.g. quick
    local testing without a real Postgres instance running). Postgres
    enforces foreign keys by default; SQLite needs this pragma set on
    every new connection or ON DELETE CASCADE silently does nothing.

    Args:
        dbapi_connection: The raw DB-API connection just opened.
        connection_record: SQLAlchemy connection pool record (unused).
    """
    if type(dbapi_connection).__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def _row_to_dict(obj) -> dict:
    """Converts any model instance into a plain dict keyed by DB column names.

    Keys are the *original* DB column names (not the Python attribute
    names), e.g. {"id": 1, "Question": "...", "Main question": ...,
    "Module": "CO923"}. This is what makes every page in pages/*.py (which
    does question.get("Question"), q.get("Module") etc.) keep working
    unmodified against the ORM-backed database.py.

    Uses the ORM mapper (not obj.__table__.columns directly) because a
    Core Column's own .key defaults to its DB column name ("Question"),
    not the Python attribute name ("question") -- the mapper is what
    actually knows the attribute-name <-> DB-column-name pairing.

    Args:
        obj: A model instance (e.g. a Question or User), or None.

    Returns:
        A dict of DB column name to value, or None if `obj` is None.
    """
    if obj is None:
        return None
    mapper = sa_inspect(obj).mapper
    return {prop.columns[0].name: getattr(obj, prop.key) for prop in mapper.column_attrs}
