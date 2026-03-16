import mysql.connector
from datetime import timedelta

def populate_sample_data():
    try:
        db = mysql.connector.connect(
            host="localhost",
            user="root",
            password="Delvin@2005",
            database="campus_event_db"
        )
        cursor = db.cursor(dictionary=True)

        print("--- Populating Students ---")
        students = [
            ("S001", "Abhijith", "abhijith@gmail.com", "CSE", "6"),
            ("S002", "Anjana", "anjana@gmail.com", "CSE", "6"),
            ("S003", "Bibin", "bibin@gmail.com", "CSE", "6"),
            ("S004", "Deepika", "deepika@gmail.com", "CSE", "6"),
            ("S005", "Gokul", "gokul@gmail.com", "CSE", "6"),
            ("S006", "Hridya", "hridya@gmail.com", "CSE", "6"),
            ("S007", "Irfan", "irfan@gmail.com", "CSE", "6"),
            ("S008", "Jibin", "jibin@gmail.com", "CSE", "6"),
            ("S009", "Karthik", "karthik@gmail.com", "CSE", "6"),
            ("S010", "Meenu", "meenu@gmail.com", "CSE", "6")
        ]

        for reg_no, name, email, dept, sem in students:
            cursor.execute("SELECT student_id FROM student WHERE email=%s", (email,))
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO student (register_number, name, email, department, semester, password)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (reg_no, name, email, dept, sem, 'scrypt:32768:8:1$defaultpassword')) # Generic pash
                print(f"Added Student: {name}")

        print("\n--- Fetching Courses and Faculty ---")
        cursor.execute("SELECT course_id, course_name FROM courses")
        courses = {c['course_name']: c['course_id'] for c in cursor.fetchall()}
        
        cursor.execute("SELECT faculty_id, name FROM faculty")
        faculty = {f['name']: f['faculty_id'] for f in cursor.fetchall()}

        print("\n--- Constructing Weekly Timetable ---")
        # Sample Weekly Slot Logic
        days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
        schedule_slots = [
            ("09:00", "10:00", "IEFT", "Ms.Lekha Krishnan", "305"),
            ("10:00", "11:00", "AAD", "Mr.Visakh Mohan", "305"),
            ("11:00", "11:15", "BREAK", None, "N/A"),
            ("11:15", "12:15", "Compiler Design", "Mr.Ranjith S", "305"),
            ("12:15", "01:15", "LUNCH", None, "N/A"),
            ("01:15", "02:15", "Data Analystic", "Anjitha ", "305"),
            ("02:15", "03:15", "CG", "Ms.Sisira K I", "305"),
            ("03:15", "04:00", "Mini Project", "Ms.Cinu Joseph", "305"),
        ]

        # Clean existing timetable to avoid duplicates for this demo
        cursor.execute("DELETE FROM timetable")
        
        for day in days:
            for start, end, course_name, faculty_name, room in schedule_slots:
                c_id = courses.get(course_name)
                f_id = faculty.get(faculty_name)
                
                # Default for this seed data
                dept = "CSE"
                sem = "6"

                # If course exists, use its info (though for CSE 6 it's the same)
                if c_id:
                    cursor.execute("SELECT department, semester FROM courses WHERE course_id=%s", (c_id,))
                    info = cursor.fetchone()
                    if info:
                        dept = info['department']
                        sem = info['semester']
                
                cursor.execute("""
                    INSERT INTO timetable (course_id, faculty_id, day, start_time, end_time, classroom, department, semester)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (c_id, f_id, day, start, end, room, dept, sem))
            print(f"Assigned slots for {day}")

        db.commit()
        print("\nSUCCESS: All data added successfully!")
        db.close()
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    populate_sample_data()
