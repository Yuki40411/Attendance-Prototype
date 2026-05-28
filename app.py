import sqlite3
import csv
import io
from datetime import date # NEW: Used to default the date to today
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
            CREATE TABLE IF NOT EXISTS classes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS students (
                student_id TEXT PRIMARY KEY,
                name TEXT NOT NULL
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS enrollments (
                student_id TEXT,
                class_id INTEGER,
                PRIMARY KEY (student_id, class_id),
                FOREIGN KEY(student_id) REFERENCES students(student_id),
                FOREIGN KEY(class_id) REFERENCES classes(id)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT,
                class_id INTEGER,
                date TEXT,
                status TEXT,
                UNIQUE(student_id, class_id, date), 
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
            with get_db_connection() as conn:
                # 1. Validation - Check if class already exists
                existing_class = conn.execute('SELECT id FROM classes WHERE name = ?', (class_name,)).fetchone()
                if existing_class:
                    flash(f'Error: A class named "{class_name}" already exists!', 'danger')
                    return redirect(url_for('upload_csv'))
                
                # 2. Decode using utf-8-sig to safely strip hidden Excel BOM characters
                stream = io.StringIO(file.stream.read().decode("utf-8-sig", errors="replace"), newline=None)
                csv_reader = csv.reader(stream)
                
                # Safely skip the header row
                try:
                    next(csv_reader) 
                except StopIteration:
                    flash("Error: The CSV file appears to be completely empty.", "danger")
                    return redirect(url_for('upload_csv'))
                
                # Create the class temporarily
                conn.execute('INSERT INTO classes (name) VALUES (?)', (class_name,))
                class_id = conn.execute('SELECT id FROM classes WHERE name = ?', (class_name,)).fetchone()['id']
                
                students_enrolled = 0
                
                for row in csv_reader:
                    # Defensive check: if Excel used semicolons instead of commas
                    if len(row) == 1 and ';' in row[0]:
                        row = row[0].split(';')

                    if len(row) >= 2: 
                        student_id = row[0].strip()
                        student_name = row[1].strip()
                        
                        if student_id and student_name: # Ensure data isn't blank
                            conn.execute('INSERT OR IGNORE INTO students (student_id, name) VALUES (?, ?)', (student_id, student_name))
                            conn.execute('INSERT OR IGNORE INTO enrollments (student_id, class_id) VALUES (?, ?)', (student_id, class_id))
                            students_enrolled += 1
                
                # 3. Transaction Control
                if students_enrolled == 0:
                    conn.rollback() # Undo the class creation so the DB stays clean
                    flash(f'Error: No valid students found. The class "{class_name}" was NOT saved. Check your CSV formatting.', 'danger')
                    return redirect(url_for('upload_csv'))
                else:
                    conn.commit() # Save everything permanently
                    flash(f'Success! Enrolled {students_enrolled} students into {class_name}.', 'success')
            
    return render_template('upload.html')

@app.route('/attendance', methods=['GET', 'POST'])
def take_attendance():
    if request.method == 'POST':
        form_date = request.form.get('date')
        class_id = request.form.get('class_id')
        
        with get_db_connection() as conn:
            for key, value in request.form.items():
                if key not in ('date', 'class_id'):
                    conn.execute('''
                        INSERT INTO attendance (student_id, class_id, date, status) 
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(student_id, class_id, date) 
                        DO UPDATE SET status=excluded.status
                    ''', (key, class_id, form_date, value))
            conn.commit()
        flash(f"Attendance for {form_date} saved/updated successfully!", 'success')
        return redirect(url_for('take_attendance', class_id=class_id, date=form_date))

    # GET Request: Loading the UI
    selected_class_id = request.args.get('class_id')
    # NEW: Default to today's date if the user hasn't selected one yet
    selected_date = request.args.get('date') or date.today().strftime('%Y-%m-%d')
    
    with get_db_connection() as conn:
        classes = conn.execute('SELECT * FROM classes ORDER BY name').fetchall()
        
        students = []
        if selected_class_id:
            students = conn.execute('''
                SELECT s.student_id, s.name, a.status
                FROM students s
                JOIN enrollments e ON s.student_id = e.student_id
                LEFT JOIN attendance a ON s.student_id = a.student_id AND a.class_id = e.class_id AND a.date = ?
                WHERE e.class_id = ?
                ORDER BY s.student_id
            ''', (selected_date, selected_class_id)).fetchall()
    
    return render_template('attendance.html', classes=classes, students=students, selected_class_id=selected_class_id, selected_date=selected_date)

if __name__ == '__main__':
    init_db()
    app.run(debug=True)