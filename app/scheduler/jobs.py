import requests
import json
import psycopg2
from datetime import datetime, timedelta
from config import db_config

def get_db_connection():
    conn = psycopg2.connect(**db_config)
    return conn

def generate_monthly_schedules():
    with open('credentials.json') as f:
        credentials = json.load(f)
    api_key = credentials['key']
    
    url = 'https://your-google-or-api-endpoint'
    headers = {'Authorization': f'Bearer {api_key}'}
    
    with open('example_request.json') as f:
        api_request_data = json.load(f)
    
    response = requests.post(url, json=api_request_data, headers=headers)
    
    if response.status_code == 200:
        shift_data = response.json()
        
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Generate schedules for a month
        today = datetime.today()
        start_date = datetime(today.year, today.month, 1)
        end_date = start_date + timedelta(days=30)
        
        while start_date < end_date:
            for shift in shift_data['shifts']:
                cur.execute(
                    'INSERT INTO schedules (date, shift_details) VALUES (%s, %s)',
                    (start_date, json.dumps(shift))
                )
            start_date += timedelta(days=1)
        
        conn.commit()
        cur.close()
        conn.close()
    else:
        print(f'Failed to generate shifts: {response.status_code}')

if __name__ == "__main__":
    generate_monthly_schedules()
