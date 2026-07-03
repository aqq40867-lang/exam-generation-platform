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

# 6.28 阶段 4：创建题目页面

## 目标

在题库列表页面基础上，实现创建题目功能。

用户点击 `Create New Question` 后，可以进入创建题目页面，填写题目信息并保存。

保存后，系统将新题目写入 `questions.json`，然后跳转回题库列表页面。

---

## 功能需求

1. 题库列表页面提供 `Create New Question` 链接。
2. 点击后进入 `/questions/new` 页面。
3. 创建页面显示题目表单。
4. 表单包含：
   - Question title
   - Main question text
5. 点击 Save 后读取 `questions.json`。
6. 将新题目加入题库。
7. 保存更新后的 `questions.json`。
8. 返回题库列表页面。

---

## 技术实现

本阶段开始使用 `questions.json` 保存题库数据，实现简单的数据持久化。

在 `app.py` 中新增：

```python
import json
```

定义题库文件：

```python
QUESTIONS_FILE = "questions.json"
```

创建读取 JSON 的函数：

```python
def load_questions():
    with open(QUESTIONS_FILE, "r", encoding="utf-8") as file:
        return json.load(file)
```

创建保存 JSON 的函数：

```python
def save_questions(questions):
    with open(QUESTIONS_FILE, "w", encoding="utf-8") as file:
        json.dump(questions, file, indent=4, ensure_ascii=False)
```

新增创建题目路由：

```python
@app.route("/questions/new", methods=["GET", "POST"])
def create_question():
```

GET 请求用于显示创建页面。

POST 请求用于：

1. 读取 `questions.json`
2. 创建新的题目 dictionary
3. 加入题库
4. 保存 JSON
5. 返回题库列表页面

创建页面使用 HTML `<form>` 收集数据，并通过：

```html
<form method="POST">
```

提交给 Flask。

---

## 问题 1：为什么 `questions=QUESTIONS` 要修改

### 原因

之前：

```python
QUESTIONS
```

保存的是 Python 中写死的数据。

现在新增题目已经保存到：

```text
questions.json
```

如果继续：

```python
questions=QUESTIONS
```

页面始终显示旧数据，新创建的题目不会显示。

---

## 问题 2：创建页面保存的数据结构和题库列表不一致

### 原因

创建页面最开始保存的是：

```python
{
    "title": "...",
    "main_text": "...",
    "page_size": "..."
}
```

但是题库页面读取的是：

```html
{{ question.Question }}
{{ question.Actions }}
{{ question.Status }}
```

字段名称不一致，因此无法正常显示。

### 解决方法

修改保存的数据结构：


### 学习

我理解了：

HTML 读取什么字段，

JSON 就必须保存什么字段。

前后端的数据结构必须保持一致。

---

## 测试记录

### 测试 1：进入创建页面

操作：

点击：

```
Create New Question
```

结果：

成功进入：

```
/questions/new
```

状态：通过

---

### 测试 2：显示创建表单

结果：

页面显示：

- Question title
- Main question text

状态：通过

---

### 测试 3：保存题目

操作：

填写表单并点击 Save。

结果：

系统成功将题目加入：

```
questions.json
```

状态：通过

---

### 测试 4：返回题库页面

结果：

保存成功后自动跳转：

```
/questions
```

状态：通过

---

### 测试 5：显示新题目

结果：

新创建的题目成功显示在题库列表中。

状态：通过

---

## 今日学习总结

今天完成了创建题目页面的开发，并开始使用 `questions.json` 保存题库数据，实现了简单的数据持久化。

相比之前使用 Python list 保存固定数据，现在系统已经能够根据用户输入动态新增题目，并在页面中显示最新数据。

今天主要理解了：

1. GET 请求用于显示页面，POST 请求用于提交表单。
2. Flask 使用 `request.form` 获取用户输入的数据。
3. 使用 `json.load()` 读取 JSON 文件。
4. 使用 `json.dump()` 保存 Python 数据到 JSON 文件。
5. `questions.append(new_question)` 用于向题库中新增一条记录。
6. `url_for()` 根据路由函数名生成页面跳转地址。
7. Flask 页面展示的数据应该从 JSON 文件读取，而不是继续使用写死的 Python list。
8. 前端页面读取的数据字段必须与后端保存的数据结构保持一致。

# 7.3 阶段 5：Question Detail 页面

## 目标

在创建题目功能完成后，实现 Question Detail 页面。

用户点击题库列表中的题目名称后，可以进入题目详情页面，查看完整题目信息，为后续 Edit、Preview、History 等功能做准备。

---

## 功能需求

1. 点击题目名称进入 Question Detail 页面。
2. 根据 question_id 找到对应题目。
3. 页面显示：
   - Question
   - Main Question
   - Marks
   - Answer
   - Created by
   - Created at
4. 页面提供返回 Question List 按钮。

---

## 技术实现

新增路由：

```python
@app.route("/questions/<int:question_id>")
def question_detail(question_id):
```

进入详情页面时：

1. 判断用户是否登录。
2. 读取 `questions.json`。
3. 根据 `question_id` 查找对应题目。
4. 找到后传递给：

```python
render_template("question_detail.html")
```

页面显示题目详细信息。

---

Question List 页面中，将题目名称修改为：

```html
<a href="{{ url_for('question_detail', question_id=question['id']) }}">
    {{ question["Question"] }}
</a>
```

实现点击题目名称即可进入详情页面。

---

## 问题 1：BuildError：Could not build url for endpoint 'question_detail'

### 原因

页面调用了：

```python
url_for("question_detail")
```

但是 `app.py` 中还没有对应的路由。

### 解决方法

新增：

```python
@app.route("/questions/<int:question_id>")
def question_detail(question_id):
```

### 学习

我理解了：

`url_for()` 只能跳转已经存在的 Flask endpoint。

如果路由不存在，页面在渲染时就会报 `BuildError`。

---

## 问题 2：NameError：datatime is not defined

### 原因

创建题目时写成：

```python
datatime.now()
```

实际上正确名称是：

```python
datetime
```

### 解决方法

导入：

```python
from datetime import datetime
```

修改为：

```python
datetime.now().strftime("%Y-%m-%d %H:%M")
```

### 学习

我理解了：

Python 中 `datetime` 既是模块也是类，拼写错误会导致 `NameError`。

---

## 问题 3：NameError：json is not defined

### 原因

使用：

```python
json.load()
```

但是没有：

```python
import json
```

### 解决方法

在文件顶部加入：

```python
import json
```

### 学习

Python 使用模块之前必须先 import，否则解释器无法识别对应名称。

---

## 问题 4：UndefinedError：'dict object' has no attribute 'id'

### 原因

模板中使用：

```html
question.id
```

但是 `question` 实际上是 dictionary。

另外，旧数据中部分题目没有：

```python
"id"
```

字段。

### 解决方法

模板统一改为：

```html
question["id"]
```

同时在读取 JSON 时检查旧数据：

```python
for index, question in enumerate(questions):
    if "id" not in question:
        question["id"] = index + 1
```

自动补充旧数据中的 id。

### 学习

我理解了：

Jinja2 可以访问 dictionary，但推荐统一使用：

```html
question["id"]
question["Question"]
```

这种方式更加稳定。

---

## 测试记录

### 测试 1：进入 Question List

结果：

登录成功后正常进入题库页面。

状态：通过

---

### 测试 2：点击题目名称

结果：

成功进入 Question Detail 页面。

状态：通过

---

### 测试 3：显示题目详细信息

结果：

页面正确显示：

- Question
- Main Question
- Marks
- Answer
- Created by
- Created at

状态：通过

---

### 测试 4：返回 Question List

操作：

点击：

```
Back to Question List
```

结果：

成功返回：

```
/questions
```

状态：通过

---

## 今日学习总结

今天完成了 Question Detail 页面开发，实现了 Question List 到 Question Detail 的页面跳转。

我主要理解了：

1. Flask 如何通过 URL 参数传递 `question_id`。
2. 如何根据 `question_id` 查找对应的数据。
3. `url_for()` 必须对应已经存在的 Flask 路由。
4. Jinja2 推荐使用 `question["key"]` 的方式访问 dictionary。
5. `datetime` 和 `json` 模块需要正确导入才能使用。
6. 为保证兼容旧数据，可以在读取 JSON 时自动补充缺失字段。