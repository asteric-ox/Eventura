import mysql.connector

def fix_onduty_schema():
    try:
        db = mysql.connector.connect(
            host="localhost",
            user="root",
            password="Delvin@2005",
            database="campus_event_db"
        )
        cursor = db.cursor()
        
        print("Checking onduty_requests table...")
        cursor.execute("DESCRIBE onduty_requests")
        columns = [row[0] for row in cursor.fetchall()]
        
        if 'timetable_id' not in columns:
            print("Adding timetable_id to onduty_requests...")
            cursor.execute("ALTER TABLE onduty_requests ADD COLUMN timetable_id INT NULL")
            cursor.execute("ALTER TABLE onduty_requests ADD CONSTRAINT fk_od_timetable FOREIGN KEY (timetable_id) REFERENCES timetable(timetable_id) ON DELETE SET NULL")
        
        if 'od_date' not in columns:
            print("Adding od_date to onduty_requests...")
            cursor.execute("ALTER TABLE onduty_requests ADD COLUMN od_date DATE NULL")

        if 'approved_by' not in columns:
            print("Adding approved_by to onduty_requests...")
            cursor.execute("ALTER TABLE onduty_requests ADD COLUMN approved_by INT NULL")
            
        db.commit()
        print("onduty_requests schema fixed successfully.")
        db.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    fix_onduty_schema()
