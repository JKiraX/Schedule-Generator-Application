import requests
import json
import psycopg2
from datetime import datetime, timedelta
from config import db_config

def get_db_connection():
    return psycopg2.connect(**db_config)

def apply_constraints(shifts):
    adjusted_shifts = []
    streak_tracker = {}

    for shift in shifts:
        user_id = shift['userID']
        shift_date = datetime.fromtimestamp(shift['startTimeEpochSeconds'])

        if user_id not in streak_tracker:
            streak_tracker[user_id] = {"working_days": 0, "off_days": 0}

        if streak_tracker[user_id]["working_days"] < 3:
            streak_tracker[user_id]["working_days"] += 1
            streak_tracker[user_id]["off_days"] = 0
            adjusted_shifts.append(shift)
        else:
            streak_tracker[user_id]["off_days"] += 1
            if streak_tracker[user_id]["off_days"] == 2:
                streak_tracker[user_id]["working_days"] = 0
                streak_tracker[user_id]["off_days"] = 0

    return adjusted_shifts

def generate_weekly_schedule(start_date):
    end_point = "https://optimization.googleapis.com/v1/scheduling:solveShiftGeneration"
    with open("credentials.json") as f:
        credentials = json.load(f)
        api_key = credentials["key"]

    with open("example_request.json", "r") as f:
        json_request = json.load(f)
    
    json_request['employeeDemands'][0]['startDateTime'] = {
        "year": start_date.year,
        "month": start_date.month,
        "day": start_date.day
    }
    json_request['employeeDemands'][0]['endDateTime'] = {
        "year": (start_date + timedelta(days=6)).year,
        "month": (start_date + timedelta(days=6)).month,
        "day": (start_date + timedelta(days=6)).day,
        "hours": 23,
        "minutes": 59
    }

    response = requests.post(f"{end_point}?key={api_key}", json=json_request)
    
    if response.status_code == 200:
        return response.json()['shifts']
    else:
        print(f'Failed to generate shifts: {response.status_code} - {response.text}')
        return []

def generate_schedules():
    conn = get_db_connection()
    cur = conn.cursor()
    
    today = datetime.today()
    start_date = datetime(today.year, today.month, 1)
    end_date = start_date + timedelta(days=30)
    
    while start_date < end_date:
        weekly_shifts = generate_weekly_schedule(start_date)
        adjusted_shifts = apply_constraints(weekly_shifts)
        
        for shift in adjusted_shifts:
            shift_date = start_date + timedelta(minutes=shift['startTimeMinutes'])
            user_id = shift['userID']
            shift_id = shift['shiftID']
            schedule_hours = shift['durationMinutes'] / 60
            
            cur.execute(
                'INSERT INTO public.schedules (shiftDate, userID, shiftID, scheduleHours) VALUES (%s, %s, %s, %s)',
                (shift_date, user_id, shift_id, schedule_hours)
            )
        
        start_date += timedelta(days=7)
    
    conn.commit()
    cur.close()
    conn.close()

if __name__ == "__main__":
    generate_schedules()
