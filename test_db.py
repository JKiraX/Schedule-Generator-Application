# test_db_connection.py
from app.scheduler.jobs import get_db_connection

def test_connection():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT version()')
        db_version = cur.fetchone()
        print(f'PostgreSQL database version: {db_version}')
        cur.close()
        conn.close()
    except Exception as error:
        print(f'Error: {error}')

if __name__ == "__main__":
    test_connection()
