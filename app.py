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
        # 1. Create Classes Table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS classes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            )
        ''')
        # 2. Create Students Table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS students (
                student_id TEXT PRIMARY KEY,
                name TEXT NOT NULL
            )
        ''')
        # 3. Create Enrollments Table (Links students to classes)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS enrollments (
                student_id TEXT,
                class_id INTEGER,
                PRIMARY KEY (student_id, class_id),
                FOREIGN KEY(student_id) REFERENCES students(student_id),
                FOREIGN KEY(class_id) REFERENCES classes(id)
            )
        ''')
        # 4. Update Attendance Table to include class_id
        conn.execute('''
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT,
                class_id INTEGER,
                date TEXT,
                status TEXT,
                FOREIGN KEY(student_id) REFERENCES students(student_id),
                FOREIGN KEY(class_id) REFERENCES classes(id)
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
        class_name = request.form.get('class_name').strip()
        
        if file and file.filename.endswith('.csv') and class_name:
            stream = io.StringIO(file.stream.read().decode("cp1252"), newline=None)
            csv_reader = csv.reader(stream)
            next(csv_reader) 
            
            with get_db_connection() as conn:
                # 1. Add the new class (ignores if it already exists)
                conn.execute('INSERT OR IGNORE INTO classes (name) VALUES (?)', (class_name,))
                # 2. Get the ID of that class
                class_id = conn.execute('SELECT id FROM classes WHERE name = ?', (class_name,)).fetchone()['id']
                
                # 3. Loop through CSV and enroll students
                for row in csv_reader:
                    if len(row) >= 2: 
                        student_id = row[0].strip()
                        student_name = row[1].strip()
                        
                        # Add student to database
                        conn.execute(
                            'INSERT OR IGNORE INTO students (student_id, name) VALUES (?, ?)', 
                            (student_id, student_name)
                        )
                        # Link student to this specific class
                        conn.execute(
                            'INSERT OR IGNORE INTO enrollments (student_id, class_id) VALUES (?, ?)',
                            (student_id, class_id)
                        )
                conn.commit()
            flash(f'CSV Imported Successfully for {class_name}!')
            
    return render_template('upload.html')

@app.route('/attendance', methods=['GET', 'POST'])
def take_attendance():
    if request.method == 'POST':
        date = request.form.get('date')
        class_id = request.form.get('class_id')
        
        with get_db_connection() as conn:
            for key, value in request.form.items():
                if key not in ('date', 'class_id'):
                    conn.execute(
                        'INSERT INTO attendance (student_id, class_id, date, status) VALUES (?, ?, ?, ?)', 
                        (key, class_id, date, value)
                    )
            conn.commit()
        flash(f"Attendance for {date} saved successfully!")
        return redirect(url_for('index'))

    # GET request logic: 
    selected_class_id = request.args.get('class_id')
    
    with get_db_connection() as conn:
        # Fetch all classes to populate the dropdown menu
        classes = conn.execute('SELECT * FROM classes ORDER BY name').fetchall()
        
        students = []
        if selected_class_id:
            # Fetch ONLY students enrolled in the selected class
            students = conn.execute('''
                SELECT s.student_id, s.name 
                FROM students s
                JOIN enrollments e ON s.student_id = e.student_id
                WHERE e.class_id = ?
                ORDER BY s.name
            ''', (selected_class_id,)).fetchall()
    
    return render_template('attendance.html', classes=classes, students=students, selected_class_id=selected_class_id)

if __name__ == '__main__':
    init_db()
    app.run(debug=True)