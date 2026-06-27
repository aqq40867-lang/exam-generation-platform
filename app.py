from flask import Flask, render_template, request, redirect, url_for, session
app = Flask(__name__)

app.secret_key = 'your_secret_key'

USER = {
    "teacher1": "123456",
    "teacher2": "456789",
    "1": "1"
}

QUESTIONS = [
    {
        "Question" : "A simple calculation",
        "Actions" : "Edit",
        "Status" : "Ready",
        "Version" : "v1",
        "Created by" : "Y Wei 27 June 2026, 21:40pm",
        "Comments" : "0",
        "Needs checking?" : "Unlikely",
        "Facility index" : "100.00%",
        "Discriminative efficiency" : "72.00%",
        "Usage" : "1",
        "Last used" : "Sunday, 25 June 2026, 21:40pm",
        "Modify" : "Y Wei 27 June 2026, 21:40pm"
    },
    {
        "Question" : "Binary search",
        "Actions" : "Edit",
        "Status" : "Ready",
        "Version" : "v1",
        "Created by" : "Y Wei 27 June 2026, 21:40pm",
        "Comments" : "0",
        "Needs checking?" : "Unlikely",
        "Facility index" : "100.00%",
        "Discriminative efficiency" : "72.00%",
        "Usage" : "1",
        "Last used" : "Sunday, 25 June 2026, 21:40pm",
        "Modify" : "Y Wei 27 June 2026, 21:40pm"
    },
    {
        "Question" : "Fibonacci",
        "Actions" : "Edit",
        "Status" : "Ready",
        "Version" : "v1",
        "Created by" : "Y Wei 27 June 2026, 21:40pm",
        "Comments" : "0",
        "Needs checking?" : "Unlikely",
        "Facility index" : "100.00%",
        "Discriminative efficiency" : "72.00%",
        "Usage" : "1",
        "Last used" : "Sunday, 25 June 2026, 21:40pm",
        "Modify" : "Y Wei 27 June 2026, 21:40pm"
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