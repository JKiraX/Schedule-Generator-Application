from ortools.sat.python import cp_model
from datetime import datetime, timedelta
from models import User, Shift, Schedule
from app import db

def create_schedule(start_date, days=7):
    model = cp_model.CpModel()
    
    # Get all users and shifts
    users = User.query.all()
    shifts = Shift.query.all()
    
    # Create variables
    shift_vars = {}
    for user in users:
        for day in range(days):
            for shift in shifts:
                shift_vars[(user.userID, day, shift.shiftID)] = model.NewBoolVar(f'shift_{user.userID}_{day}_{shift.shiftID}')
    
    # Constraints
    for day in range(days):
        # Each shift must be assigned to exactly one user per day
        for shift in shifts:
            model.Add(sum(shift_vars[(user.userID, day, shift.shiftID)] for user in users) == 1)
        
        # Each user can be assigned to at most one shift per day
        for user in users:
            model.Add(sum(shift_vars[(user.userID, day, shift.shiftID)] for shift in shifts) <= 1)
    
    # Each user should work 5 days in a week
    for user in users:
        model.Add(sum(shift_vars[(user.userID, day, shift.shiftID)] 
                      for day in range(days) 
                      for shift in shifts) == 5)
    
    # No more than 3 consecutive working days
    for user in users:
        for day in range(days - 3):
            model.Add(sum(shift_vars[(user.userID, d, shift.shiftID)] 
                          for d in range(day, day + 4) 
                          for shift in shifts) <= 3)
    
    # Solver
    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        return create_schedule_from_solution(solver, shift_vars, users, shifts, start_date, days)
    else:
        return None

def create_schedule_from_solution(solver, shift_vars, users, shifts, start_date, days):
    schedules = []
    for user in users:
        for day in range(days):
            for shift in shifts:
                if solver.Value(shift_vars[(user.userID, day, shift.shiftID)]):
                    shift_date = start_date + timedelta(days=day)
                    schedule = Schedule(
                        shiftDate=shift_date,
                        userID=user.userID,
                        shiftID=shift.shiftID,
                        scheduleHours=shift.duration.total_seconds() / 3600  # Convert to hours
                    )
                    schedules.append(schedule)
    return schedules

def assign_shifts(start_date):
    schedules = create_schedule(start_date)
    if schedules:
        for schedule in schedules:
            db.session.add(schedule)
        db.session.commit()
        return True
    return False