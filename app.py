import json
from flask import Flask, render_template, request, redirect, url_for, session
app = Flask(__name__)

app.secret_key = 'your_secret_key'

USER = {
    "teacher1": "123456",
    "teacher2": "456789",
    "1": "1"
}
QUESTIONS_FILE = "questions.json"

def load_questions():
    with open(QUESTIONS_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def save_questions(questions):
    with open(QUESTIONS_FILE, "w", encoding="utf-8") as file:
        json.dump(questions, file, indent=4, ensure_ascii=False)


@app.route('/')
def home():
    return redirect(url_for('login'))

# login
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if username in USER and USER[username] == password:
            session['logged_in'] = True
            session['username'] = username
            return redirect(url_for('question_list'))
        else: 
            error = 'Invalid Credentials. Please try again.'

    return render_template('login.html', error=error)

@app.route('/questions')
def question_list():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    questions = load_questions()

    return render_template('question.html', questions=questions, username=session.get('username'))

# create questions
@app.route("/questions/new", methods=["GET", "POST"])
def create_question():
    if "username" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        questions = load_questions()

        new_question = {
            "id": len(questions) + 1,
            "Question": request.form["title"],
            "Marks": request.form["marks"],
            "Answer": request.form["answer"],
            "Actions": "Edit",
            "Status": "Ready",
            "Version": "v1",
            "Created by": session["username"],
            "Created at": datatime.now().strftime("%Y-%m-%d %H:%M"),
            "Comments": "0",
            "Needs checking?": "Unlikely",
            "Facility index": "100.00%",
            "Discriminative efficiency": "72.00%",
            "Usage": "0",
            "Last used": "Never",
            "Modify": session["username"]
        }

        questions.append(new_question)
        save_questions(questions)

        return redirect(url_for("question_list"))

    return render_template("create_question.html")

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)