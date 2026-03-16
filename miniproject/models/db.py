import mysql.connector
import os

def get_db_connection():
    return mysql.connector.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", "Delvin@2005"),
        database=os.environ.get("DB_NAME", "campus_event_db")
    )
