# Exam Platform

A lightweight web application for teachers to create, manage, and organize exam questions. Built with [NiceGUI](https://nicegui.io/) and backed by Postgres (via SQLAlchemy).

## Overview

Exam Platform lets a logged-in teacher create question entries (title, question text, marks, and answer), track their status and version, and browse them in a searchable table. Each teacher only sees and manages the questions they created, so multiple teachers can safely use the same instance without seeing each other's content.

Key features:

- Simple username/password login
- Create, view, edit, and delete questions
- Draft/version tracking for each question
- Per-user question list — private to the account that created it
- Actions (View / Edit / Delete) available directly from a dropdown menu in the question table
- Data stored in Postgres (SQLAlchemy ORM data layer)

## Who Is This For

- **Teachers / instructors** who want a simple internal tool to draft and organize exam questions before publishing them into a larger exam system.
- **Students / developers** using this as a learning project to practice full-stack development with Python, NiceGUI, and SQLite.
- Anyone who wants a small, self-hosted, dependency-light question bank without setting up a cloud database.

This project is intended for small-scale, personal, or educational use (e.g., a single classroom or small team), not for large multi-tenant production deployments.

## Project Structure

```
.
├── app.py                          # Entry point — defines routes/pages
├── models.py                       # SQLAlchemy ORM models (the schema)
├── database.py                     # Data layer (CRUD functions, built on models.py)
├── migrate_sqlite_to_postgres.py   # One-time script: import old exam_platform.db into Postgres
├── pages/
│   ├── login.py             # Login page
│   ├── question_list.py     # Question list + dropdown actions
│   ├── question_detail.py   # Question detail view
│   ├── create_question.py   # Create new question form
│   └── edit_question.py     # Edit existing question form
├── requirements.txt        # Python dependencies
├── Dockerfile               # Container build instructions
└── docker-compose.yml       # Container run configuration (app + Postgres)
```

## Getting Started

You can run this project either directly with Python, or with Docker (no local Python setup required).

### Option 1: Run with Python

**Requirements:** Python 3.9+, and a Postgres server you can connect to (local install, or any hosted Postgres).

1. Clone the project:
   ```bash
   git clone <your-repo-url>
   cd <project-folder>
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Point the app at your Postgres database. Set the `DATABASE_URL` environment variable (`postgresql://user:password@host:port/dbname`) before running, e.g. on Windows PowerShell:
   ```powershell
   $env:DATABASE_URL = "postgresql://exam_platform:exam_platform@localhost:5432/exam_platform"
   ```
   If `DATABASE_URL` isn't set, it defaults to `postgresql://exam_platform:exam_platform@localhost:5432/exam_platform` (matching the Docker setup below).
4. Run the app:
   ```bash
   python app.py
   ```
   Tables are created automatically on first run (via `init_db()`).
5. Open your browser at [http://localhost:8080](http://localhost:8080)

**Upgrading from an old SQLite install?** If you have an existing `exam_platform.db` with real data in it, run the one-time migration script *once*, after Postgres is reachable and before you start using the app for real:
```bash
python migrate_sqlite_to_postgres.py
```
It copies every table over (questions, users, exams, etc.) preserving all IDs and relationships. See the comment at the top of the script for details.

### Option 2: Run with Docker

**Requirements:** [Docker Desktop](https://www.docker.com/products/docker-desktop/) (free for personal, educational, and small business use)

1. Clone the project:
   ```bash
   git clone <your-repo-url>
   cd <project-folder>
   ```
2. Build and start both containers (the app and a Postgres database):
   ```bash
   docker compose up --build
   ```
   Add `-d` to run it in the background:
   ```bash
   docker compose up -d
   ```
3. Open your browser at [http://localhost:8080](http://localhost:8080)
4. To stop the app:
   ```bash
   docker compose down
   ```
   (This stops the containers but keeps the Postgres data, which lives in a named Docker volume. Use `docker compose down -v` if you really want to wipe it.)

With Docker, you don't need to install Python, Postgres, or any dependencies on the host machine — everything runs inside the containers.

**Upgrading from an old SQLite install?** Start just the database first, run the migration script against it from your host machine, then start the app:
```bash
docker compose up -d postgres
$env:DATABASE_URL = "postgresql://exam_platform:exam_platform@localhost:5432/exam_platform"  # PowerShell
python migrate_sqlite_to_postgres.py
docker compose up -d
```

## Data Persistence

All data is stored in Postgres. When running via Docker, it lives in a named Docker volume (`pgdata`) that survives `docker compose down` / rebuilds; only `docker compose down -v` removes it. When running Postgres yourself outside Docker, back it up the way you'd back up any Postgres database (e.g. `pg_dump`).

## Viewing the Database (pgAdmin)

`docker-compose.yml` includes a pgAdmin service — a web-based GUI for browsing the Postgres tables (questions, users, exams, etc.) without needing to install anything separately or write SQL by hand.

1. Start it (this also starts Postgres if it isn't already running):
   ```bash
   docker compose up -d pgadmin
   ```
2. Open [http://localhost:5050](http://localhost:5050) and log in:
   - Email: `admin@example.com`
   - Password: `admin`
3. First time only — register the database server: right-click **Servers** in the left sidebar → **Register** → **Server...**
   - **General** tab: Name — anything you like, e.g. `exam-platform`
   - **Connection** tab:
     - Host name/address: `postgres` (the Docker service name — not `localhost`, since pgAdmin talks to Postgres over the internal Docker network)
     - Port: `5432`
     - Maintenance database: `exam_platform`
     - Username: `exam_platform`
     - Password: `exam_platform`
   - Click **Save**.
4. Browse the data: expand **Servers → exam-platform → Databases → exam_platform → Schemas → public → Tables**, right-click any table → **View/Edit Data → All Rows**.

The pgAdmin login (`admin@example.com` / `admin`) and the Postgres credentials (`exam_platform` / `exam_platform`) are placeholder defaults suitable for local/internal use — change them in `docker-compose.yml` if this ever runs somewhere less trusted.

## License

This project is provided as-is for educational purposes.
