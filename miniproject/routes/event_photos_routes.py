import os
import uuid
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, abort
from werkzeug.utils import secure_filename
from models.db import get_db_connection

event_photos_bp = Blueprint('event_photos', __name__)

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), '..', 'static', 'uploads', 'event_photos')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_FILE_SIZE = 8 * 1024 * 1024  # 8MB


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def ensure_table():
    """Create event_photos table if it doesn't exist."""
    db = get_db_connection()
    cursor = db.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS event_photos (
            photo_id INT AUTO_INCREMENT PRIMARY KEY,
            event_id INT,
            title VARCHAR(255),
            filename VARCHAR(255) NOT NULL,
            uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (event_id) REFERENCES events(event_id) ON DELETE SET NULL
        )
    """)
    db.commit()
    db.close()


# ── Public Gallery (no login needed) ──────────────────────────────────────────
@event_photos_bp.route('/event-gallery')
def event_gallery():
    ensure_table()
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT ep.*, e.event_name, e.event_date, e.event_type
        FROM event_photos ep
        LEFT JOIN events e ON ep.event_id = e.event_id
        ORDER BY ep.uploaded_at DESC
    """)
    photos = cursor.fetchall()

    cursor.execute("SELECT event_id, event_name FROM events ORDER BY event_date DESC")
    events = cursor.fetchall()
    db.close()
    return render_template('event_gallery.html', photos=photos, events=events)


# ── Admin: Manage Event Photos ─────────────────────────────────────────────────
@event_photos_bp.route('/admin/event-photos', methods=['GET', 'POST'])
def admin_event_photos():
    if not session.get('is_admin'):
        abort(403)
    ensure_table()
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    if request.method == 'POST':
        event_id = request.form.get('event_id') or None
        title = request.form.get('title', '').strip()
        files = request.files.getlist('photos')

        if not files or all(f.filename == '' for f in files):
            flash("Please select at least one photo.", "error")
            return redirect(url_for('event_photos.admin_event_photos'))

        uploaded = 0
        for f in files:
            if f and allowed_file(f.filename):
                ext = f.filename.rsplit('.', 1)[1].lower()
                unique_name = f"{uuid.uuid4().hex}.{ext}"
                save_path = os.path.join(UPLOAD_FOLDER, unique_name)
                os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                f.save(save_path)

                photo_title = title or secure_filename(f.filename.rsplit('.', 1)[0])
                cursor.execute(
                    "INSERT INTO event_photos (event_id, title, filename) VALUES (%s, %s, %s)",
                    (event_id, photo_title, unique_name)
                )
                uploaded += 1

        db.commit()
        flash(f"{uploaded} photo(s) uploaded successfully!", "success")
        db.close()
        return redirect(url_for('event_photos.admin_event_photos'))

    # GET — load all photos and events
    cursor.execute("""
        SELECT ep.*, e.event_name
        FROM event_photos ep
        LEFT JOIN events e ON ep.event_id = e.event_id
        ORDER BY ep.uploaded_at DESC
    """)
    photos = cursor.fetchall()
    cursor.execute("SELECT event_id, event_name FROM events ORDER BY event_date DESC")
    events = cursor.fetchall()
    db.close()
    return render_template('admin_event_photos.html', photos=photos, events=events)


# ── Admin: Delete a photo ──────────────────────────────────────────────────────
@event_photos_bp.route('/admin/event-photos/delete/<int:photo_id>')
def delete_event_photo(photo_id):
    if not session.get('is_admin'):
        abort(403)
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT filename FROM event_photos WHERE photo_id = %s", (photo_id,))
    photo = cursor.fetchone()
    if photo:
        file_path = os.path.join(UPLOAD_FOLDER, photo['filename'])
        if os.path.exists(file_path):
            os.remove(file_path)
        cursor.execute("DELETE FROM event_photos WHERE photo_id = %s", (photo_id,))
        db.commit()
        flash("Photo deleted.", "success")
    db.close()
    return redirect(url_for('event_photos.admin_event_photos'))
