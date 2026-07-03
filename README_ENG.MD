# Development Log 001 — Login Function

## Date
2026-06-26

## Development Goal
The first development goal was to build a basic login function for the exam question bank platform.

The system should allow teacher users to enter a username and password. If the credentials are correct, the user should be redirected to the question bank page. If the credentials are incorrect, the user should remain on the login page and see an error message.

The system should also prevent unauthenticated users from directly accessing the question list page.

## Functional Requirements
1. Display a login page with username and password input fields.
2. Predefine two teacher accounts for the first prototype.
3. Validate user input when the login form is submitted.
4. Redirect valid users to the question bank page.
5. Show an error message for invalid login attempts.
6. Use Flask session to store login status.
7. Redirect unauthenticated users back to the login page when they try to access the question list page.
8. Provide a logout function to clear the session.

## Technical Implementation
This stage was implemented using Flask.

The `/login` route handles both GET and POST requests. A GET request displays the login form, while a POST request receives the submitted username and password.

Two test accounts were stored in a Python dictionary. This approach was chosen because the first prototype focuses on authentication flow rather than database design.

Flask session was used to store the login state:

- `session['logged_in'] = True`
- `session['username'] = username`

The `/questions` route checks whether the user is logged in before displaying the question bank page. If the session does not contain a valid login state, the system redirects the user back to `/login`.

The `/logout` route clears the session and redirects the user to the login page.

## Problems Encountered
One issue occurred when redirecting the user after successful login.

The code originally used:

```python
return redirect(url_for('question'))

# Development Log 002 — Question List Page

## Date

2026-06-26

## Development Goal

The second development goal was to build a basic question list page after the login function was completed.

After a teacher logs in successfully, the system should redirect the user to the `/questions` page and display a list of questions.

At this stage, no database is used. The question data is temporarily stored in a Python list for prototype testing.

## Functional Requirements

1. Redirect authenticated users to the question list page after login.
2. Display the current logged-in username on the question page.
3. Display a list of questions.
4. Show each question’s id, title, and content.
5. Prevent unauthenticated users from directly accessing `/questions`.
6. Provide a logout link to clear the session.

## Technical Implementation

A temporary `QUESTIONS` list was created in `app.py`.

Each question is stored as a Python dictionary with three fields:

* `id`
* `title`
* `content`

The `/questions` route checks the session before rendering the page. If the user is not logged in, the system redirects the user back to `/login`.

If the user is logged in, Flask passes both the username and the question list to the template:

```python
return render_template(
    'question.html',
    username=session.get('username'),
    questions=QUESTIONS
)
```

The `question.html` template uses a Jinja2 for loop to display each question:

```html
{% for question in questions %}
    <li>
        <strong>{{ question.id }}. {{ question.title }}</strong>
        <p>{{ question.content }}</p>
    </li>
{% endfor %}
```

## Problems Encountered

### Problem 1: The question list was not displayed

The template contained a loop:

```html
{% for question in questions %}
```

However, the backend did not initially pass the `questions` variable into the template.

The original route only passed the username:

```python
return render_template('question.html', username=session.get('username'))
```

As a result, the HTML page did not receive the question data, so the list could not be displayed.

### Solution

The `questions=QUESTIONS` argument was added to `render_template()`:

```python
return render_template(
    'question.html',
    username=session.get('username'),
    questions=QUESTIONS
)
```

### Learning

I learned that Flask templates cannot automatically access Python variables from `app.py`.

Data must be explicitly passed from the route function to the HTML template using `render_template()`.

---

### Problem 2: Only id and title were displayed, but content was missing

The reason was that the HTML template only contained:

```html
{{ question.id }}. {{ question.title }}
```

Therefore, only the id and title were shown.

### Solution

The content field was added to the template:

```html
<p>{{ question.content }}</p>
```

### Learning

I learned that a template only displays the fields that are explicitly written in the HTML.

Even if the Python dictionary contains more fields, they will not appear on the page unless they are referenced in the template.

## Testing Record

### Test 1: Successful login and redirect

Input:

```text
username = teacher1
password = 123456
```

Result:
The user was successfully redirected to `/questions`.

Status: Passed

### Test 2: Display username

Result:
The question page displayed the logged-in username.

Status: Passed

### Test 3: Display question list

Result:
The page displayed multiple questions with id, title, and content.

Status: Passed

### Test 4: Protect question page

Action:
Accessed `/questions` without logging in.

Result:
The system redirected the user back to `/login`.

Status: Passed

### Test 5: Logout

Action:
Clicked the Logout link.

Result:
The session was cleared and the user returned to `/login`.

Status: Passed

## Summary

Today I completed the second stage of the prototype: the question list page.

I learned how Flask passes data from the backend to the frontend template, how Jinja2 loops through a list, and why each displayed field must be written explicitly in the HTML template.

The current system now supports:

1. Login
2. Session-based access control
3. Logout
4. Displaying a basic question list after login


# Development Log 003 — Question List Table

## Date

2026-06-27

## Development Goal

After completing the basic question list page, the next goal was to redesign it as a table so that it more closely resembles a real exam question bank system.

At this stage, the application still stores question data in a Python list rather than a database. The main objective was to practice passing data from Flask to an HTML template and displaying it dynamically using Jinja2.

## Functional Requirements

1. Redirect users to `/questions` after successful login.
2. Display the logged-in username.
3. Display the question bank as a table.
4. Display the following fields for each question:

   * Question
   * Actions
   * Status
   * Version
   * Created by
   * Comments
   * Needs checking?
   * Facility index
   * Discriminative efficiency
   * Usage
   * Last used
   * Modify
5. Display a message when no questions are available.
6. Keep the Logout link.

## Technical Implementation

The temporary `QUESTIONS` data structure in `app.py` was expanded from a simple dictionary into a more realistic question record containing multiple fields.

The `question.html` template was redesigned using an HTML table.

Several placeholder links were also added for future features:

```html
<a href="#">Create New Question</a>
<a href="#">Reset Columns</a>
<a href="#">Show question text in the question list?</a>
```

The `href="#"` value is used as a placeholder link. The actual functionality will be implemented in a later stage.

## Problems Encountered

### Problem 1: Some fields could not be displayed correctly

Some dictionary keys contain spaces or special characters, for example:

```python
"Created by"
"Needs checking?"
"Facility index"
"Discriminative efficiency"
"Last used"
```

Using dot notation such as:

```html
{{ question.Created by }}
```

caused Jinja2 to fail because these keys are not valid attribute names.

### Solution

Dictionary indexing was used instead:

```html
{{ question["Created by"] }}
{{ question["Needs checking?"] }}
{{ question["Facility index"] }}
{{ question["Discriminative efficiency"] }}
{{ question["Last used"] }}
```

### Learning

I learned that Jinja2 provides two ways to access dictionary values.

For normal keys, dot notation can be used:

```html
{{ question.Question }}
```

However, when a key contains spaces or special characters, bracket notation must be used:

```html
{{ question["Created by"] }}
```

---

### Problem 2: Display different content when no questions exist

If the `QUESTIONS` list is empty, the page should not display an empty table.

### Solution

A Jinja2 conditional statement was added:

```html
{% if questions %}
```

If the list contains data, the table is displayed.

Otherwise, the page displays:

```html
<p>No questions available.</p>
```

### Learning

I learned that Jinja2 conditional statements can control what is rendered on the page depending on whether data exists.

---

### Problem 3: Understanding the difference between `QUESTIONS`, `questions`, and `question`

At first, it was confusing that the Python code used `QUESTIONS`, while the HTML template used `questions` and `question`.

### Solution

The relationship became clear after understanding how `render_template()` passes variables:

```python
questions=QUESTIONS
```

* `QUESTIONS` is the Python variable that stores all question data.
* `questions` is the variable name available inside the HTML template.
* `question` represents one individual question during each iteration of the Jinja2 `for` loop.

### Learning

I learned that Flask does not automatically expose Python variables to HTML templates.

The backend variable must first be passed into `render_template()`, and the template can then iterate through it using a Jinja2 loop.

## Testing Record

### Test 1: Display question table

Result:

The page successfully displayed multiple questions in a table, including Question, Actions, Status, Version, Created by, Comments, and the remaining fields.

Status: Passed

### Test 2: Display message when no questions exist

Action:

```python
QUESTIONS = []
```

Result:

The page displayed:

```text
No questions available.
```

Status: Passed

## Summary

Today I completed the third stage of the prototype by upgrading the question list page from a simple list to a structured table.

During this stage, I learned:

1. How Flask passes a Python list to an HTML template using `render_template()`.
2. How Jinja2 uses `{% if %}` to conditionally display content.
3. How Jinja2 uses `{% for %}` to iterate through multiple question records.
4. The purpose of HTML table elements such as `<table>`, `<thead>`, `<tbody>`, `<tr>`, `<th>`, and `<td>`.
5. That dictionary keys containing spaces or special characters must be accessed using `question["key"]`.
6. That `href="#"` is a placeholder link used before the actual functionality is implemented.

# 6.28 Stage 4: Create Question Page

## Objective

Implement the **Create Question** feature based on the existing Question List page.

After clicking **Create New Question**, users can open a form, enter question information, and save it.

Once the question is saved, the system writes the new question to `questions.json` and redirects the user back to the Question List page.

---

## Functional Requirements

1. Provide a **Create New Question** link on the Question List page.
2. Navigate to `/questions/new` after clicking the link.
3. Display a question creation form.
4. The form includes:

   * Question Title
   * Main Question Text
5. Read `questions.json` when the user clicks **Save**.
6. Add the new question to the question bank.
7. Save the updated data back to `questions.json`.
8. Redirect to the Question List page after saving.

---

## Technical Implementation

At this stage, the project starts using `questions.json` to store question data instead of relying on a hard-coded Python list.

Import the JSON module in `app.py`:

```python
import json
```

Define the question file:

```python
QUESTIONS_FILE = "questions.json"
```

Create a function to load question data:

```python
def load_questions():
    with open(QUESTIONS_FILE, "r", encoding="utf-8") as file:
        return json.load(file)
```

Create a function to save question data:

```python
def save_questions(questions):
    with open(QUESTIONS_FILE, "w", encoding="utf-8") as file:
        json.dump(questions, file, indent=4, ensure_ascii=False)
```

Add a new route for creating questions:

```python
@app.route("/questions/new", methods=["GET", "POST"])
def create_question():
```

A **GET** request displays the Create Question page.

A **POST** request performs the following steps:

1. Read `questions.json`.
2. Create a new question dictionary.
3. Append the new question to the question list.
4. Save the updated JSON file.
5. Redirect to the Question List page.

The Create Question page uses an HTML form:

```html
<form method="POST">
```

The form submits user input to the Flask backend.

---

## Issue 1: Why change `questions=QUESTIONS`?

### Cause

Previously, the question data was stored in a hard-coded Python list:

```python
QUESTIONS
```

After implementing the Create Question feature, newly created questions are saved to:

```text
questions.json
```

If the Question List page still uses:

```python
questions=QUESTIONS
```

the page will always display the old hard-coded data, and newly created questions will never appear.

### Learning

I learned that there are now two different data sources.

`QUESTIONS` is a static Python list, while `questions.json` stores the latest question data.

To display the newest questions, the Question List page should load data from `questions.json` instead of the original Python list.

---

## Issue 2: The saved data structure did not match the Question List

### Cause

Initially, the Create Question page saved data like this:

```python
{
    "title": "...",
    "main_text": "...",
    "page_size": "..."
}
```

However, the Question List page expected fields such as:

```html
{{ question.Question }}
{{ question.Actions }}
{{ question.Status }}
```

Because the field names were different, the saved questions could not be displayed correctly.

### Solution

Update the saved data structure to match the table:

```python
new_question = {
    "Question": request.form["title"],
    "Actions": "Edit",
    "Status": "Ready",
    "Version": "v1",
    "Created by": session["username"],
    "Comments": "0",
    "Needs checking?": "Unlikely",
    "Facility index": "100.00%",
    "Discriminative efficiency": "72.00%",
    "Usage": "0",
    "Last used": "Never",
    "Modify": session["username"]
}
```

### Learning

I learned that the backend data structure must match the fields expected by the frontend template.

If the HTML template reads:

```html
{{ question.Question }}
```

then the JSON file must also contain the field:

```json
"Question": "..."
```

Otherwise, the data cannot be displayed correctly.

---

## Test Results

### Test 1: Open the Create Question page

**Action**

Click **Create New Question**.

**Result**

The browser successfully navigates to:

```text
/questions/new
```

**Status**

Passed

---

### Test 2: Display the Create Question form

**Result**

The page displays:

* Question Title
* Main Question Text

**Status**

Passed

---

### Test 3: Save a new question

**Action**

Fill in the form and click **Save**.

**Result**

The new question is successfully added to:

```text
questions.json
```

**Status**

Passed

---

### Test 4: Redirect after saving

**Result**

After saving, the system automatically redirects to:

```text
/questions
```

**Status**

Passed

---

### Test 5: Display the new question

**Result**

The newly created question appears in the Question List.

**Status**

Passed

---

## Learning Summary

Today I completed the basic Create Question feature and started using `questions.json` to store question data, providing simple data persistence for the application.

Compared with the previous implementation that used a fixed Python list, the system can now save user input dynamically and display newly created questions in the Question List.

Today I learned:

1. **GET** requests are used to display a page, while **POST** requests are used to submit form data.
2. Flask uses `request.form` to retrieve data submitted from an HTML form.
3. `json.load()` reads data from a JSON file.
4. `json.dump()` writes Python data back to a JSON file.
5. `questions.append(new_question)` adds a new question to the question bank.
6. `url_for()` generates URLs based on Flask route function names.
7. The Question List page should load data from `questions.json` instead of a hard-coded Python list.
8. The data structure saved by the backend must match the fields expected by the frontend template.

# 7.3 Stage 5: Question Detail Page

## Objective

After completing the Create Question feature, implement the Question Detail page.

Users should be able to click a question title in the Question List and view the complete information for that question. This page will also serve as the foundation for future features such as Edit, Preview, and History.

---

## Functional Requirements

1. Click a question title to open the Question Detail page.
2. Find the corresponding question using `question_id`.
3. Display the following information:
   - Question
   - Main Question
   - Marks
   - Answer
   - Created by
   - Created at
4. Provide a **Back to Question List** button.

---

## Technical Implementation

A new route was added to `app.py`:

```python
@app.route("/questions/<int:question_id>")
def question_detail(question_id):
```

When a user opens the page, the application:

1. Checks whether the user is logged in.
2. Loads `questions.json`.
3. Searches for the question using `question_id`.
4. Passes the matched question to:

```python
render_template("question_detail.html")
```

The detail page displays all information about the selected question.

---

The Question List page was updated so that each question title becomes a hyperlink:

```html
<a href="{{ url_for('question_detail', question_id=question['id']) }}">
    {{ question["Question"] }}
</a>
```

This enables navigation from the Question List page to the Question Detail page.

---

## Issue 1: BuildError - Could not build url for endpoint 'question_detail'

### Cause

The template called:

```python
url_for("question_detail")
```

However, no corresponding route existed in `app.py`.

### Solution

Added the following route:

```python
@app.route("/questions/<int:question_id>")
def question_detail(question_id):
```

### Learning

I learned that `url_for()` can only generate URLs for existing Flask endpoints. If the endpoint does not exist, Flask raises a `BuildError` while rendering the template.

---

## Issue 2: NameError - datatime is not defined

### Cause

The code used:

```python
datatime.now()
```

instead of:

```python
datetime.now()
```

### Solution

Imported the module correctly:

```python
from datetime import datetime
```

Then updated the code to:

```python
datetime.now().strftime("%Y-%m-%d %H:%M")
```

### Learning

I learned that `datetime` is both a module and a class in Python. A spelling mistake results in a `NameError`.

---

## Issue 3: NameError - json is not defined

### Cause

The application used:

```python
json.load()
```

without importing the `json` module.

### Solution

Added:

```python
import json
```

at the beginning of `app.py`.

### Learning

Python modules must be imported before they can be used.

---

## Issue 4: UndefinedError - 'dict object' has no attribute 'id'

### Cause

The template accessed:

```html
question.id
```

However, `question` is a Python dictionary rather than an object.

In addition, some existing records in `questions.json` did not contain an `"id"` field.

### Solution

Updated the template to use:

```html
question["id"]
```

Also updated `load_questions()` to automatically assign IDs to old records:

```python
for index, question in enumerate(questions):
    if "id" not in question:
        question["id"] = index + 1
```

### Learning

I learned that dictionary values in Jinja2 are more reliably accessed using:

```html
question["id"]
question["Question"]
```

instead of dot notation.

---

## Testing

### Test 1: Open Question List

**Result**

Successfully displayed the Question List page after login.

**Status:** Passed

---

### Test 2: Open Question Detail

**Action**

Click a question title.

**Result**

Successfully navigated to the Question Detail page.

**Status:** Passed

---

### Test 3: Display Question Information

**Result**

The page correctly displayed:

- Question
- Main Question
- Marks
- Answer
- Created by
- Created at

**Status:** Passed

---

### Test 4: Return to Question List

**Action**

Click **Back to Question List**.

**Result**

Successfully returned to:

```
/questions
```

**Status:** Passed

---

## Learning Summary

Today I completed the Question Detail page and successfully connected the Question List page with the Question Detail page.

Key concepts I learned include:

1. How Flask passes URL parameters using `question_id`.
2. How to retrieve a specific record from `questions.json`.
3. How `url_for()` works with Flask routes.
4. The recommended way to access dictionary values in Jinja2 using `question["key"]`.
5. The importance of correctly importing Python modules such as `json` and `datetime`.
6. How to maintain compatibility with older JSON data by automatically adding missing fields.