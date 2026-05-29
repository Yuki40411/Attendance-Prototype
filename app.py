import sqlite3
import csv
import io
from datetime import date
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
        # UPDATED: Added is_active for Soft Deletes (1 = Active, 0 = Dropped)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS enrollments (
                student_id TEXT,
                class_id INTEGER,
                is_active INTEGER DEFAULT 1, 
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
                existing_class = conn.execute('SELECT id FROM classes WHERE name = ?', (class_name,)).fetchone()
                
                if existing_class:
                    class_id = existing_class['id']
                    is_update = True
                else:
                    conn.execute('INSERT INTO classes (name) VALUES (?)', (class_name,))
                    class_id = conn.execute('SELECT id FROM classes WHERE name = ?', (class_name,)).fetchone()['id']
                    is_update = False
                
                raw_data = file.stream.read().decode("utf-8-sig", errors="replace")
                stream = io.StringIO(raw_data, newline=None)
                
                try:
                    dialect = csv.Sniffer().sniff(raw_data[:1024], delimiters=[',', ';', '\t'])
                    csv_reader = csv.reader(stream, dialect)
                except:
                    csv_reader = csv.reader(stream) 

                try:
                    next(csv_reader) 
                except StopIteration:
                    flash("Error: The CSV file appears to be completely empty.", "danger")
                    return redirect(url_for('upload_csv'))
                
                new_enrollments = 0
                
                for row in csv_reader:
                    if not row: continue 
                    if len(row) == 1:
                        if ';' in row[0]: row = row[0].split(';')
                        elif '\t' in row[0]: row = row[0].split('\t')

                    if len(row) >= 2: 
                        student_id = str(row[0]).strip()
                        student_name = str(row[1]).strip()
                        
                        if student_id.lower() == 'student_id' or student_name.lower() == 'name':
                            continue
                            
                        if student_id and student_name: 
                            conn.execute('INSERT OR IGNORE INTO students (student_id, name) VALUES (?, ?)', (student_id, student_name))
                            
                            existing_enrollment = conn.execute(
                                'SELECT is_active FROM enrollments WHERE student_id = ? AND class_id = ?', 
                                (student_id, class_id)
                            ).fetchone()
                            
                            if not existing_enrollment:
                                conn.execute('INSERT INTO enrollments (student_id, class_id) VALUES (?, ?)', (student_id, class_id))
                                new_enrollments += 1
                            elif existing_enrollment['is_active'] == 0:
                                # Re-activate a dropped student if they are uploaded again
                                conn.execute('UPDATE enrollments SET is_active = 1 WHERE student_id = ? AND class_id = ?', (student_id, class_id))
                                new_enrollments += 1
                
                if new_enrollments == 0 and not is_update:
                    conn.rollback() 
                    flash(f'Error: Could not read any valid students from CSV. Check the file format.', 'danger')
                    return redirect(url_for('upload_csv'))
                else:
                    conn.commit() 
                    if is_update:
                        if new_enrollments == 0:
                            flash(f'No new transfer students found. The roster for "{class_name}" is already up to date!', 'info')
                        else:
                            flash(f'Success! Added/Restored {new_enrollments} student(s) to "{class_name}".', 'success')
                    else:
                        flash(f'Success! Created "{class_name}" and enrolled {new_enrollments} students.', 'success')
                        
            
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

    selected_class_id = request.args.get('class_id')
    selected_date = request.args.get('date') or date.today().strftime('%Y-%m-%d')
    
    with get_db_connection() as conn:
        classes = conn.execute('SELECT * FROM classes ORDER BY name').fetchall()
        students = []
        if selected_class_id:
            # UPDATED: Only load active students (is_active = 1) for daily attendance
            students = conn.execute('''
                SELECT s.student_id, s.name, a.status
                FROM students s
                JOIN enrollments e ON s.student_id = e.student_id
                LEFT JOIN attendance a ON s.student_id = a.student_id AND a.class_id = e.class_id AND a.date = ?
                WHERE e.class_id = ? AND e.is_active = 1
                ORDER BY s.student_id
            ''', (selected_date, selected_class_id)).fetchall()
    
    return render_template('attendance.html', classes=classes, students=students, selected_class_id=selected_class_id, selected_date=selected_date)

# NEW ROUTE: Manage Roster (Drop / Restore / Add Students)
@app.route('/manage', methods=['GET', 'POST'])
def manage_roster():
    if request.method == 'POST':
        class_id = request.form.get('class_id')
        action = request.form.get('action') 
        
        with get_db_connection() as conn:
            # ACTION 1: ADD A NEW STUDENT MANUALLY
            if action == 'add':
                new_id = request.form.get('new_student_id').strip()
                new_name = request.form.get('new_student_name').strip()
                
                if new_id and new_name:
                    # 1. Add them to the master student list (ignores if they already exist in another class)
                    conn.execute('INSERT OR IGNORE INTO students (student_id, name) VALUES (?, ?)', (new_id, new_name))
                    
                    # 2. Check their status in THIS specific class
                    existing = conn.execute('SELECT is_active FROM enrollments WHERE student_id = ? AND class_id = ?', (new_id, class_id)).fetchone()
                    
                    if not existing:
                        conn.execute('INSERT INTO enrollments (student_id, class_id) VALUES (?, ?)', (new_id, class_id))
                        flash(f"Success! {new_name} ({new_id}) was added to the class.", "success")
                    elif existing['is_active'] == 0:
                        conn.execute('UPDATE enrollments SET is_active = 1 WHERE student_id = ? AND class_id = ?', (new_id, class_id))
                        flash(f"{new_name} was previously dropped from this class and has been restored.", "success")
                    elif existing['is_active'] == 1 and new_name != conn.execute('SELECT name FROM students WHERE student_id = ?', (new_id,)).fetchone()['name']:
                        flash(f"The student ID {new_id} is already in the class with a different name.", "info")
                    else:
                        flash(f"{new_name} ({new_id}) is already an active student in this class.", "info")
            
            # ACTION 2: DROP OR RESTORE EXISTING STUDENTS
            elif action in ['drop', 'restore']:
                student_id = request.form.get('student_id')
                new_status = 0 if action == 'drop' else 1
                conn.execute('UPDATE enrollments SET is_active = ? WHERE student_id = ? AND class_id = ?', (new_status, student_id, class_id))
                action_text = "dropped from" if new_status == 0 else "restored to"
                flash(f"Student {student_id} successfully {action_text} the roster.", "success")
                
            conn.commit()
            
        return redirect(url_for('manage_roster', class_id=class_id))

    # GET Request: Load the UI
    selected_class_id = request.args.get('class_id')
    with get_db_connection() as conn:
        classes = conn.execute('SELECT * FROM classes ORDER BY name').fetchall()
        students = []
        if selected_class_id:
            students = conn.execute('''
                SELECT s.student_id, s.name, e.is_active
                FROM students s
                JOIN enrollments e ON s.student_id = e.student_id
                WHERE e.class_id = ?
                ORDER BY s.name
            ''', (selected_class_id,)).fetchall()

    return render_template('manage.html', classes=classes, students=students, selected_class_id=selected_class_id)

if __name__ == '__main__':
    init_db()
    app.run(debug=True)