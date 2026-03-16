from flask import Blueprint, render_template, request, redirect, url_for, session, flash, send_file, make_response, abort, current_app
from models.db import get_db_connection
from utils.helpers import login_required, role_required, add_notification, notify_admins
from services.email_service import send_email
from datetime import datetime, timedelta
import uuid
import qrcode
from io import BytesIO
import time
import os
from fpdf import FPDF
from werkzeug.utils import secure_filename
from groq import Groq
from flask import jsonify
import json

# System prompt remains defined here
SYSTEM_PROMPT_TEMPLATE = """
You are 'Eventora AI', a helpful assistant for this college event portal.
Current Date: {date}
Logged-in Student ID: {user_id}

Database Schema:
- student(student_id, name, register_number, email, department, semester)
- events(event_id, event_name, event_date, location, event_type, points_awarded, is_announced, description)
- registrations(registration_id, event_id, student_id, attendance)

Guidelines:
1. If you need to query the database, you MUST output ONLY the JSON block and NOTHING ELSE. Example: {{"sql": "SELECT ..."}}
2. Do NOT ask the user for their student ID; it is provided above as {user_id}.
3. Always filter events by 'is_announced = 1' when listing general events.
4. For 'my events' or 'registrations', join 'registrations' and 'events'.
5. If a user asks for points, use this: SELECT SUM(e.points_awarded) FROM events e JOIN registrations r ON e.event_id = r.event_id WHERE r.student_id = {user_id} AND r.attendance = 'Present'
6. Your final answer (after I give you database results) should be friendly and human-like.
"""

student_bp = Blueprint('student', __name__)

@student_bp.route('/student/dashboard')
@login_required
@role_required('student')
def student_dashboard():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT e.event_id, e.event_name, e.event_date, e.location, e.event_type, e.points_awarded, r.attendance, r.certificate_status, r.registration_id,
        (SELECT COUNT(*) FROM feedback f WHERE f.event_id=r.event_id AND f.student_id=r.student_id) as feedback_count,
        od.status as od_status
        FROM registrations r
        JOIN events e ON r.event_id=e.event_id
        LEFT JOIN onduty_requests od ON r.event_id = od.event_id AND r.student_id = od.student_id
        WHERE r.student_id=%s
    """, (session['user_id'],))
    registrations = cursor.fetchall()
    
    current_date = datetime.now().date()
    for r in registrations:
        e_date = r['event_date']
        if isinstance(e_date, str):
            e_date = datetime.strptime(e_date, '%Y-%m-%d').date()
        
        if e_date >= (current_date + timedelta(days=2)) and r['attendance'] != 'Present':
            r['can_cancel'] = True
        else:
            r['can_cancel'] = False
            
    total_registered = len(registrations)
    attended_count = sum(1 for r in registrations if r['attendance'] == 'Present')
    
    # Calculate Campus Points and Co-curricular Badges
    total_campus_points = sum(r['points_awarded'] for r in registrations if r['attendance'] == 'Present' and r['points_awarded'])
    
    badge = "Novice"
    if total_campus_points >= 100:
        badge = "Elite Scholar"
    elif total_campus_points >= 50:
        badge = "Pro Organizer"
    elif total_campus_points >= 20:
        badge = "Active Participant"
    
    participation_rate = 0
    if total_registered > 0:
        participation_rate = round((attended_count / total_registered) * 100, 1)
        
    cursor.execute("""
        SELECT e.*, 
        CASE WHEN r.registration_id IS NOT NULL THEN 1 ELSE 0 END as is_registered,
        CASE WHEN w.waitlist_id IS NOT NULL THEN 1 ELSE 0 END as is_waitlisted,
        w.position as waitlist_pos
        FROM events e
        LEFT JOIN registrations r ON e.event_id = r.event_id AND r.student_id = %s
        LEFT JOIN waitlist w ON e.event_id = w.event_id AND w.student_id = %s
        WHERE e.is_announced = 1
        ORDER BY e.event_date
    """, (session['user_id'], session['user_id']))
    events = cursor.fetchall()
    
    # Fetch waitlisted events
    cursor.execute("""
        SELECT e.event_name, e.event_date, e.location, w.position, w.waitlist_id
        FROM waitlist w
        JOIN events e ON w.event_id = e.event_id
        WHERE w.student_id = %s
        ORDER BY w.added_at DESC
    """, (session['user_id'],))
    waitlisted_events = cursor.fetchall()
    
    # Fetch student profile details (phone, year, department, semester, profile_photo)
    try:
        cursor.execute("SELECT phone, year, department, semester, profile_photo FROM student WHERE student_id=%s", (session['user_id'],))
        student_profile = cursor.fetchone()
    except Exception:
        student_profile = None
    
    db.close()
    
    return render_template('student_dashboard.html', 
                           registrations=registrations, 
                           events=events,
                           waitlisted_events=waitlisted_events,
                           total_registered=total_registered,
                           attended_count=attended_count,
                           participation_rate=participation_rate,
                           total_campus_points=total_campus_points,
                           badge=badge,
                           student_profile=student_profile)

@student_bp.route('/my-registrations', methods=['GET', 'POST'])
def my_registrations():
    registrations = None
    if request.method == 'POST':
        reg_no = request.form.get('reg_no')
        email = request.form.get('email')
        
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        cursor.execute("""
            SELECT r.registration_id, e.event_name, e.event_date, e.location, r.attendance
            FROM registrations r
            JOIN student s ON r.student_id = s.student_id
            JOIN events e ON r.event_id = e.event_id
            WHERE s.register_number=%s AND s.email=%s
            ORDER BY e.event_date DESC
        """, (reg_no, email))
        registrations = cursor.fetchall()
        db.close()

    return render_template('my_registrations.html', registrations=registrations)

@student_bp.route('/student/update-profile', methods=['POST'])
@login_required
@role_required('student')
def update_profile():
    phone = request.form.get('phone', '').strip()
    year = request.form.get('year') or None
    department = request.form.get('department', '').strip()
    semester = request.form.get('semester') or None

    photo_filename = None
    photo_file = request.files.get('profile_photo')
    if photo_file and photo_file.filename:
        ext = os.path.splitext(secure_filename(photo_file.filename))[1].lower()
        if ext not in ('.jpg', '.jpeg', '.png', '.webp'):
            flash("Invalid photo format. Use JPG, PNG or WEBP.", "error")
            return redirect(url_for('student.student_dashboard') + '#v-pills-profile')
        photo_filename = f"{session['user_id']}{ext}"
        portraits_dir = os.path.join(os.path.dirname(__file__), '..', 'static', 'uploads', 'portraits')
        os.makedirs(portraits_dir, exist_ok=True)
        photo_file.save(os.path.join(portraits_dir, photo_filename))

    db = get_db_connection()
    cursor = db.cursor()
    try:
        if photo_filename:
            cursor.execute("""
                UPDATE student SET phone=%s, year=%s, department=%s, semester=%s, profile_photo=%s
                WHERE student_id=%s
            """, (phone or None, year, department or None, semester, photo_filename, session['user_id']))
        else:
            cursor.execute("""
                UPDATE student SET phone=%s, year=%s, department=%s, semester=%s
                WHERE student_id=%s
            """, (phone or None, year, department or None, semester, session['user_id']))
        db.commit()
        if semester:
            session['semester'] = semester
        flash("Profile updated successfully!", "success")
    except Exception as e:
        db.rollback()
        flash(f"Error updating profile: {e}", "error")
    db.close()
    return redirect(url_for('student.student_dashboard'))

@student_bp.route('/register-event/<int:event_id>', methods=['GET', 'POST'])
@login_required
@role_required('student')
def register_for_event(event_id):
    time.sleep(3)
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    
    # Check Event Status
    cursor.execute("SELECT * FROM events WHERE event_id=%s", (event_id,))
    event = cursor.fetchone()
    
    if not event:
        db.close()
        flash("Event not found.", "error")
        return redirect(url_for('student.student_dashboard'))
        
    if event.get('status') == 'Closed':
        db.close()
        flash("Registration is closed for this event.", "error")
        return redirect(url_for('student.student_dashboard'))
        
    # Check Deadline (2 Days Before)
    e_date = event['event_date']
    if isinstance(e_date, str):
        e_date = datetime.strptime(e_date, '%Y-%m-%d').date()
    
    current_date = datetime.now().date()
    if (e_date - current_date).days < 2:
        db.close()
        flash("Registration deadline has passed (must register 2 days in advance).", "error")
        return redirect(url_for('student.student_dashboard'))
    
    cursor.execute("""
        SELECT registration_id FROM registrations 
        WHERE student_id=%s AND event_id=%s
    """, (session['user_id'], event_id))
    if cursor.fetchone():
        db.close()
        flash("You are already registered for this event.", "info")
        return redirect(url_for('student.student_dashboard'))
        
    cursor.execute("""
        SELECT waitlist_id FROM waitlist 
        WHERE student_id=%s AND event_id=%s
    """, (session['user_id'], event_id))
    if cursor.fetchone():
        db.close()
        flash("You are already on the waitlist for this event.", "warning")
        return redirect(url_for('student.student_dashboard'))
    
    if request.method == 'POST':
        req_fields = ['name', 'register_number', 'email', 'semester']
        for field in req_fields:
            if not request.form.get(field):
                db.close()
                flash(f"{field.replace('_', ' ').capitalize()} is required.", "error")
                return redirect(url_for('student.student_dashboard'))
        
        try:
            # Save face photo if event requires it and one was submitted
            face_photo_b64 = request.form.get('face_photo', '')
            if event.get('require_face_photo') and face_photo_b64 and face_photo_b64.startswith('data:image'):
                import base64
                header, encoded = face_photo_b64.split(',', 1)
                img_bytes = base64.b64decode(encoded)
                photo_filename = f"{session['user_id']}.jpg"
                portraits_dir = os.path.join(os.path.dirname(__file__), '..', 'static', 'uploads', 'portraits')
                os.makedirs(portraits_dir, exist_ok=True)
                with open(os.path.join(portraits_dir, photo_filename), 'wb') as f:
                    f.write(img_bytes)
                # Update student profile_photo if not already set
                cursor.execute(
                    "UPDATE student SET profile_photo=%s WHERE student_id=%s AND (profile_photo IS NULL OR profile_photo='')",
                    (photo_filename, session['user_id'])
                )

            cursor.execute("SELECT COUNT(*) as total FROM registrations WHERE event_id=%s", (event_id,))
            current_count = cursor.fetchone()['total']
            
            cursor.execute("SELECT max_seats FROM events WHERE event_id=%s", (event_id,))
            max_seats = cursor.fetchone()['max_seats']

            if current_count < max_seats:
                qr_token = str(uuid.uuid4())
                cursor.execute("""
                    INSERT INTO registrations (student_id, event_id, qr_token) 
                    VALUES (%s, %s, %s)
                """, (session['user_id'], event_id, qr_token))
                db.commit()

                # Event details are already in 'event' variable
                
                cursor.execute("SELECT email, name FROM student WHERE student_id=%s", (session['user_id'],))
                student = cursor.fetchone()

                qr = qrcode.make(qr_token)
                buffer = BytesIO()
                qr.save(buffer, format="PNG")
                img_data = buffer.getvalue()

                html_body = f"""
                <h3>Registration Confirmed!</h3>
                <p>Hello {student['name']},</p>
                <p>You have successfully registered for:</p>
                <ul>
                    <li><strong>Event:</strong> {event['event_name']}</li>
                    <li><strong>Date:</strong> {event['event_date']}</li>
                    <li><strong>Location:</strong> {event['location']}</li>
                </ul>
                <p>Please show the QR code below during attendance:</p>
                <div style="text-align: center;">
                    <img src="cid:qr_code" alt="QR Code" style="width: 200px; height: 200px;">
                </div>
                """
                
                attachment = {
                    'filename': 'qrcode.png',
                    'content_type': 'image/png',
                    'data': img_data,
                    'headers': {'Content-ID': '<qr_code>'}
                }
                
                send_email("Event Registration Successful", [student['email']], html=html_body, attachments=[attachment])

                add_notification(session['user_id'], 'student', f"Registered: {event['event_name']}.")
                add_notification(event['coordinator_id'], 'faculty', f"Reg: {student['name']} - {event['event_name']}.")
                notify_admins(f"Reg: {student['name']} - {event['event_name']}.")

                flash("Successfully registered! Confirmation email with QR code sent.", "success")
            else:
                cursor.execute("SELECT COUNT(*) as wait_count FROM waitlist WHERE event_id=%s", (event_id,))
                wait_position = cursor.fetchone()['wait_count'] + 1

                cursor.execute("""
                    INSERT INTO waitlist (event_id, student_id, position)
                    VALUES (%s, %s, %s)
                """, (event_id, session['user_id'], wait_position))
                db.commit()

                add_notification(session['user_id'], 'student', f"Waitlisted (Position {wait_position}): {event['event_name']}.")
                flash(f"Event is full. You have been added to the waitlist at position {wait_position}.", "warning")
                
            db.close()

        except Exception as e:
            db.rollback()
            db.close()
            flash(f"Error during registration: {str(e)}", "error")

        return redirect(url_for('student.student_dashboard'))
    
    db.close()
    return redirect(url_for('student.student_dashboard'))

@student_bp.route('/cancel-registration/<int:reg_id>')
@login_required
@role_required('student')
def cancel_registration(reg_id):
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT r.event_id, e.event_date, r.attendance 
        FROM registrations r
        JOIN events e ON r.event_id = e.event_id
        WHERE r.registration_id=%s AND r.student_id=%s
    """, (reg_id, session['user_id']))
    record = cursor.fetchone()

    if not record:
        db.close()
        flash("Registration not found or access denied.", "error")
        return redirect(url_for('student.student_dashboard'))
    
    event_date = record['event_date']
    if isinstance(event_date, str):
        event_date = datetime.strptime(event_date, '%Y-%m-%d').date()
        
    current_date = datetime.now().date()

    if record['attendance'] == 'Present':
        db.close()
        flash("Cannot cancel registration. You have already participated/attended this event.", "error")
        return redirect(url_for('student.student_dashboard'))
    
    if event_date < (current_date + timedelta(days=2)):
        db.close()
        flash("Cannot cancel registration. Cancellation is only allowed 2 days before the event.", "error")
        return redirect(url_for('student.student_dashboard'))

    try:
        cursor.execute("DELETE FROM registrations WHERE registration_id=%s", (reg_id,))
        event_id = record['event_id']
        
        # Check if there is someone in waitlist for this event
        cursor.execute("""
            SELECT * FROM waitlist
            WHERE event_id=%s
            ORDER BY position ASC
            LIMIT 1
        """, (event_id,))
        next_student = cursor.fetchone()

        if next_student:
            qr_token = str(uuid.uuid4())
            cursor.execute("""
                INSERT INTO registrations (student_id, event_id, qr_token)
                VALUES (%s, %s, %s)
            """, (next_student['student_id'], event_id, qr_token))

            cursor.execute("DELETE FROM waitlist WHERE waitlist_id=%s", (next_student['waitlist_id'],))

            cursor.execute("""
                UPDATE waitlist
                SET position = position - 1
                WHERE event_id=%s AND position > %s
            """, (event_id, next_student['position']))

            # Notify student
            cursor.execute("SELECT email, name FROM student WHERE student_id=%s", (next_student['student_id'],))
            s_record = cursor.fetchone()
            if s_record:
                qr = qrcode.make(qr_token)
                buffer = BytesIO()
                qr.save(buffer, format="PNG")
                img_data = buffer.getvalue()
                
                cursor.execute("SELECT event_name, event_date, location FROM events WHERE event_id=%s", (event_id,))
                wait_event = cursor.fetchone()

                html_body = f"""
                <h3>Seat Available! Registration Confirmed.</h3>
                <p>Hello {s_record['name']},</p>
                <p>You have been moved from the waitlist to confirmed registration for:</p>
                <ul>
                    <li><strong>Event:</strong> {wait_event['event_name']}</li>
                    <li><strong>Date:</strong> {wait_event['event_date']}</li>
                    <li><strong>Location:</strong> {wait_event['location']}</li>
                </ul>
                <p>Please show the QR code below during attendance:</p>
                <div style="text-align: center;">
                    <img src="cid:qr_code" alt="QR Code" style="width: 200px; height: 200px;">
                </div>
                """
                
                attachment = {
                    'filename': 'qrcode.png',
                    'content_type': 'image/png',
                    'data': img_data,
                    'headers': {'Content-ID': '<qr_code>'}
                }
                
                send_email("Seat Available - Registration Confirmed!", [s_record['email']], html=html_body, attachments=[attachment])
                add_notification(next_student['student_id'], 'student', f"Waitlist cleared! You are now registered for {wait_event['event_name']}.")

        db.commit()
        flash("Registration cancelled successfully.", "success")
    except Exception as e:
        db.rollback()
        flash(f"Error checking cancellation: {str(e)}", "error")
        
    db.close()
    return redirect(url_for('student.student_dashboard'))

@student_bp.route('/cancel-waitlist/<int:waitlist_id>')
@login_required
@role_required('student')
def cancel_waitlist(waitlist_id):
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT event_id, position 
        FROM waitlist
        WHERE waitlist_id=%s AND student_id=%s
    """, (waitlist_id, session['user_id']))
    record = cursor.fetchone()

    if not record:
        db.close()
        flash("Waitlist entry not found or access denied.", "error")
        return redirect(url_for('student.student_dashboard'))
    
    try:
        # Delete from waitlist
        cursor.execute("DELETE FROM waitlist WHERE waitlist_id=%s", (waitlist_id,))
        
        # Shift positions
        cursor.execute("""
            UPDATE waitlist
            SET position = position - 1
            WHERE event_id=%s AND position > %s
        """, (record['event_id'], record['position']))
        
        db.commit()
        flash("Successfully removed from the waitlist.", "success")
    except Exception as e:
        db.rollback()
        flash(f"Error checking cancellation: {str(e)}", "error")
        
    db.close()
    return redirect(url_for('student.student_dashboard'))

@student_bp.route('/submit-feedback', methods=['POST'])
@login_required
def submit_feedback():
    if session.get('role') != 'student':
        abort(403)
        
    event_id = request.form['event_id']
    rating = request.form['rating']
    comments = request.form['comments']
    student_id = session['user_id']

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM feedback WHERE event_id=%s AND student_id=%s", (event_id, student_id))
    if cursor.fetchone():
        db.close()
        flash("You have already submitted feedback.", "warning")
        return redirect(url_for('student.student_dashboard'))
        
    try:
        cursor.execute("""
            INSERT INTO feedback (event_id, student_id, rating, comments)
            VALUES (%s, %s, %s, %s)
        """, (event_id, student_id, rating, comments))
        db.commit()
        flash("Thank you for your feedback!", "success")
    except Exception as e:
        db.rollback()
        flash(f"Error submitting feedback: {str(e)}", "error")
        
    db.close()
    return redirect(url_for('student.student_dashboard'))

@student_bp.route('/student/timetable')
@login_required
@role_required('student')
def student_timetable():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("SELECT student_id, name, department, semester FROM student WHERE student_id=%s", (session['user_id'],))
    student = cursor.fetchone()
    
    if not student:
        db.close()
        flash("Student profile not found.", "error")
        return redirect(url_for('student.student_dashboard'))
        
    cursor.execute("""
        SELECT t.*, c.course_name, f.name as faculty_name
        FROM timetable t
        LEFT JOIN courses c ON t.course_id = c.course_id
        LEFT JOIN faculty f ON t.faculty_id = f.faculty_id
        WHERE t.department = %s AND t.semester = %s
        ORDER BY FIELD(day, 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'), CAST(start_time AS TIME)
    """, (student['department'], student['semester']))
    timetable = cursor.fetchall()
    db.close()
    return render_template('student_timetable.html', timetable=timetable, student=student)

@student_bp.route('/request-onduty/<int:reg_id>')
@login_required
@role_required('student')
def request_onduty(reg_id):
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT * FROM registrations 
        WHERE registration_id=%s AND student_id=%s AND attendance='Present'
    """, (reg_id, session['user_id']))
    reg = cursor.fetchone()
    
    if not reg:
        db.close()
        flash("Cannot request On-Duty. Either attendance not marked or not registered.", "error")
        return redirect(url_for('student.student_dashboard'))
        
    cursor.execute("""
        SELECT request_id FROM onduty_requests 
        WHERE student_id=%s AND event_id=%s
    """, (session['user_id'], reg['event_id']))
    existing = cursor.fetchone()
    
    if existing:
        db.close()
        flash("On-Duty request already submitted for this event.", "warning")
        return redirect(url_for('student.student_dashboard'))
        
    try:
        cursor.execute("""
            INSERT INTO onduty_requests (student_id, event_id, status)
            VALUES (%s, %s, 'Pending')
        """, (session['user_id'], reg['event_id']))
        db.commit()
        flash("On-Duty request submitted successfully!", "success")
    except Exception as e:
        db.rollback()
        flash(f"Error submitting request: {e}", "error")
        
    db.close()
    return redirect(url_for('student.student_dashboard'))

@student_bp.route('/student/exams')
@login_required
@role_required('student')
def student_exams():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("SELECT department, semester FROM student WHERE student_id=%s", (session['user_id'],))
    student = cursor.fetchone()
    
    if not student:
        db.close()
        flash("Student record not found.", "error")
        return redirect(url_for('student.student_dashboard'))
        
    cursor.execute("""
        SELECT e.*, c.course_name, c.department, c.semester 
        FROM exams e 
        JOIN courses c ON e.course_id = c.course_id 
        WHERE c.department = %s AND c.semester = %s
        ORDER BY e.exam_date, e.start_time
    """, (student['department'], student['semester']))
    exams = cursor.fetchall()
    
    next_exam = None
    now = datetime.now()
    
    for ex in exams:
        time_str = ""
        if isinstance(ex['start_time'], timedelta):
            total_seconds = int(ex['start_time'].total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            time_str = f"{hours:02}:{minutes:02}"
            ex['start_time'] = time_str
        else:
            time_str = str(ex['start_time'])[:5]
            ex['start_time'] = time_str
            
        if isinstance(ex['end_time'], timedelta):
             total_seconds = int(ex['end_time'].total_seconds())
             hours = total_seconds // 3600
             minutes = (total_seconds % 3600) // 60
             ex['end_time'] = f"{hours:02}:{minutes:02}"
        else:
             ex['end_time'] = str(ex['end_time'])[:5]

        if not next_exam:
            try:
                dt_str = f"{ex['exam_date']} {time_str}"
                if len(time_str) == 5:
                    exam_dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M')
                else:
                    exam_dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
                    
                if exam_dt > now:
                    next_exam = ex
            except Exception as e:
                pass
                
    db.close()
    return render_template('student_exams.html', exams=exams, next_exam=next_exam)

@student_bp.route('/download-certificate/<int:reg_id>')
@login_required
def download_certificate(reg_id):
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT r.*, s.name as student_name, e.event_name, e.event_date 
        FROM registrations r
        JOIN student s ON r.student_id = s.student_id
        JOIN events e ON r.event_id = e.event_id
        WHERE r.registration_id=%s
    """, (reg_id,))
    record = cursor.fetchone()
    db.close()
    
    if not record:
        abort(404)
        
    if session.get('role') == 'student' and record['student_id'] != session.get('user_id'):
        abort(403)

    if record['certificate_status'] != 'Approved':
         flash("Certificate not available yet.", "error")
         return redirect(url_for('student.student_dashboard'))
         
    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=False, margin=0)
    pdf.add_page()
    
    pdf.set_line_width(1.0)
    pdf.set_draw_color(50, 50, 100)
    pdf.rect(10, 10, 277, 190)
    
    pdf.set_line_width(0.5)
    pdf.set_draw_color(200, 150, 50)
    pdf.rect(13, 13, 271, 184)

    pdf.set_y(25)
    pdf.set_font("Times", 'B', 30)
    pdf.set_text_color(50, 50, 100)
    pdf.cell(0, 10, 'CAMPUS EVENT PORTAL UNIVERSITY', 0, 1, 'C')
    
    pdf.set_y(45)
    pdf.set_font("Times", 'B', 40)
    pdf.set_text_color(200, 150, 50)
    pdf.cell(0, 15, 'CERTIFICATE', 0, 1, 'C')
    
    pdf.set_font("Times", '', 18)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 10, 'OF PARTICIPATION', 0, 1, 'C')

    pdf.ln(15)
    pdf.set_font("Arial", '', 16)
    pdf.cell(0, 10, 'This is to certify that', 0, 1, 'C')
    
    pdf.ln(5)
    pdf.set_font("Times", 'BI', 32)
    pdf.set_text_color(50, 50, 100)
    pdf.cell(0, 15, record['student_name'], 0, 1, 'C')
    
    pdf.ln(5)
    pdf.set_font("Arial", '', 16)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 10, 'has successfully participated in the event', 0, 1, 'C')
    
    pdf.ln(5)
    pdf.set_font("Helvetica", 'B', 24)
    pdf.cell(0, 15, record['event_name'].upper(), 0, 1, 'C')
    
    pdf.ln(2)
    pdf.set_font("Arial", '', 14)
    pdf.cell(0, 10, f"Held on {record['event_date']}", 0, 1, 'C')

    pdf.set_y(-55)
    
    pdf.set_x(40)
    pdf.set_font("Times", 'I', 14)
    pdf.cell(60, 10, "Coordinator", 0, 1, 'C') 
    pdf.set_x(40)
    pdf.cell(60, 0, "__________________________", 0, 1, 'C')
    pdf.set_x(40)
    pdf.set_font("Arial", '', 10)
    pdf.cell(60, 10, "Event Coordinator", 0, 0, 'C')

    pdf.set_xy(133, 155)
    pdf.set_draw_color(200, 150, 50)
    pdf.set_line_width(0.5)
    pdf.ellipse(133.5, 155, 30, 30) 
    
    pdf.set_xy(133.5, 165)
    pdf.set_font("Times", 'B', 8)
    pdf.set_text_color(200, 150, 50)
    pdf.cell(30, 5, "OFFICIAL", 0, 1, 'C')
    pdf.set_xy(133.5, 170)
    pdf.cell(30, 5, "SEAL", 0, 1, 'C')

    pdf.set_y(-55)
    pdf.set_x(190)
    pdf.set_font("Times", 'I', 14)
    pdf.cell(60, 10, "Dr. Principal Name", 0, 1, 'C')
    pdf.set_x(190)
    pdf.cell(60, 0, "__________________________", 0, 1, 'C')
    pdf.set_x(190)
    pdf.set_font("Arial", '', 10)
    pdf.cell(60, 10, "Dean of Students", 0, 0, 'C')

    pdf.set_y(-20)
    pdf.set_font("Courier", '', 8)
    pdf.set_text_color(150, 150, 150)
    reg_id_str = str(record['registration_id']).zfill(6)
    pdf.cell(0, 10, f"Certificate ID: CEP-{reg_id_str} | Verified by Campus Event Portal", 0, 1, 'C')

    response = make_response(pdf.output(dest='S').encode('latin-1'))
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=Certificate_{record["event_name"]}.pdf'
    return response

@student_bp.route('/chatbot', methods=['POST'])
@login_required
@role_required('student')
def chatbot():
    data = request.get_json()
    user_message = data.get('message', '')
    
    if not user_message:
        return jsonify({"reply": "I'm listening! Ask me anything about events, campus points, or your registrations."})

    # Get Groq Key from app config
    api_key = current_app.config.get('GROQ_API_KEY')
    if not api_key:
        return jsonify({"reply": "System Error: AI API Key not configured."})

    client = Groq(api_key=api_key)
    model_name = "llama-3.3-70b-versatile"

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        user_id=session['user_id'],
        date=datetime.now().strftime('%Y-%m-%d')
    )

    try:
        # Step 1: Request SQL or direct answer from Groq
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            model=model_name,
        )
        ai_response = chat_completion.choices[0].message.content.strip()
        
        # Check if AI returned SQL (searching for JSON structure)
        if ai_response.startswith('{') and '"sql"' in ai_response:
            try:
                # Clean potential markdown backticks from AI response
                clean_json = ai_response.replace('```json', '').replace('```', '').strip()
                potential_sql = json.loads(clean_json)
                if "sql" in potential_sql:
                    query = potential_sql["sql"]
                    
                    # Security check
                    forbidden = ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE"]
                    if any(word in query.upper() for word in forbidden):
                        return jsonify({"reply": "I'm sorry, I can only perform data retrieval."})
                    
                    db = get_db_connection()
                    cursor = db.cursor(dictionary=True)
                    cursor.execute(query)
                    results = cursor.fetchall()
                    db.close()
                    
                    # Step 2: Narrate results using Groq
                    narration_prompt = f"The database returned these results: {results}. Narrate this to the user in response to: '{user_message}'"
                    narration_completion = client.chat.completions.create(
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": narration_prompt}
                        ],
                        model=model_name,
                    )
                    return jsonify({"reply": narration_completion.choices[0].message.content})
            except Exception as inner_e:
                print(f"Chatbot Inner Error: {inner_e}")
                pass # Fallback to direct response
        
        return jsonify({"reply": ai_response})
            
    except Exception as e:
        import traceback
        print(f"Chatbot Error: {e}")
        traceback.print_exc()
        return jsonify({"reply": "I'm having trouble connecting to my brain right now. Please try again later!"})
