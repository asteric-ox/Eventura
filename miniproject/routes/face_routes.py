import os, base64, uuid
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, abort
from utils.helpers import login_required
from models.db import get_db_connection

face_bp = Blueprint('face', __name__)

PORTRAITS_DIR = os.path.join(os.path.dirname(__file__), '..', 'static', 'uploads', 'portraits')
FACE_DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'static', 'uploads', 'face_data')

# ── Lazy-load face_recognition (requires dlib / cmake) ────────────────────────
def _get_fr():
    try:
        import face_recognition
        return face_recognition
    except ImportError:
        return None

def _get_cv2():
    try:
        import cv2
        return cv2
    except ImportError:
        return None


def ensure_tables():
    db = get_db_connection()
    cursor = db.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS face_data (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            user_role ENUM('student','faculty') NOT NULL DEFAULT 'student',
            image_path VARCHAR(512),
            encoding LONGBLOB,
            captured_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.commit()
    db.close()


def load_known_faces():
    """Load all face encodings from DB into memory."""
    fr = _get_fr()
    if not fr:
        return []
    import numpy as np
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT user_id, user_role, encoding, image_path FROM face_data WHERE encoding IS NOT NULL")
    rows = cursor.fetchall()
    db.close()
    known = []
    for row in rows:
        if row['encoding']:
            enc = np.frombuffer(row['encoding'], dtype=np.float64)
            known.append((enc, row['user_id'], row['user_role'], row['image_path']))
    return known


def decode_image(data_url):
    """Decode a base64 data URL to an OpenCV numpy array (BGR)."""
    import numpy as np
    cv2 = _get_cv2()
    if not cv2:
        return None
    header, encoded = data_url.split(',', 1)
    img_bytes = base64.b64decode(encoded)
    arr = np.frombuffer(img_bytes, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def save_portrait(frame, user_id, role, face_location=None):
    """Crop and save the face portrait, return the relative path."""
    cv2 = _get_cv2()
    fr = _get_fr()
    if not cv2 or not fr:
        return None
    if frame is None:
        return None
    os.makedirs(PORTRAITS_DIR, exist_ok=True)
    if face_location:
        top, right, bottom, left = face_location
        pad = 20
        top = max(0, top - pad)
        left = max(0, left - pad)
        bottom = min(frame.shape[0], bottom + pad)
        right = min(frame.shape[1], right + pad)
        face_img = frame[top:bottom, left:right]
    else:
        face_img = frame
    filename = f"{role}_{user_id}.jpg"
    abs_path = os.path.join(PORTRAITS_DIR, filename)
    cv2.imwrite(abs_path, face_img)
    return f"static/uploads/portraits/{filename}"


# ──────────────────────────────────────────────────────────────────────────────
# PUBLIC: Face Recognition Page (login required)
# ──────────────────────────────────────────────────────────────────────────────
@face_bp.route('/face-system')
@login_required
def face_system():
    ensure_tables()
    fr_available = _get_fr() is not None
    cv2_available = _get_cv2() is not None
    return render_template('face_system.html',
                           fr_available=fr_available,
                           cv2_available=cv2_available)


# ──────────────────────────────────────────────────────────────────────────────
# API: Recognize a face from a captured image
# ──────────────────────────────────────────────────────────────────────────────
@face_bp.route('/recognize', methods=['POST'])
@login_required
def recognize():
    fr = _get_fr()
    cv2 = _get_cv2()
    if not fr or not cv2:
        return jsonify({"status": "error", "message": "face_recognition library not installed. See setup instructions."})

    data = request.json
    if not data or 'image' not in data:
        return jsonify({"status": "error", "message": "No image data received."})

    frame = decode_image(data['image'])
    if frame is None:
        return jsonify({"status": "error", "message": "Could not decode image."})

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    face_locations = fr.face_locations(rgb, model='hog')

    if not face_locations:
        return jsonify({"status": "no_face", "message": "No face detected. Please look at the camera."})

    face_encodings = fr.face_encodings(rgb, face_locations)
    if not face_encodings:
        return jsonify({"status": "no_face", "message": "Could not encode face. Try better lighting."})

    face_enc = face_encodings[0]

    # ── Only compare against the currently logged-in user's own enrolled face ──
    import numpy as np
    uid = session['user_id']
    role = session.get('role', 'student')

    ensure_tables()
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    cursor.execute(
        "SELECT encoding, image_path FROM face_data WHERE user_id=%s AND user_role=%s AND encoding IS NOT NULL",
        (uid, role)
    )
    row = cursor.fetchone()
    db.close()

    if not row or not row['encoding']:
        return jsonify({
            "status": "not_enrolled",
            "message": "You have not enrolled your face yet. Switch to 'Enroll My Face' mode first."
        })

    known_enc = np.frombuffer(row['encoding'], dtype=np.float64)
    matches = fr.compare_faces([known_enc], face_enc, tolerance=0.55)
    dist = fr.face_distance([known_enc], face_enc)[0]

    if matches[0]:
        portrait = save_portrait(frame, uid, role, face_locations[0])
        return jsonify({
            "status": "recognized",
            "user_id": uid,
            "role": role,
            "portrait": "/" + portrait if portrait else None,
            "confidence": round((1 - float(dist)) * 100, 1)
        })

    return jsonify({
        "status": "unknown",
        "message": "Your face could not be verified. Please ensure good lighting and try again."
    })


# ──────────────────────────────────────────────────────────────────────────────
# API: Enroll - register the current user's face
# ──────────────────────────────────────────────────────────────────────────────
@face_bp.route('/enroll-face', methods=['POST'])
@login_required
def enroll_face():
    fr = _get_fr()
    cv2 = _get_cv2()
    if not fr or not cv2:
        return jsonify({"status": "error", "message": "face_recognition library not installed."})

    data = request.json
    if not data or 'image' not in data:
        return jsonify({"status": "error", "message": "No image data."})

    frame = decode_image(data['image'])
    if frame is None:
        return jsonify({"status": "error", "message": "Could not decode image."})

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    face_locations = fr.face_locations(rgb)
    encodings = fr.face_encodings(rgb, face_locations)

    if not encodings:
        return jsonify({"status": "no_face", "message": "No face detected. Please look at the camera."})

    enc_bytes = encodings[0].tobytes()
    uid = session['user_id']
    role = session.get('role', 'student')

    portrait_path = save_portrait(frame, uid, role, face_locations[0])

    ensure_tables()
    db = get_db_connection()
    cursor = db.cursor()
    # Upsert: delete old, insert new
    cursor.execute("DELETE FROM face_data WHERE user_id=%s AND user_role=%s", (uid, role))
    cursor.execute(
        "INSERT INTO face_data (user_id, user_role, image_path, encoding) VALUES (%s, %s, %s, %s)",
        (uid, role, portrait_path, enc_bytes)
    )
    db.commit()
    db.close()

    return jsonify({
        "status": "enrolled",
        "message": "Face enrolled successfully!",
        "portrait": "/" + portrait_path if portrait_path else None
    })


# ──────────────────────────────────────────────────────────────────────────────
# ADMIN: View all enrolled faces
# ──────────────────────────────────────────────────────────────────────────────
@face_bp.route('/admin/face-data')
@login_required
def admin_face_data():
    if not session.get('is_admin'):
        abort(403)
    ensure_tables()
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT fd.id, fd.user_id, fd.user_role, fd.image_path, fd.captured_at,
               COALESCE(s.name, f.name) as user_name,
               COALESCE(s.register_number, f.email) as user_identifier
        FROM face_data fd
        LEFT JOIN student s ON fd.user_id = s.student_id AND fd.user_role = 'student'
        LEFT JOIN faculty f ON fd.user_id = f.faculty_id AND fd.user_role = 'faculty'
        ORDER BY fd.captured_at DESC
    """)
    face_records = cursor.fetchall()
    db.close()
    return render_template('admin_face_data.html', face_records=face_records)


# ── Admin: Delete a face record ────────────────────────────────────────────────
@face_bp.route('/admin/face-data/delete/<int:record_id>')
@login_required
def delete_face_record(record_id):
    if not session.get('is_admin'):
        abort(403)
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT image_path FROM face_data WHERE id=%s", (record_id,))
    row = cursor.fetchone()
    if row and row['image_path']:
        abs_path = os.path.join(os.path.dirname(__file__), '..', row['image_path'])
        if os.path.exists(abs_path):
            os.remove(abs_path)
    cursor.execute("DELETE FROM face_data WHERE id=%s", (record_id,))
    db.commit()
    db.close()
    flash("Face record deleted.", "success")
    return redirect(url_for('face.admin_face_data'))
