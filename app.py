from flask import Flask, render_template, request, redirect, url_for, session
app = Flask(__name__)

app.secret_key = 'your_secret_key'

USER = {
    "teacher1": "123456",
    "teacher2": "456789"
}

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
            return redirect(url_for('question'))
        else: 
            error = 'Invalid Credentials. Please try again.'

    return render_template('login.html', error=error)

@app.route('/questions')
def question_list():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('question.html', username=session.get('username'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)