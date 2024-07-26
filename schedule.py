import json
from datetime import datetime, timedelta

def create_shift_scheduling_request(start_date, num_days, employees):
    shifts = []
    coverage_requirements = []
    
    for day in range(num_days):
        current_date = start_date + timedelta(days=day)
        shift_times = [
            (6, 14),  # 6am-2pm
            (8, 16),  # 8am-4pm
            (14, 22), # 2pm-10pm
            (22, 6)   # 10pm-6am
        ]
        
        for start_hour, end_hour in shift_times:
            shift_start = current_date.replace(hour=start_hour, minute=0)
            shift_end = current_date.replace(hour=end_hour, minute=0)
            if end_hour < start_hour:
                shift_end += timedelta(days=1)
            
            shift_id = f"{current_date.strftime('%A')}_{start_hour:02d}-{end_hour:02d}"
            
            shifts.append({
                "id": shift_id,
                "start_date_time": {
                    "year": shift_start.year,
                    "month": shift_start.month,
                    "day": shift_start.day,
                    "hours": shift_start.hour
                },
                "end_date_time": {
                    "year": shift_end.year,
                    "month": shift_end.month,
                    "day": shift_end.day,
                    "hours": shift_end.hour
                }
            })
            
            coverage_requirements.append({
                "start_date_time": {
                    "year": shift_start.year,
                    "month": shift_start.month,
                    "day": shift_start.day,
                    "hours": shift_start.hour
                },
                "end_date_time": {
                    "year": shift_end.year,
                    "month": shift_end.month,
                    "day": shift_end.day,
                    "hours": shift_end.hour
                },
                "role_requirements": [
                    {"role_id": "Employee", "target_employee_count": 1}
                ]
            })

    request = {
        "shifts": shifts,
        "employees": [{"id": employee, "role_ids": ["Employee"]} for employee in employees],
        "coverage_requirements": coverage_requirements,
        "role_ids": ["Employee"],
        "solve_parameters": {
            "time_limit": {"seconds": 30}
        },
        "shift_constraints": [
            {
                "max_consecutive_shifts": {"maximum": 3},
                "min_consecutive_shifts_off": {"minimum": 2},
                "max_shifts_per_week": {"maximum": 5},
                "min_shifts_per_week": {"minimum": 5}
            }
        ],
        "employee_shift_constraints": [
            {
                "min_hours_between_shifts": {"minimum": 16}
            }
        ]
    }

    return request

# Usage
start_date = datetime(2024, 7, 29)  # A Monday
num_days = 7
employees = ["Yusheen", "Roxanne", "Mpho", "Phumeza", "Hope", "Katlego", "John"]

request_data = create_shift_scheduling_request(start_date, num_days, employees)

# Save to file
with open('shift_scheduling_request.json', 'w') as f:
    json.dump(request_data, f, indent=2)

print("Request data saved to 'shift_scheduling_request.json'")