from flask import Flask, render_template, request, redirect, url_for, session
app = Flask(__name__)

app.secret_key = 'your_secret_key'

USER = {
    "teacher1": "123456",
    "teacher2": "456789"
}

QUESTIONS = [
    {
        "id": 1,
        "title": "Python",
        "content": "Explain what a variable is in Python."
    },
    {
        "id": 2,
        "title": "SQL",
        "content": "Write a SQL query to select all students."
    },
    {
        "id": 3,
        "title": "Algorithms and Data Structures",
        "content": "Explain what a linked list is."
    }
]

@app.route('/')
def home():
    return redirect(url_for('login'))

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
    return render_template('question.html', username=session.get('username'), questions=QUESTIONS)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)