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
    # JSON-encoded ordered list of content blocks (same {"type": "text"/
    # "image"/"table", ...} shape as QuestionPart.content_blocks -- see
    # that column's docstring) for the question's overall problem
    # statement/stimulus, shown above the lettered sub-problems. Lets the
    # Create/Edit Question pages' "2. Problem" section use the same
    # text/image/table block editor a sub-problem's own content uses,
    # instead of being limited to plain text. `main_question` above is
    # still kept in sync as a best-effort plain-text summary (every text
    # block's text, joined) purely for older code paths that only know
    # about that flat field; this column is the source of truth for
    # rendering once it's set. NULL for rows saved before this feature
    # existed, or for a question with no problem statement at all (it's
    # optional, unlike a sub-problem's own content) -- database.py's
    # get_question()/load_questions() fall back to synthesizing a single
    # text block from `main_question` when this is NULL but that isn't,
    # so an old row's problem text still shows up when reopened for
    # editing.
    main_content_blocks = Column("Main content blocks", Text)
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
    # Every part is a lettered, gradable "sub-problem" -- (a)/(b)/(c)...
    # -- made up of a description plus any combination of an attached
    # image and/or an attached table (see create_question.py's sub-problem
    # editor). "Part type" is "text" or "table" depending on whether a
    # table is attached; it no longer gates whether an image can be
    # attached -- `image_data` may be set on either type.
    #
    # Legacy values "material" (non-gradable stimulus text block) and
    # "image" (non-gradable standalone image) can still appear on rows
    # written by older versions of this app; database.py and
    # latex_export.py still know how to read/render them, but
    # create_question.py no longer creates new ones -- an image is now
    # always attached to a "text"/"table" sub-problem instead of being its
    # own unlettered component.
    #   "text"     -- free-form answer. Gradable: carries "Marks" and a
    #                 lettered (a)/(b)/(c)... label. Optionally has an
    #                 attached image (`image_data`).
    #   "table"    -- step-by-step/tracing table. Gradable, same labelling
    #                 as "text". `table_spec` holds the *problem* table
    #                 (what the student sees) and `answer_table_spec`
    #                 holds the *answer* table (shown only in the
    #                 solutions export) -- two independent JSON-encoded
    #                 column/row definitions, not one table with masked
    #                 columns. Optionally has an attached image too.
    #   "material" -- (legacy) a block of reading material/stimulus text
    #                 (reuses `description`), not gradable: no marks, no
    #                 letter label, no answer.
    #   "image"    -- (legacy) a standalone embedded image, not gradable;
    #                 `description` doubles as an optional caption.
    part_type = Column("Part type", Text, nullable=False, default="text")
    table_spec = Column("Table spec", Text)
    # The model-answer counterpart to `table_spec`: same
    # {"given_columns", "answer_columns", "rows"} shape, but fully filled
    # in with the correct answers. Rendered instead of `table_spec` only
    # in "solutions" mode. None for "text" parts (and for "table" parts
    # that haven't had their answer table filled in yet).
    answer_table_spec = Column("Answer table spec", Text)
    # Base64-encoded raw image bytes for an attached image, and the
    # original uploaded filename (kept for display/debugging only -- the
    # actual embedded format is sniffed from the bytes themselves at
    # export time, not trusted from this name/extension). May be set
    # regardless of `part_type`.
    image_data = Column("Image data", Text)
    image_filename = Column("Image filename", Text)
    # JSON-encoded ordered list of *content blocks* -- the current, richer
    # replacement for the fixed "one description, then one image, then one
    # table" layout above. Each block is
    # {"type": "text", "text": str} |
    # {"type": "image", "image_data": base64 str, "image_filename": str} |
    # {"type": "table", "table_spec": {...}, "answer_table_spec": {...}}
    # (same {"given_columns", "answer_columns", "rows"} shape as
    # `table_spec`/`answer_table_spec` above), in whatever order the
    # teacher arranged them in -- e.g. text, then a diagram, then more
    # text, then a tracing table, letting a sub-problem's image and extra
    # instructions sit between two paragraphs instead of always after all
    # of the text. May hold any number of blocks of each type.
    #
    # This column is nullable so old rows (written before this feature
    # existed) don't need a data migration: database.py's
    # get_question_parts() synthesizes an equivalent blocks list on the
    # fly from `description`/`image_data`/`table_spec` when this is NULL.
    # `description`, `image_data`, `image_filename`, `table_spec`, and
    # `answer_table_spec` are still kept in sync on every save (see
    # database.py's replace_question_parts) as best-effort single-value
    # summaries -- concatenated text, first image, first table -- purely
    # so older code paths that only know about those columns (e.g.
    # edit_question.py's "can this question be edited here" check) keep
    # working; `content_blocks` is the source of truth for rendering.
    content_blocks = Column("Content blocks", Text)
    # JSON-encoded ordered list of *sub-parts* -- the third numbering level,
    # (i)/(ii)/(iii)... nested inside this (a)/(b)/(c)... sub-problem, for
    # questions whose sub-problems are themselves broken down further (see
    # create_question.py's sub-parts editor). Each entry has exactly the
    # same shape create_question.py's _build_part_dict() already produces
    # for a top-level part -- "Label" (here a lower-case Roman numeral,
    # e.g. "i"), "Content blocks", "Marks", "Answer space", "Part type",
    # "Table spec", "Answer table spec", "Answer", "Image data", "Image
    # filename" -- but never itself carries a further "Sub parts" (the
    # UI caps nesting at this one extra level: 1./2./3. -> (a)(b)(c) ->
    # (i)(ii)(iii), no deeper).
    #
    # When a sub-problem has any sub-parts, its own "Marks" column is the
    # sum of its sub-parts' marks (mirroring how the parent question's
    # "Marks" is the sum of its sub-problems' marks) and its own
    # "Answer"/"Answer space" are unused -- each sub-part carries its own.
    # NULL/empty for the (still overwhelmingly common) case of a
    # sub-problem with no further breakdown.
    sub_parts = Column("Sub parts", Text)


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


class TeacherTopic(Base):
    """A reusable Topic / Knowledge Point label a teacher has created.

    Offered as select-or-add choices on the create/edit question pages'
    Topic field (see create_question.py / edit_question.py), scoped to
    the teacher who created them -- mirrors TeacherModule's shape, but
    unlike modules (assigned by an admin), a teacher creates their own
    topic labels freely while authoring a question. A row here persists
    independently of whether any question currently uses that Topic, so
    a label a teacher has used before stays selectable even after the
    last question using it is deleted or edited to use a different one.
    """

    __tablename__ = "teacher_topics"
    __table_args__ = (UniqueConstraint("Username", "Topic"),)

    id = Column(Integer, primary_key=True)
    username = Column("Username", Text, nullable=False)
    topic = Column("Topic", Text, nullable=False)


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
