from flask import session, redirect, url_for, abort
from functools import wraps
from models.db import get_db_connection

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            # Redirect to login page - assuming 'auth.login' endpoint
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return wrapper

def role_required(role):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if session.get('role') != role:
                abort(403)
            return f(*args, **kwargs)
        return wrapper
    return decorator

def add_notification(user_id, role, message):
    try:
        db = get_db_connection()
        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO notifications (user_id, user_role, message) 
            VALUES (%s, %s, %s)
        """, (user_id, role, message))
        db.commit()
        db.close()
    except Exception as e:
        print(f"Error adding notification: {e}")

def notify_admins(message):
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT faculty_id FROM faculty WHERE is_admin = 1")
        admins = cursor.fetchall()
        
        cursor_insert = db.cursor()
        for admin in admins:
             cursor_insert.execute("""
                INSERT INTO notifications (user_id, user_role, message) 
                VALUES (%s, 'faculty', %s)
            """, (admin['faculty_id'], message))
        
        db.commit()
        db.close()
    except Exception as e:
        print(f"Error notifying admins: {e}")
