# 6.25 阶段 1：登录功能

## 目标：
实现一个基础登录系统，使教师用户可以通过 username 和 password 登录系统。
登录成功后进入题库列表页面。
登录失败时停留在登录页面并显示错误信息。
未登录用户不能直接访问题库页面。

## 功能需求：
1. 用户可以看到 username 和 password 输入框。
2. 系统预置两个测试教师账号。
3. 用户输入正确账号后进入题库页面。
4. 用户输入错误账号后显示错误提示。
5. 系统使用 Flask session 保存登录状态。
6. 未登录用户访问 /questions 时会被重定向到 /login。

## 技术实现：
本阶段使用 Flask 实现后端路由。
使用 HTML template 创建登录页面和题库页面。
使用 Flask session 保存用户登录状态。
使用 redirect 和 url_for 控制页面跳转。
目前用户账号暂时存储在 Python dictionary 中，方便一期原型测试。

## 问题 1：登录成功后无法正确跳转到题库页面。

原因：
在 app.py 中，登录成功后使用了 url_for('question')，但实际定义的路由函数名是 question_list。
Flask 的 url_for() 需要使用函数名，而不是页面文件名或随便写的名字。

解决方法：
将 return redirect(url_for('question')) 修改为 return redirect(url_for('question_list'))。

学习：
我理解了 Flask 中 endpoint 默认等于路由函数名。url_for() 不是根据 URL 地址查找，而是根据函数名生成 URL。

## 测试记录：

测试 1：正确登录
输入：
username = teacher1
password = 123456
结果：
成功跳转到 /questions 页面。
状态：通过

测试 2：错误登录
输入：
username = teacher1
password = wrongpassword
结果：
停留在 /login 页面，并显示 Invalid Credentials. Please try again.
状态：通过

测试 3：未登录访问题库页面
操作：
直接访问 /questions
结果：
系统自动跳转回 /login。
状态：通过

测试 4：退出登录
操作：
点击 Logout
结果：
session 被清除，页面返回 /login。
状态：通过

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


可以。你今天的进度可以写成下面这样，风格和你前面的 **Development Log 001** 保持一致。

# 6.26 阶段 2：题库列表页面

## 目标：

在完成登录功能后，实现一个基础题库列表页面。

用户登录成功后可以进入 `/questions` 页面，并看到当前系统中的题目列表。
未登录用户仍然不能直接访问题库页面，需要先登录。

本阶段暂时不连接数据库，题目数据先存储在 Python list 中，用于验证页面展示和 Flask 数据传递流程。

## 功能需求：

1. 用户登录成功后进入 `/questions` 页面。
2. `/questions` 页面显示欢迎信息。
3. 页面显示题目列表。
4. 每道题显示 id、title 和 content。
5. 未登录用户访问 `/questions` 时仍然会被重定向到 `/login`。
6. 页面提供 Logout 链接，用户可以退出登录。

## 技术实现：

本阶段继续使用 Flask 实现后端路由。

在 `app.py` 中新增一个 `QUESTIONS` 列表，用于暂时保存题目数据：

```python
QUESTIONS = [
    {
        "id": 1,
        "title": "Python 基础题",
        "content": "Explain what a variable is in Python."
    },
    {
        "id": 2,
        "title": "数据库 SQL 题",
        "content": "Write a SQL query to select all students."
    },
    {
        "id": 3,
        "title": "Flask 登录题",
        "content": "Explain how Flask session works."
    }
]
```

在 `/questions` 路由中，系统会先检查用户是否已经登录：

```python
if not session.get('logged_in'):
    return redirect(url_for('login'))
```

如果用户已经登录，则通过 `render_template()` 将用户名和题目列表传递给 HTML 页面：

```python
return render_template(
    'question.html',
    username=session.get('username'),
    questions=QUESTIONS
)
```

在 `question.html` 中，使用 Jinja2 的 for 循环显示题目列表：

```html
<ul>
    {% for question in questions %}
        <li>
            <strong>{{ question.id }}. {{ question.title }}</strong>
            <p>{{ question.content }}</p>
        </li>
    {% endfor %}
</ul>
```

## 问题 1：题目列表不显示

原因：
HTML 页面中写了：

```html
{% for question in questions %}
```

但是 `app.py` 中最开始只传入了 `username`，没有把 `QUESTIONS` 传给模板。

原代码类似：

```python
return render_template('question.html', username=session.get('username'))
```

所以 HTML 页面虽然写了循环，但是没有收到 `questions` 数据，因此无法显示题目。

解决方法：
在 `render_template()` 中增加：

```python
questions=QUESTIONS
```

修改后：

```python
return render_template(
    'question.html',
    username=session.get('username'),
    questions=QUESTIONS
)
```

学习：
我理解了 Flask 后端需要主动把数据传给 HTML template。
HTML 不能直接访问 Python 变量，必须通过 `render_template()` 传递。

## 问题 2：只显示 id 和 title，不显示 content

原因：
HTML 里原本只写了：

```html
{{ question.id }}. {{ question.title }}
```

所以页面只会显示 id 和 title，不会自动显示 content。

解决方法：
在 HTML 中增加：

```html
<p>{{ question.content }}</p>
```

同时确保 `QUESTIONS` 中每一道题都有 `content` 字段。

学习：
我理解了 template 中显示什么字段，取决于 HTML 里写了哪些变量。
Flask 不会自动显示 dictionary 里的所有内容，需要手动写出：

```html
{{ question.id }}
{{ question.title }}
{{ question.content }}
```

## 测试记录：

测试 1：登录后进入题库页面
输入正确账号：

```text
username = teacher1
password = 123456
```

结果：
成功跳转到 `/questions` 页面。
状态：通过

测试 2：显示欢迎信息
结果：
页面显示当前登录用户，例如：

```text
Welcome, teacher1.
```

状态：通过

测试 3：显示题目列表
结果：
页面显示多道题目，包括题目 id、title 和 content。
状态：通过

测试 4：未登录访问 `/questions`
操作：
清除 session 后直接访问 `/questions`。

结果：
系统自动跳转回 `/login`。
状态：通过

测试 5：退出登录
操作：
点击 Logout。

结果：
session 被清除，页面返回 `/login`。
状态：通过

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
