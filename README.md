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

# 6.27 阶段 3：题库列表页面（表格版本）

## 目标

在完成基础题库列表页面后，将题库页面改为表格形式展示，使其更接近实际考试系统的题库页面。

本阶段继续使用 Python list 模拟题目数据，暂时不连接数据库，重点练习 Flask 向 HTML template 传递数据，以及 Jinja2 在页面中循环显示表格内容。

## 功能需求

1. 登录成功后进入 `/questions` 页面。
2. 页面显示当前登录教师。
3. 页面以表格形式显示题库。
4. 每道题显示多个字段，包括：
   - Question
   - Actions
   - Status
   - Version
   - Created by
   - Comments
   - Needs checking?
   - Facility index
   - Discriminative efficiency
   - Usage
   - Last used
   - Modify
5. 当没有题目时显示提示信息。
6. 页面保留 Logout 链接。

## 技术实现

在 `app.py` 中扩展了 `QUESTIONS` 数据结构，由简单的 `id/title/content` 修改为包含多个字段的 dictionary：

```python
QUESTIONS = [
    {
        "Question": "A simple calculation",
        "Actions": "Edit",
        "Status": "Ready",
        "Version": "v1",
        "Created by": "Y Wei 27 June 2026, 21:40pm",
        "Comments": "0",
        "Needs checking?": "Unlikely",
        "Facility index": "100.00%",
        "Discriminative efficiency": "72.00%",
        "Usage": "1",
        "Last used": "Sunday, 25 June 2026, 21:40pm",
        "Modify": "Y Wei 27 June 2026, 21:40pm"
    }
]
```

```
在 `question.html` 中，使用 HTML table 显示题库数据：

页面中也加入了几个占位链接：

```html
<a href="#">Create New Question</a>
<a href="#">Reset Columns</a>
<a href="#">Show question test in the question list?</a>
```

这里的 `href="#"` 表示 placeholder link，目前只是占位，后续再连接真实功能。

## 问题 1：部分字段无法正常显示

原因：

有些 dictionary 的 key 中包含空格或特殊字符，例如：

```python
"Created by"
"Needs checking?"
"Facility index"
"Discriminative efficiency"
"Last used"
```

如果直接写成：

```html
{{ question.Created by }}
```

Jinja2 无法正确解析。

解决方法：

改用 dictionary key 的写法：

```html
{{ question["Created by"] }}
{{ question["Needs checking?"] }}
{{ question["Facility index"] }}
{{ question["Discriminative efficiency"] }}
{{ question["Last used"] }}
```

学习：

我理解了 Jinja2 访问 dictionary 数据有两种方式。

普通 key 可以写：

```html
{{ question.Question }}
```

但如果 key 中有空格或特殊符号，就要写：

```html
{{ question["Created by"] }}
```

## 问题 2：页面需要根据是否有题目决定显示内容

原因：

如果 `QUESTIONS` 为空，页面不应该显示空表格，而应该提示当前没有题目。

解决方法：

使用 Jinja2 的条件判断：

```html
{% if questions %}
```

有数据时显示表格，没有数据时显示：

```html
<p>No questions available.</p>
```

学习：

我理解了 Jinja2 可以用 `{% if %}` 判断后端传来的数据是否为空，从而控制页面显示内容。

## 问题 3：`QUESTIONS` 和 `questions` 的区别

原因：

在 `app.py` 中，后端数据叫：

```python
QUESTIONS
```

但在 HTML 中使用的是：

```html
questions
```

一开始容易混淆为什么 Python 里是大写，HTML 里是小写。

解决方法：

理解 `render_template()` 中的传参关系：

```python
questions=QUESTIONS
```

左边的 `questions` 是传给 HTML 使用的名字。

右边的 `QUESTIONS` 是 Python 里真实的数据变量。

学习：

我理解了：

```python
QUESTIONS
```

是后端 Python 中的变量名；

```html
questions
```

是传到 HTML template 后使用的变量名；

```html
question
```

是 `{% for question in questions %}` 循环中临时表示每一道题的数据。

## 测试记录

### 测试 1：显示题库表格

结果：

页面正确显示多道题目，并展示 Question、Actions、Status、Version、Created by、Comments 等多个字段。

状态：通过

### 测试 2：没有题目时显示提示

操作：

将：

```python
QUESTIONS = []
```

结果：

页面显示：

```text
No questions available.
```

状态：通过

## 今日学习总结

今天完成了题库列表页面的表格展示版本。

相比之前简单显示 `id/title/content`，今天的页面更接近真实考试系统中的题库管理页面。

我主要理解了：

1. Flask 后端如何通过 `render_template()` 把 Python list 传给 HTML。
2. Jinja2 如何使用 `{% if %}` 判断是否有数据。
3. Jinja2 如何使用 `{% for %}` 循环显示多条题目。
4. HTML 表格中 `<table>`、`<thead>`、`<tbody>`、`<tr>`、`<th>`、`<td>` 的作用。
5. dictionary key 如果包含空格或特殊字符，需要使用 `question["key"]` 的方式访问。
6. `href="#"` 是 placeholder link，表示功能暂时占位。