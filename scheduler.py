from pulp import *
import datetime

def create_two_month_shift_schedule(employees, shifts, start_date):
    num_days_per_month = 28
    num_months = 2
    num_employees = len(employees)
    num_shifts = len(shifts)
    
    full_schedule = {}
    
    for month in range(num_months):
        # Create the model
        prob = LpProblem(f"ShiftScheduling_Month_{month}", LpMaximize)
        
        # Decision Variables
        shift_vars = LpVariable.dicts("shift",
                                    ((e, d, s) for e in range(num_employees) 
                                     for d in range(num_days_per_month) 
                                     for s in range(num_shifts)),
                                    cat='Binary')
        
        # Objective: Maximize fairness (we'll use equal distribution as a proxy)
        prob += lpSum(shift_vars[e,d,s] 
                     for e in range(num_employees) 
                     for d in range(num_days_per_month) 
                     for s in range(num_shifts))
        
        # Constraint: Each employee works exactly 20 days in a month
        for e in range(num_employees):
            prob += lpSum(shift_vars[e,d,s] 
                         for d in range(num_days_per_month) 
                         for s in range(num_shifts)) == 20
        
        # Constraint: No more than 3 consecutive working days
        for e in range(num_employees):
            for d in range(num_days_per_month - 3):
                prob += lpSum(shift_vars[e,d+i,s] 
                            for i in range(4) 
                            for s in range(num_shifts)) <= 3
        
        # Constraint: At least one person per shift
        for d in range(num_days_per_month):
            for s in range(num_shifts):
                prob += lpSum(shift_vars[e,d,s] 
                            for e in range(num_employees)) >= 1
        
        # Night shift and Evening shift restrictions
        night_shift = next((i for i, s in enumerate(shifts) 
                           if s['start_time'].strftime('%H:%M') == '22:00'), None)
        evening_shift = next((i for i, s in enumerate(shifts) 
                            if s['start_time'].strftime('%H:%M') == '14:00'), None)
        
        for e in range(num_employees):
            for d in range(num_days_per_month - 1):
                if night_shift is not None:
                    prob += shift_vars[e,d,night_shift] + \
                           lpSum(shift_vars[e,d+1,s] for s in range(num_shifts) 
                                if s != night_shift) <= 1
                
                if evening_shift is not None:
                    prob += shift_vars[e,d,evening_shift] + \
                           lpSum(shift_vars[e,d+1,s] for s in range(num_shifts) 
                                if s != evening_shift) <= 1
        
        # Constraint: Ensure at least 2 days off per week
        for e in range(num_employees):
            for w in range(4):  # 4 weeks
                week_start = w * 7
                prob += lpSum(shift_vars[e,d,s] 
                            for d in range(week_start, week_start + 7) 
                            for s in range(num_shifts)) <= 5
        
        # Solve the problem
        prob.solve()
        
        if LpStatus[prob.status] != 'Optimal':
            raise Exception(f'No optimal solution found for month {month + 1}')
        
        # Extract the solution
        for e in range(num_employees):
            emp_schedule = {}
            for d in range(num_days_per_month):
                for s in range(num_shifts):
                    if value(shift_vars[e,d,s]) > 0.5:
                        day_number = d + month * num_days_per_month
                        if employees[e]['id'] not in full_schedule:
                            full_schedule[employees[e]['id']] = {}
                        full_schedule[employees[e]['id']][day_number] = shifts[s]['id']
    
    return full_schedule