import mysql.connector

def check_tables():
    db = mysql.connector.connect(
        host="localhost",
        user="root",
        password="Delvin@2005",
        database="campus_event_db"
    )
    cursor = db.cursor()
    tables = ['timetable', 'faculty', 'courses', 'student']
    for table in tables:
        print(f"\n--- Schema for {table} ---")
        cursor.execute(f"DESCRIBE {table}")
        for row in cursor.fetchall():
            print(row)
    db.close()

if __name__ == "__main__":
    check_tables()
