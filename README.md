# Exam Platform

A lightweight web application for teachers to create, manage, and organize exam questions. Built with [NiceGUI](https://nicegui.io/) and backed by a simple SQLite database.

## Overview

Exam Platform lets a logged-in teacher create question entries (title, question text, marks, and answer), track their status and version, and browse them in a searchable table. Each teacher only sees and manages the questions they created, so multiple teachers can safely use the same instance without seeing each other's content.

Key features:

- Simple username/password login
- Create, view, edit, and delete questions
- Draft/version tracking for each question
- Per-user question list — private to the account that created it
- Actions (View / Edit / Delete) available directly from a dropdown menu in the question table
- Data stored locally in a single SQLite file — no external database or account required

## Who Is This For

- **Teachers / instructors** who want a simple internal tool to draft and organize exam questions before publishing them into a larger exam system.
- **Students / developers** using this as a learning project to practice full-stack development with Python, NiceGUI, and SQLite.
- Anyone who wants a small, self-hosted, dependency-light question bank without setting up a cloud database.

This project is intended for small-scale, personal, or educational use (e.g., a single classroom or small team), not for large multi-tenant production deployments.

## Project Structure

```
.
├── app.py                 # Entry point — defines routes/pages
├── database.py             # SQLite data layer (CRUD functions)
├── pages/
│   ├── login.py             # Login page
│   ├── question_list.py     # Question list + dropdown actions
│   ├── question_detail.py   # Question detail view
│   ├── create_question.py   # Create new question form
│   └── edit_question.py     # Edit existing question form
├── requirements.txt        # Python dependencies
├── Dockerfile               # Container build instructions
├── docker-compose.yml       # Container run configuration
└── exam_platform.db         # SQLite database file (created automatically)
```

## Getting Started

You can run this project either directly with Python, or with Docker (no local Python setup required).

### Option 1: Run with Python

**Requirements:** Python 3.9+

1. Clone the project:
   ```bash
   git clone <your-repo-url>
   cd <project-folder>
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the app:
   ```bash
   python app.py
   ```
4. Open your browser at [http://localhost:8080](http://localhost:8080)

The SQLite database file (`exam_platform.db`) is created automatically on first run.

### Option 2: Run with Docker

**Requirements:** [Docker Desktop](https://www.docker.com/products/docker-desktop/) (free for personal, educational, and small business use)

1. Clone the project:
   ```bash
   git clone <your-repo-url>
   cd <project-folder>
   ```
2. Build and start the container:
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

With Docker, you don't need to install Python or any dependencies on the host machine — everything runs inside the container.

## Data Persistence

All question data is stored in `exam_platform.db`, a single SQLite file created in the project directory. This file is not tracked by git by default — back it up manually (or add it to version control) if you want to preserve your data across machines.

## License

This project is provided as-is for educational purposes.
