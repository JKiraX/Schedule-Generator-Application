#schedular.py

from ortools.sat.python import cp_model
from ortools.linear_solver import pywraplp
import datetime
import numpy as np
import logging

logger = logging.getLogger(__name__)

class AdaptiveScheduler:
    def __init__(self, db_session):
        self.db_session = db_session
        
    def create_two_month_shift_schedule(self, employees, shifts, start_date):
        num_days_per_month = 28
        num_months = 2
        num_employees = len(employees)
        num_shifts = len(shifts)

        # Fetch employee preferences
        employee_preferences = self._fetch_employee_preferences([e['id'] for e in employees])
        
        # Fetch employee availability
        employee_availability = self._fetch_employee_availability(
            [e['id'] for e in employees], 
            start_date, 
            start_date + datetime.timedelta(days=num_days_per_month * num_months - 1)
        )
        
        # Calculate work history to ensure fair distribution
        work_history = self._fetch_work_history([e['id'] for e in employees])
        
        full_schedule = {}

        for month in range(num_months):
            # ========== PHASE 1: CSP to Generate Initial Feasible Solutions ==========
            csp_model = cp_model.CpModel()

            # Variables for each employee, day, and shift
            shift_vars = {}
            for e in range(num_employees):
                for d in range(num_days_per_month):
                    for s in range(num_shifts):
                        shift_vars[(e, d, s)] = csp_model.NewBoolVar(f'shift_{e}_{d}_{s}')

            # Constraints: Each employee works at most once per day
            for e in range(num_employees):
                for d in range(num_days_per_month):
                    csp_model.Add(sum(shift_vars[(e, d, s)] for s in range(num_shifts)) <= 1)
            
            # Calculate actual workdays per month based on availability
            for e in range(num_employees):
                emp_id = employees[e]['id']
                
                # Calculate number of days employee is available
                available_days = num_days_per_month
                for d in range(num_days_per_month):
                    day_date = start_date + datetime.timedelta(days=d + month * num_days_per_month)
                    day_key = day_date.strftime("%Y-%m-%d")
                    
                    if emp_id in employee_availability and day_key in employee_availability[emp_id] and not employee_availability[emp_id][day_key]:
                        available_days -= 1
                
                # Adjust workdays based on availability (aim for ~70% of available days)
                target_workdays = min(20, int(available_days * 0.7))
                
                # Constraints: Each employee works approximately target_workdays in a month
                csp_model.Add(sum(shift_vars[(e, d, s)] for d in range(num_days_per_month) for s in range(num_shifts)) >= max(10, target_workdays - 2))
                csp_model.Add(sum(shift_vars[(e, d, s)] for d in range(num_days_per_month) for s in range(num_shifts)) <= min(22, target_workdays + 2))

            # Constraints: Employee availability 
            for e in range(num_employees):
                emp_id = employees[e]['id']
                for d in range(num_days_per_month):
                    day_date = start_date + datetime.timedelta(days=d + month * num_days_per_month)
                    day_key = day_date.strftime("%Y-%m-%d")
                    
                    if emp_id in employee_availability and day_key in employee_availability[emp_id] and not employee_availability[emp_id][day_key]:
                        # Employee is not available on this day
                        for s in range(num_shifts):
                            csp_model.Add(shift_vars[(e, d, s)] == 0)

            # Fetch consecutive day preferences
            consecutive_prefs = {}
            for e in range(num_employees):
                emp_id = employees[e]['id']
                if emp_id in employee_preferences and 'consecutive' in employee_preferences[emp_id]:
                    consecutive_prefs[e] = employee_preferences[emp_id]['consecutive']
                else:
                    consecutive_prefs[e] = {'min': 1, 'max': 3, 'preferred': 2}
            
            # Constraints: Consecutive working days based on preferences
            for e in range(num_employees):
                max_consecutive = consecutive_prefs[e]['max']
                
                for d in range(num_days_per_month - max_consecutive):
                    # No more than max_consecutive consecutive working days
                    csp_model.Add(sum(shift_vars[(e, d+i, s)] for i in range(max_consecutive + 1) for s in range(num_shifts)) <= max_consecutive)

            # Constraints: At least one person per shift
            for d in range(num_days_per_month):
                for s in range(num_shifts):
                    # Calculate minimum staff based on day of week
                    day_date = start_date + datetime.timedelta(days=d + month * num_days_per_month)
                    is_weekend = day_date.weekday() >= 5  # Saturday or Sunday
                    
                    min_staff = 1  # Default minimum staffing
                    
                    if is_weekend:
                        min_staff = max(1, min_staff - 1)  # Can reduce staff on weekends
                    
                    csp_model.Add(sum(shift_vars[(e, d, s)] for e in range(num_employees)) >= min_staff)

            # Constraints: Night shift (10pm-6am) and Evening shift (2pm-10pm) restrictions
            night_shift = next((i for i, s in enumerate(shifts) if s['start_time'].strftime('%H:%M') == '22:00'), None)
            evening_shift = next((i for i, s in enumerate(shifts) if s['start_time'].strftime('%H:%M') == '14:00'), None)

            for e in range(num_employees):
                for d in range(num_days_per_month - 1):
                    if night_shift is not None:
                        # If working night shift, next day can only be night shift or off
                        csp_model.Add(shift_vars[(e, d, night_shift)] + 
                                      sum(shift_vars[(e, d+1, s)] for s in range(num_shifts) if s != night_shift) <= 1)
                    
                    if evening_shift is not None:
                        # If working evening shift, next day can only be evening shift or off
                        csp_model.Add(shift_vars[(e, d, evening_shift)] + 
                                      sum(shift_vars[(e, d+1, s)] for s in range(num_shifts) if s != evening_shift) <= 1)

            # Constraints: Ensure at least 2 days off per week
            for e in range(num_employees):
                for w in range(4):  # 4 weeks
                    week_start = w * 7
                    week_end = min(week_start + 7, num_days_per_month)
                    csp_model.Add(sum(shift_vars[(e, d, s)] for d in range(week_start, week_end) for s in range(num_shifts)) <= 5)

            # Solve the CSP model
            csp_solver = cp_model.CpSolver()
            csp_status = csp_solver.Solve(csp_model)

            if csp_status != cp_model.OPTIMAL and csp_status != cp_model.FEASIBLE:
                # If strict constraints fail, try relaxing some constraints
                logger.warning(f"No feasible solution found by CSP for month {month + 1}. Trying with relaxed constraints.")
                return self._create_schedule_with_relaxed_constraints(employees, shifts, start_date, employee_preferences, employee_availability)

            # Extract the initial feasible solution
            initial_schedule = {}
            for e in range(num_employees):
                emp_schedule = {}
                for d in range(num_days_per_month):
                    for s in range(num_shifts):
                        if csp_solver.Value(shift_vars[(e, d, s)]):
                            emp_schedule[d + month * num_days_per_month] = shifts[s]['id']
                initial_schedule[employees[e]['id']] = emp_schedule

            # ========== PHASE 2: ILP to Optimize the Feasible Solutions ==========
            ilp_solver = pywraplp.Solver.CreateSolver('GLOP')

            # Create ILP variables based on the initial CSP solution
            ilp_vars = {}
            for e in range(num_employees):
                for d in range(num_days_per_month):
                    for s in range(num_shifts):
                        ilp_vars[(e, d, s)] = ilp_solver.BoolVar(f'shift_{e}_{d}_{s}')

            # Add all constraints from CSP
            # Each employee works at most once per day
            for e in range(num_employees):
                for d in range(num_days_per_month):
                    ilp_solver.Add(sum(ilp_vars[(e, d, s)] for s in range(num_shifts)) <= 1)
            
            # Each employee works approximately target_workdays in a month
            for e in range(num_employees):
                emp_id = employees[e]['id']
                
                # Calculate number of days employee is available
                available_days = num_days_per_month
                for d in range(num_days_per_month):
                    day_date = start_date + datetime.timedelta(days=d + month * num_days_per_month)
                    day_key = day_date.strftime("%Y-%m-%d")
                    
                    if emp_id in employee_availability and day_key in employee_availability[emp_id] and not employee_availability[emp_id][day_key]:
                        available_days -= 1
                
                # Adjust workdays based on availability
                target_workdays = min(20, int(available_days * 0.7))
                
                ilp_solver.Add(sum(ilp_vars[(e, d, s)] for d in range(num_days_per_month) for s in range(num_shifts)) >= max(10, target_workdays - 2))
                ilp_solver.Add(sum(ilp_vars[(e, d, s)] for d in range(num_days_per_month) for s in range(num_shifts)) <= min(22, target_workdays + 2))

            # Employee availability constraints
            for e in range(num_employees):
                emp_id = employees[e]['id']
                for d in range(num_days_per_month):
                    day_date = start_date + datetime.timedelta(days=d + month * num_days_per_month)
                    day_key = day_date.strftime("%Y-%m-%d")
                    
                    if emp_id in employee_availability and day_key in employee_availability[emp_id] and not employee_availability[emp_id][day_key]:
                        # Employee is not available on this day
                        for s in range(num_shifts):
                            ilp_solver.Add(ilp_vars[(e, d, s)] == 0)

            # Consecutive days constraints
            for e in range(num_employees):
                max_consecutive = consecutive_prefs[e]['max']
                
                for d in range(num_days_per_month - max_consecutive):
                    # No more than max_consecutive consecutive working days
                    ilp_solver.Add(sum(ilp_vars[(e, d+i, s)] for i in range(max_consecutive + 1) for s in range(num_shifts)) <= max_consecutive)

            # At least one person per shift
            for d in range(num_days_per_month):
                for s in range(num_shifts):
                    # Calculate minimum staff based on day of week
                    day_date = start_date + datetime.timedelta(days=d + month * num_days_per_month)
                    is_weekend = day_date.weekday() >= 5  # Saturday or Sunday
                    
                    min_staff = 1  # Default minimum staffing
                    
                    if is_weekend:
                        min_staff = max(1, min_staff - 1)  # Can reduce staff on weekends
                    
                    ilp_solver.Add(sum(ilp_vars[(e, d, s)] for e in range(num_employees)) >= min_staff)

            # Night shift and Evening shift restrictions
            for e in range(num_employees):
                for d in range(num_days_per_month - 1):
                    if night_shift is not None:
                        ilp_solver.Add(ilp_vars[(e, d, night_shift)] + 
                                      sum(ilp_vars[(e, d+1, s)] for s in range(num_shifts) if s != night_shift) <= 1)
                    if evening_shift is not None:
                        ilp_solver.Add(ilp_vars[(e, d, evening_shift)] + 
                                      sum(ilp_vars[(e, d+1, s)] for s in range(num_shifts) if s != evening_shift) <= 1)

            # Ensure at least 2 days off per week
            for e in range(num_employees):
                for w in range(4):  # 4 weeks
                    week_start = w * 7
                    week_end = min(week_start + 7, num_days_per_month)
                    ilp_solver.Add(sum(ilp_vars[(e, d, s)] for d in range(week_start, week_end) for s in range(num_shifts)) <= 5)

            # ========== OBJECTIVE FUNCTION: Maximize preferences while maintaining fairness ==========
            objective = ilp_solver.Objective()
            
            # Part 1: Add preference terms to objective
            for e in range(num_employees):
                emp_id = employees[e]['id']
                
                for d in range(num_days_per_month):
                    day_date = start_date + datetime.timedelta(days=d + month * num_days_per_month)
                    day_of_week = day_date.weekday() + 1  # 1=Monday, 7=Sunday
                    
                    for s in range(num_shifts):
                        shift_id = shifts[s]['id']
                        weight = 1.0  # Default weight
                        
                        # Check for shift-day preference
                        if emp_id in employee_preferences and 'shift_day' in employee_preferences[emp_id]:
                            pref_key = (shift_id, day_of_week)
                            if pref_key in employee_preferences[emp_id]['shift_day']:
                                weight = employee_preferences[emp_id]['shift_day'][pref_key]
                        
                        # Apply the preference weight
                        objective.SetCoefficient(ilp_vars[(e, d, s)], weight)
            
            # Part 2: Add fairness terms to objective (penalize deviations from fair distribution)
            if work_history:
                for e in range(num_employees):
                    emp_id = employees[e]['id']
                    
                    # Get historical workload
                    historical_shifts = work_history.get(emp_id, 0)
                    target_shifts = 20  # Target shifts per month
                    
                    # Calculate fairness penalty based on history
                    fairness_factor = 1.0
                    if historical_shifts > target_shifts * 1.1:  # Overworked
                        fairness_factor = 0.8  # Reduce likelihood of assignment
                    elif historical_shifts < target_shifts * 0.9:  # Underworked
                        fairness_factor = 1.2  # Increase likelihood of assignment
                    
                    # Apply fairness factor to all shift variables for this employee
                    for d in range(num_days_per_month):
                        for s in range(num_shifts):
                            current_coeff = objective.GetCoefficient(ilp_vars[(e, d, s)])
                            objective.SetCoefficient(ilp_vars[(e, d, s)], current_coeff * fairness_factor)
            
            # Set objective to maximization
            objective.SetMaximization()

            # Solve the ILP
            ilp_status = ilp_solver.Solve()

            if ilp_status == pywraplp.Solver.OPTIMAL or ilp_status == pywraplp.Solver.FEASIBLE:
                for e in range(num_employees):
                    emp_schedule = {}
                    for d in range(num_days_per_month):
                        for s in range(num_shifts):
                            if ilp_vars[(e, d, s)].solution_value() > 0.5:
                                day_number = d + month * num_days_per_month
                                if employees[e]['id'] not in full_schedule:
                                    full_schedule[employees[e]['id']] = {}
                                full_schedule[employees[e]['id']][day_number] = shifts[s]['id']
            else:
                # If ILP fails, just use the initial schedule from CSP
                logger.warning(f"ILP optimization failed for month {month + 1}. Using CSP solution.")
                for emp_id, schedule in initial_schedule.items():
                    if emp_id not in full_schedule:
                        full_schedule[emp_id] = {}
                    full_schedule[emp_id].update(schedule)

        return full_schedule

    def _create_schedule_with_relaxed_constraints(self, employees, shifts, start_date, employee_preferences, employee_availability):
        """Create a schedule with relaxed constraints when strict constraints can't be satisfied"""
        logger.info("Creating schedule with relaxed constraints")
        
        num_days_per_month = 28
        num_months = 2
        num_employees = len(employees)
        num_shifts = len(shifts)
        
        full_schedule = {}
        
        for month in range(num_months):
            csp_model = cp_model.CpModel()
            
            # Variables for each employee, day, and shift
            shift_vars = {}
            for e in range(num_employees):
                for d in range(num_days_per_month):
                    for s in range(num_shifts):
                        shift_vars[(e, d, s)] = csp_model.NewBoolVar(f'shift_{e}_{d}_{s}')
            
            # Relax constraints - only keep the most essential ones
            
            # Each employee works at most once per day (essential)
            for e in range(num_employees):
                for d in range(num_days_per_month):
                    csp_model.Add(sum(shift_vars[(e, d, s)] for s in range(num_shifts)) <= 1)
            
            # At least one person per shift (essential)
            for d in range(num_days_per_month):
                for s in range(num_shifts):
                    csp_model.Add(sum(shift_vars[(e, d, s)] for e in range(num_employees)) >= 1)
            
            # Employee availability (essential)
            for e in range(num_employees):
                emp_id = employees[e]['id']
                for d in range(num_days_per_month):
                    day_date = start_date + datetime.timedelta(days=d + month * num_days_per_month)
                    day_key = day_date.strftime("%Y-%m-%d")
                    
                    if emp_id in employee_availability and day_key in employee_availability[emp_id] and not employee_availability[emp_id][day_key]:
                        # Employee is not available on this day
                        for s in range(num_shifts):
                            csp_model.Add(shift_vars[(e, d, s)] == 0)
            
            # Solve the relaxed CSP model
            csp_solver = cp_model.CpSolver()
            csp_status = csp_solver.Solve(csp_model)
            
            if csp_status != cp_model.OPTIMAL and csp_status != cp_model.FEASIBLE:
                # If even relaxed constraints fail, create a basic schedule (round-robin)
                logger.warning("Even relaxed constraints cannot be satisfied. Creating basic round-robin schedule.")
                return self._create_round_robin_schedule(employees, shifts, start_date, employee_availability)
            
            # Extract the solution
            for e in range(num_employees):
                emp_schedule = {}
                for d in range(num_days_per_month):
                    for s in range(num_shifts):
                        if csp_solver.Value(shift_vars[(e, d, s)]):
                            day_number = d + month * num_days_per_month
                            if employees[e]['id'] not in full_schedule:
                                full_schedule[employees[e]['id']] = {}
                            full_schedule[employees[e]['id']][day_number] = shifts[s]['id']
        
        return full_schedule
    
    def _create_round_robin_schedule(self, employees, shifts, start_date, employee_availability):
        """Create a basic round-robin schedule as a last resort"""
        logger.info("Creating round-robin schedule")
        
        num_days_per_month = 28
        num_months = 2
        num_employees = len(employees)
        num_shifts = len(shifts)
        
        full_schedule = {emp['id']: {} for emp in employees}
        
        for month in range(num_months):
            for d in range(num_days_per_month):
                for s in range(num_shifts):
                    # Try to find an available employee for this shift
                    assigned = False
                    
                    # Start with a different employee each day to distribute shifts more evenly
                    start_index = (d + s) % num_employees
                    
                    for e_offset in range(num_employees):
                        e = (start_index + e_offset) % num_employees
                        emp_id = employees[e]['id']
                        
                        day_number = d + month * num_days_per_month
                        day_date = start_date + datetime.timedelta(days=day_number)
                        day_key = day_date.strftime("%Y-%m-%d")
                        
                        # Check if employee is available and not already assigned that day
                        is_available = True
                        if emp_id in employee_availability and day_key in employee_availability[emp_id]:
                            is_available = employee_availability[emp_id][day_key]
                        
                        already_assigned = day_number in full_schedule[emp_id]
                        
                        if is_available and not already_assigned:
                            full_schedule[emp_id][day_number] = shifts[s]['id']
                            assigned = True
                            break
                    
                    if not assigned:
                        # If no employee is available, find anyone who isn't assigned that day
                        for e in range(num_employees):
                            emp_id = employees[e]['id']
                            day_number = d + month * num_days_per_month
                            
                            if day_number not in full_schedule[emp_id]:
                                full_schedule[emp_id][day_number] = shifts[s]['id']
                                break
        
        return full_schedule
    
    def _fetch_employee_preferences(self, employee_ids):
        """Fetch employee preferences from database"""
        preferences = {}
        
        try:
            # Query for shift-day preferences
            shift_day_prefs = self.db_session.query(
                EmployeePreference.user_id, 
                EmployeePreference.shift_id, 
                EmployeePreference.day_of_week, 
                EmployeePreference.weight
            ).filter(EmployeePreference.user_id.in_(employee_ids)).all()
            
            # Query for consecutive day preferences
            consecutive_prefs = self.db_session.query(
                EmployeeConsecutiveDayPreference.user_id,
                EmployeeConsecutiveDayPreference.min_consecutive_days,
                EmployeeConsecutiveDayPreference.max_consecutive_days,
                EmployeeConsecutiveDayPreference.preferred_consecutive_days
            ).filter(EmployeeConsecutiveDayPreference.user_id.in_(employee_ids)).all()
            
            # Process shift-day preferences
            for pref in shift_day_prefs:
                user_id, shift_id, day_of_week, weight = pref
                
                if user_id not in preferences:
                    preferences[user_id] = {'shift_day': {}}
                elif 'shift_day' not in preferences[user_id]:
                    preferences[user_id]['shift_day'] = {}
                
                preferences[user_id]['shift_day'][(shift_id, day_of_week)] = weight
            
            # Process consecutive day preferences
            for pref in consecutive_prefs:
                user_id, min_days, max_days, preferred_days = pref
                
                if user_id not in preferences:
                    preferences[user_id] = {}
                
                preferences[user_id]['consecutive'] = {
                    'min': min_days,
                    'max': max_days,
                    'preferred': preferred_days
                }
                
        except Exception as e:
            logger.error(f"Error fetching employee preferences: {str(e)}")
        
        return preferences
    
    def _fetch_employee_availability(self, employee_ids, start_date, end_date):
        """Fetch employee availability from database"""
        availability = {}
        
        try:
            # Query for availability records
            avail_records = self.db_session.query(
                EmployeeAvailability.user_id,
                EmployeeAvailability.date,
                EmployeeAvailability.is_available
            ).filter(
                EmployeeAvailability.user_id.in_(employee_ids),
                EmployeeAvailability.date >= start_date,
                EmployeeAvailability.date <= end_date
            ).all()
            
            # Process availability records
            for record in avail_records:
                user_id, date, is_available = record
                
                if user_id not in availability:
                    availability[user_id] = {}
                
                date_key = date.strftime("%Y-%m-%d")
                availability[user_id][date_key] = is_available
                
        except Exception as e:
            logger.error(f"Error fetching employee availability: {str(e)}")
        
        return availability
    
    def _fetch_work_history(self, employee_ids, lookback_months=3):
        """Fetch work history to ensure fair distribution of shifts"""
        work_history = {}
        
        try:
            # Calculate lookback date
            today = datetime.date.today()
            lookback_date = today - datetime.timedelta(days=30 * lookback_months)
            
            # Query for historical schedules
            historical_shifts = self.db_session.query(
                Schedule.user_id,
                db.func.count(Schedule.schedule_id).label('shift_count')
            ).filter(
                Schedule.user_id.in_(employee_ids),
                Schedule.work_date >= lookback_date,
                Schedule.work_date < today
            ).group_by(Schedule.user_id).all()
            
            # Process historical data
            for record in historical_shifts:
                user_id, shift_count = record
                work_history[user_id] = shift_count
                
        except Exception as e:
            logger.error(f"Error fetching work history: {str(e)}")
        
        return work_history

# Import necessary models at the module level
from models import EmployeePreference, EmployeeConsecutiveDayPreference, ShiftTransition, EmployeeAvailability, Schedule

# Function to be called by app.py
def create_two_month_shift_schedule(employees, shifts, start_date, db_session=None):
    """
    Main entry point - creates a schedule for the next two months
    
    Args:
        employees: List of employee dictionaries with 'id' and 'name'
        shifts: List of shift dictionaries with 'id', 'start_time', and 'end_time'
        start_date: The start date for the schedule
        db_session: SQLAlchemy database session
        
    Returns:
        Dictionary mapping employee IDs to their schedules
    """
    scheduler = AdaptiveScheduler(db_session)
    return scheduler.create_two_month_shift_schedule(employees, shifts, start_date)