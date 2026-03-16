import mysql.connector

def fix_schema():
    try:
        db = mysql.connector.connect(
            host="localhost",
            user="root",
            password="Delvin@2005",
            database="campus_event_db"
        )
        cursor = db.cursor()
        
        # Ensure timetable has department and semester
        print("Checking timetable table...")
        cursor.execute("DESCRIBE timetable")
        columns = [row[0] for row in cursor.fetchall()]
        
        if 'department' not in columns:
            print("Adding department to timetable...")
            cursor.execute("ALTER TABLE timetable ADD COLUMN department VARCHAR(100)")
        if 'semester' not in columns:
            print("Adding semester to timetable...")
            cursor.execute("ALTER TABLE timetable ADD COLUMN semester VARCHAR(20)")

        # Ensure faculty has department
        print("Checking faculty table...")
        cursor.execute("DESCRIBE faculty")
        columns = [row[0] for row in cursor.fetchall()]
        if 'department' not in columns:
            print("Adding department to faculty...")
            cursor.execute("ALTER TABLE faculty ADD COLUMN department VARCHAR(100)")

        # Ensure courses has department
        print("Checking courses table...")
        cursor.execute("DESCRIBE courses")
        columns = [row[0] for row in cursor.fetchall()]
        if 'department' not in columns:
            print("Adding department to courses...")
            cursor.execute("ALTER TABLE courses ADD COLUMN department VARCHAR(100)")
            
        db.commit()
        print("Schema check/fix completed successfully.")
        db.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    fix_schema()
