import sqlite3
import csv
import io
from flask import Flask, request, render_template, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = 'super_secret_poc_key' 
DB_NAME = "attendance.db"

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db_connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS students (
                student_id TEXT PRIMARY KEY,
                name TEXT NOT NULL
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT,
                date TEXT,
                status TEXT,
                FOREIGN KEY(student_id) REFERENCES students(student_id)
            )
        ''')
        conn.commit()

@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')

@app.route('/upload', methods=['GET', 'POST'])
def upload_csv():
    if request.method == 'POST':
        file = request.files['file']
        if file and file.filename.endswith('.csv'):
            stream = io.StringIO(file.stream.read().decode("cp1252"), newline=None)
            csv_reader = csv.reader(stream)
            next(csv_reader) 
            
            with get_db_connection() as conn:
                for row in csv_reader:
                    if len(row) >= 2: 
                        conn.execute(
                            'INSERT OR IGNORE INTO students (student_id, name) VALUES (?, ?)', 
                            (row[0].strip(), row[1].strip())
                        )
                conn.commit()
            flash('CSV Imported Successfully!')
            return redirect(url_for('take_attendance'))
            
    return render_template('upload.html')

@app.route('/attendance', methods=['GET', 'POST'])
def take_attendance():
    if request.method == 'POST':
        date = request.form.get('date')
        
        with get_db_connection() as conn:
            for key, value in request.form.items():
                if key != 'date':
                    conn.execute(
                        'INSERT INTO attendance (student_id, date, status) VALUES (?, ?, ?)', 
                        (key, date, value)
                    )
            conn.commit()
        return f"<h3>Attendance for {date} saved successfully!</h3><a href='/'>Back to Home</a>"

    # GET request: Fetch students and render the UI template
    with get_db_connection() as conn:
        students = conn.execute('SELECT student_id, name FROM students').fetchall()
    
    return render_template('attendance.html', students=students)

if __name__ == '__main__':
    init_db()
    app.run(debug=True)