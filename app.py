import sqlite3
import csv
import io
import random
from datetime import date
from functools import wraps # NEW: Used to create security locks
from flask import Flask, request, render_template, redirect, url_for, flash, session

app = Flask(__name__)
app.secret_key = 'super_secret_poc_key' 
DB_NAME = "attendance.db"

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

# --- SECURITY DECORATORS ---
def lecturer_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'lecturer':
            flash("Access denied. Lecturer login required.", "danger")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def student_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'student':
            flash("Please log in as a student to access the check-in portal.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- INITIALIZATION ---
def init_db():
    with get_db_connection() as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS classes (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL)')
        conn.execute('CREATE TABLE IF NOT EXISTS students (student_id TEXT PRIMARY KEY, name TEXT NOT NULL)')
        conn.execute('''CREATE TABLE IF NOT EXISTS enrollments (
            student_id TEXT, class_id INTEGER, is_active INTEGER DEFAULT 1, 
            PRIMARY KEY (student_id, class_id), FOREIGN KEY(student_id) REFERENCES students(student_id), FOREIGN KEY(class_id) REFERENCES classes(id))''')
        conn.execute('''CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT, student_id TEXT, class_id INTEGER, date TEXT, status TEXT,
            UNIQUE(student_id, class_id, date), FOREIGN KEY(student_id) REFERENCES students(student_id), FOREIGN KEY(class_id) REFERENCES classes(id))''')
        conn.execute('''CREATE TABLE IF NOT EXISTS active_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, class_id INTEGER, date TEXT, pin TEXT,
            UNIQUE(class_id, date), FOREIGN KEY(class_id) REFERENCES classes(id))''')
        conn.commit()

# --- AUTHENTICATION ROUTES ---
@app.route('/')
def index():
    # Smart routing based on who is logged in
    if session.get('role') == 'lecturer':
        return redirect(url_for('take_attendance'))
    elif session.get('role') == 'student':
        return redirect(url_for('student_checkin'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        role = request.form.get('role')
        
        if role == 'lecturer':
            session.clear()
            session['role'] = 'lecturer'
            flash("Welcome back, Lecturer!", "success")
            return redirect(url_for('take_attendance'))
                
        elif role == 'student':
            student_id = request.form.get('student_id').strip()
            with get_db_connection() as conn:
                student = conn.execute('SELECT * FROM students WHERE student_id = ?', (student_id,)).fetchone()
                if student:
                    session.clear()
                    session['role'] = 'student'
                    session['student_id'] = student_id
                    session['student_name'] = student['name']
                    flash(f"Welcome, {student['name']}!", "success")
                    return redirect(url_for('student_checkin'))
                else:
                    flash("Student ID not found in the system. Please see your lecturer.", "danger")
                    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("You have been successfully logged out.", "info")
    return redirect(url_for('login'))

# --- STUDENT ROUTE ---
@app.route('/checkin', methods=['GET', 'POST'])
@student_required # Locked to students
def student_checkin():
    if request.method == 'POST':
        student_id = session.get('student_id') # Pulled securely from session, NOT the form!
        pin = request.form.get('pin').strip()

        with get_db_connection() as conn:
            session_data = conn.execute('SELECT class_id, date FROM active_sessions WHERE pin = ?', (pin,)).fetchone()

            if session_data:
                class_id = session_data['class_id']
                session_date = session_data['date']
                enrollment = conn.execute('SELECT is_active FROM enrollments WHERE student_id = ? AND class_id = ?', (student_id, class_id)).fetchone()

                if enrollment and enrollment['is_active'] == 1:
                    conn.execute('''
                        INSERT INTO attendance (student_id, class_id, date, status) 
                        VALUES (?, ?, ?, 'Present')
                        ON CONFLICT(student_id, class_id, date) 
                        DO UPDATE SET status='Present'
                    ''', (student_id, class_id, session_date))
                    conn.commit()
                    flash(f"Check-in successful! You have been marked Present.", "success")
                else:
                    flash("Check-in Failed: You are not actively enrolled in this class.", "danger")
            else:
                flash("Check-in Failed: Invalid or expired PIN.", "danger")
                
        return redirect(url_for('student_checkin'))

    return render_template('checkin.html')

# --- LECTURER ROUTES ---
@app.route('/upload', methods=['GET', 'POST'])
@lecturer_required
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
                            existing_enrollment = conn.execute('SELECT is_active FROM enrollments WHERE student_id = ? AND class_id = ?', (student_id, class_id)).fetchone()
                            
                            if not existing_enrollment:
                                conn.execute('INSERT INTO enrollments (student_id, class_id) VALUES (?, ?)', (student_id, class_id))
                                new_enrollments += 1
                            elif existing_enrollment['is_active'] == 0:
                                conn.execute('UPDATE enrollments SET is_active = 1 WHERE student_id = ? AND class_id = ?', (student_id, class_id))
                                new_enrollments += 1
                
                if new_enrollments == 0 and not is_update:
                    conn.rollback() 
                    flash('Error: Could not read any valid students from CSV. Check the file format.', 'danger')
                else:
                    conn.commit() 
                    if is_update:
                        if new_enrollments == 0: flash(f'No new transfer students found. The roster for "{class_name}" is already up to date!', 'info')
                        else: flash(f'Success! Added/Restored {new_enrollments} student(s) to "{class_name}".', 'success')
                    else: flash(f'Success! Created "{class_name}" and enrolled {new_enrollments} students.', 'success')
                        
        return redirect(url_for('take_attendance'))
    return render_template('upload.html')

@app.route('/attendance', methods=['GET', 'POST'])
@lecturer_required
def take_attendance():
    if request.method == 'POST':
        form_date = request.form.get('date')
        class_id = request.form.get('class_id')
        action = request.form.get('action')

        with get_db_connection() as conn:
            # ACTION 1: Generate Student PIN
            if action == 'generate_pin':
                new_pin = str(random.randint(1000, 9999))
                conn.execute('INSERT INTO active_sessions (class_id, date, pin) VALUES (?, ?, ?) ON CONFLICT(class_id, date) DO UPDATE SET pin=excluded.pin', (class_id, form_date, new_pin))
                conn.commit()
                flash(f"Session started! Student Check-in PIN is: {new_pin}", "success")
                return redirect(url_for('take_attendance', class_id=class_id, date=form_date))
                
            # ACTION 2: NEW Silent Autosave via AJAX
            elif action == 'auto_save':
                student_id = request.form.get('student_id')
                status = request.form.get('status')
                
                conn.execute('''
                    INSERT INTO attendance (student_id, class_id, date, status) 
                    VALUES (?, ?, ?, ?) 
                    ON CONFLICT(student_id, class_id, date) 
                    DO UPDATE SET status=excluded.status
                ''', (student_id, class_id, form_date, status))
                conn.commit()
                
                # Return a simple 200 OK text response so the browser doesn't refresh!
                return "Saved successfully", 200

    # GET Request: Loading the UI
    selected_class_id = request.args.get('class_id')
    today_string = date.today().strftime('%Y-%m-%d')
    selected_date = request.args.get('date') or today_string
    
    with get_db_connection() as conn:
        classes = conn.execute('SELECT * FROM classes ORDER BY name').fetchall()
        students = []
        active_pin = None
        
        if selected_class_id:
            session_data = conn.execute('SELECT pin FROM active_sessions WHERE class_id = ? AND date = ?', (selected_class_id, selected_date)).fetchone()
            if session_data: active_pin = session_data['pin']

            students = conn.execute('''
                SELECT s.student_id, s.name, a.status FROM students s
                JOIN enrollments e ON s.student_id = e.student_id
                LEFT JOIN attendance a ON s.student_id = a.student_id AND a.class_id = e.class_id AND a.date = ?
                WHERE e.class_id = ? AND e.is_active = 1 ORDER BY s.student_id
            ''', (selected_date, selected_class_id)).fetchall()
    
    return render_template('attendance.html', classes=classes, students=students, selected_class_id=selected_class_id, selected_date=selected_date, active_pin=active_pin, today_date=today_string)

@app.route('/manage', methods=['GET', 'POST'])
@lecturer_required
def manage_roster():
    if request.method == 'POST':
        class_id = request.form.get('class_id')
        action = request.form.get('action') 
        
        with get_db_connection() as conn:
            if action == 'add':
                new_id = request.form.get('new_student_id').strip()
                new_name = request.form.get('new_student_name').strip()
                if new_id and new_name:
                    conn.execute('INSERT OR IGNORE INTO students (student_id, name) VALUES (?, ?)', (new_id, new_name))
                    existing = conn.execute('SELECT is_active FROM enrollments WHERE student_id = ? AND class_id = ?', (new_id, class_id)).fetchone()
                    if not existing:
                        conn.execute('INSERT INTO enrollments (student_id, class_id) VALUES (?, ?)', (new_id, class_id))
                        flash(f"Success! {new_name} ({new_id}) was added to the class.", "success")
                    elif existing['is_active'] == 0:
                        conn.execute('UPDATE enrollments SET is_active = 1 WHERE student_id = ? AND class_id = ?', (new_id, class_id))
                        flash(f"{new_name} was previously dropped from this class and has been restored.", "success")
                    else:
                        flash(f"{new_name} is already active in this class!", "info")
            elif action in ['drop', 'restore']:
                student_id = request.form.get('student_id')
                new_status = 0 if action == 'drop' else 1
                conn.execute('UPDATE enrollments SET is_active = ? WHERE student_id = ? AND class_id = ?', (new_status, student_id, class_id))
                action_text = "dropped from" if new_status == 0 else "restored to"
                flash(f"Student {student_id} successfully {action_text} the roster.", "success")
            conn.commit()
            
        return redirect(url_for('manage_roster', class_id=class_id))

    selected_class_id = request.args.get('class_id')
    with get_db_connection() as conn:
        classes = conn.execute('SELECT * FROM classes ORDER BY name').fetchall()
        students = []
        if selected_class_id:
            students = conn.execute('''SELECT s.student_id, s.name, e.is_active FROM students s JOIN enrollments e ON s.student_id = e.student_id WHERE e.class_id = ? ORDER BY s.name''', (selected_class_id,)).fetchall()

    return render_template('manage.html', classes=classes, students=students, selected_class_id=selected_class_id)

if __name__ == '__main__':
    init_db()
    app.run(debug=True)