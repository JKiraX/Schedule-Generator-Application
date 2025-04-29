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
        # Define constants at the start of the function for clear scope
        BASE_SHIFT_WEIGHT = 10.0  # All-caps to indicate it's a constant
        
        num_days_per_month = 28
        num_months = 2
        num_employees = len(employees)
        num_shifts = len(shifts)

        # Validate employee count before scheduling
        # Minimum requirement: At least as many employees as shifts
        min_required = num_shifts
        
        # Only add a small buffer for night/morning transitions if needed
        has_night_shift = any(shift['start_time'].hour == 22 for shift in shifts)
        has_morning_shift = any(shift['start_time'].hour in [6, 7, 8] for shift in shifts)
        
        if has_night_shift and has_morning_shift and min_required < 5:
            # Only add 1 extra employee if we have both night and morning shifts
            min_required += 1
        
        if num_employees < min_required:
            logger.error(f"Not enough employees ({num_employees}) to cover all shifts. " +
                        f"Minimum required: {min_required}")
            raise ValueError(f"Not enough employees to cover all shifts. Min required: {min_required}")

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
            # Initialize the initial_schedule variable before we might need to use it
            initial_schedule = {}
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
            
            # Constraints: Consecutive working days - enforce maximum 3 consecutive days
            for e in range(num_employees):
                max_consecutive = 3  # Force maximum 3 consecutive days
                
                for d in range(num_days_per_month - max_consecutive):
                    # No more than max_consecutive consecutive working days
                    csp_model.Add(sum(shift_vars[(e, d+i, s)] for i in range(max_consecutive + 1) for s in range(num_shifts)) <= max_consecutive)

            # Constraints: Each shift must have at least one employee every day (regardless of weekends)
            # This is the most critical constraint - every shift MUST be covered every day
            for d in range(num_days_per_month):
                for s in range(num_shifts):
                    # Each shift must have at least one employee - make this a HARD constraint
                    shift_coverage = sum(shift_vars[(e, d, s)] for e in range(num_employees))
                    # Make this constraint higher priority by assigning it a higher weight in the solver
                    csp_model.Add(shift_coverage >= 1)
                    
                    # Log for debugging
                    if d < 3:  # Only log first few days to avoid excessive logging
                        logger.info(f"Added constraint: Day {d}, Shift {s} ({shifts[s]['id']}): At least one employee")

            # Identify shifts by hour rather than string comparison
            night_shift = next((i for i, s in enumerate(shifts) if s['start_time'].hour == 22), None)
            morning_shifts = [i for i, s in enumerate(shifts) if s['start_time'].hour in {6, 8}]
            
            # Constraints: Night shift (10pm) and morning shift restrictions
            if night_shift is not None and morning_shifts:
                for e in range(num_employees):
                    for d in range(num_days_per_month - 1):
                        # If worked night shift, can't work morning shifts next day
                        csp_model.Add(
                            shift_vars[(e, d, night_shift)] + 
                            sum(shift_vars[(e, d + 1, s)] for s in morning_shifts) <= 1
                        )

            # Implement employee rest periods (at least 10 hours between shifts)
            for e in range(num_employees):
                for d in range(num_days_per_month - 1):
                    for prev_s in range(num_shifts):
                        prev_end = shifts[prev_s]['end_time']
                        prev_end_dt = datetime.datetime.combine(datetime.date.today(), prev_end)
                        if prev_end_dt.hour >= 22:  # Handle overnight shifts
                            prev_end_dt += datetime.timedelta(days=1)
                        
                        for next_s in range(num_shifts):
                            next_start = shifts[next_s]['start_time']
                            next_start_dt = datetime.datetime.combine(datetime.date.today() + datetime.timedelta(days=1), next_start)
                            
                            time_diff = (next_start_dt - prev_end_dt).total_seconds() / 3600
                            if time_diff < 10:  # Less than 10 hours between shifts
                                csp_model.Add(
                                    shift_vars[(e, d, prev_s)] + shift_vars[(e, d + 1, next_s)] <= 1
                                )

            # Constraints: Instead of requiring exactly 5 work days, allow 4-6 work days per week
            # This gives more flexibility to ensure all shifts can be covered
            for e in range(num_employees):
                for w in range(4):  # 4 weeks
                    week_start = w * 7
                    week_end = min(week_start + 7, num_days_per_month)
                    # Allow 4-6 days of work per week instead of exactly 5
                    # This makes the problem more feasible while still ensuring reasonable rest
                    csp_model.Add(sum(shift_vars[(e, d, s)] for d in range(week_start, week_end) for s in range(num_shifts)) >= 4)
                    csp_model.Add(sum(shift_vars[(e, d, s)] for d in range(week_start, week_end) for s in range(num_shifts)) <= 6)

            # Solve the CSP model with extended time limit to find solution
            csp_solver = cp_model.CpSolver()
            csp_solver.parameters.max_time_in_seconds = 300.0  # Extend time limit to 5 minutes
            csp_solver.parameters.num_search_workers = 8  # Use more workers for parallel search
            csp_solver.parameters.search_branching = cp_model.PORTFOLIO_SEARCH  # Use portfolio search
            csp_solver.parameters.cp_model_presolve = True  # Enable presolve
            
            # Log start of solving
            logger.info(f"Solving CSP model for month {month + 1}...")
            csp_status = csp_solver.Solve(csp_model)
            
            # Log the solving stats
            logger.info(f"CSP solving stats: {csp_solver.ResponseStats()}")

            if csp_status != cp_model.OPTIMAL and csp_status != cp_model.FEASIBLE:
                # Remove fallback round-robin and relaxed constraints
                logger.error(f"No feasible solution found for month {month + 1}.")
                raise ValueError("No feasible schedule could be generated. Try adding more employees or relaxing some constraints.")

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

            # Consecutive days constraints - enforce maximum 3 consecutive days
            for e in range(num_employees):
                max_consecutive = 3  # Force maximum 3 consecutive days
                
                for d in range(num_days_per_month - max_consecutive):
                    # No more than max_consecutive consecutive working days
                    ilp_solver.Add(sum(ilp_vars[(e, d+i, s)] for i in range(max_consecutive + 1) for s in range(num_shifts)) <= max_consecutive)

            # Each shift must have at least one employee every day
            # This is the most critical constraint in the ILP model
            for d in range(num_days_per_month):
                for s in range(num_shifts):
                    # Add this as a hard constraint
                    shift_coverage = sum(ilp_vars[(e, d, s)] for e in range(num_employees))
                    ilp_solver.Add(shift_coverage >= 1)

            # Night shift and morning shift restrictions
            if night_shift is not None and morning_shifts:
                for e in range(num_employees):
                    for d in range(num_days_per_month - 1):
                        # If worked night shift, can't work morning shifts next day
                        ilp_solver.Add(
                            ilp_vars[(e, d, night_shift)] + 
                            sum(ilp_vars[(e, d + 1, s)] for s in morning_shifts) <= 1
                        )

            # Rest period constraints
            for e in range(num_employees):
                for d in range(num_days_per_month - 1):
                    for prev_s in range(num_shifts):
                        prev_end = shifts[prev_s]['end_time']
                        prev_end_dt = datetime.datetime.combine(datetime.date.today(), prev_end)
                        if prev_end_dt.hour >= 22:  # Handle overnight shifts
                            prev_end_dt += datetime.timedelta(days=1)
                        
                        for next_s in range(num_shifts):
                            next_start = shifts[next_s]['start_time']
                            next_start_dt = datetime.datetime.combine(datetime.date.today() + datetime.timedelta(days=1), next_start)
                            
                            time_diff = (next_start_dt - prev_end_dt).total_seconds() / 3600
                            if time_diff < 10:  # Less than 10 hours between shifts
                                ilp_solver.Add(
                                    ilp_vars[(e, d, prev_s)] + ilp_vars[(e, d + 1, next_s)] <= 1
                                )

            # Use same work days constraint as CSP: Allow 4-6 work days per week
            for e in range(num_employees):
                for w in range(4):  # 4 weeks
                    week_start = w * 7
                    week_end = min(week_start + 7, num_days_per_month)
                    # Allow 4-6 days of work per week
                    ilp_solver.Add(sum(ilp_vars[(e, d, s)] for d in range(week_start, week_end) for s in range(num_shifts)) >= 4)
                    ilp_solver.Add(sum(ilp_vars[(e, d, s)] for d in range(week_start, week_end) for s in range(num_shifts)) <= 6)

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
                        
                        # Apply the preference weight plus the base shift weight
                        objective.SetCoefficient(ilp_vars[(e, d, s)], BASE_SHIFT_WEIGHT + weight)
            
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
                            # Use the constant BASE_SHIFT_WEIGHT defined at the beginning of the function
                            current_coeff = objective.GetCoefficient(ilp_vars[(e, d, s)])
                            # Adjust the coefficient by the fairness factor but preserve the base weight
                            adjusted_weight = BASE_SHIFT_WEIGHT + ((current_coeff - BASE_SHIFT_WEIGHT) * fairness_factor)
                            objective.SetCoefficient(ilp_vars[(e, d, s)], adjusted_weight)
            
            # Add base weights for shift coverage in the objective function
            # This ensures the solver prioritizes assigning shifts over leaving them unassigned
            base_shift_weight = 10.0  # Base weight for any shift assignment
            
            # Set objective to maximization
            objective.SetMaximization()

            # Solve the ILP
            ilp_status = ilp_solver.Solve()

            if ilp_status == pywraplp.Solver.OPTIMAL or ilp_status == pywraplp.Solver.FEASIBLE:
                # First verify that all shifts are covered in the ILP solution
                coverage_issues = []
                for d in range(num_days_per_month):
                    for s in range(num_shifts):
                        employees_on_shift = sum(1 for e in range(num_employees) if ilp_vars[(e, d, s)].solution_value() > 0.5)
                        if employees_on_shift == 0:
                            day_date = start_date + datetime.timedelta(days=d + month * num_days_per_month)
                            coverage_issues.append(f"No employee assigned to shift {shifts[s]['id']} on {day_date.strftime('%Y-%m-%d')}")
                
                if coverage_issues:
                    # If ILP solution has coverage issues, use the CSP solution instead
                    logger.error(f"Coverage issues found in ILP solution: {len(coverage_issues)} issues")
                    logger.info("Falling back to CSP solution which has verified coverage")
                    
                    # Use the initial_schedule from CSP to ensure all shifts are covered
                    for emp_id, schedule in initial_schedule.items():
                        if emp_id not in full_schedule:
                            full_schedule[emp_id] = {}
                        full_schedule[emp_id].update(schedule)
                else:
                    # Extract the ILP solution if it has full coverage
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
        
            # Use the db session that was passed to the constructor
            if self.db_session:
                # Import necessary SQLAlchemy functions
                from sqlalchemy import func
            
                # Use the session object directly
                historical_shifts = self.db_session.query(
                    Schedule.user_id,
                    func.count(Schedule.schedule_id).label('shift_count')
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
    # Calculate minimum required employees based on constraints
    # Each day requires all shifts to be covered
    min_shifts_per_day = len(shifts)
    
    # Since the system previously worked with 7 employees, we'll use a more
    # practical approach to minimum requirements
    min_required = min_shifts_per_day  # At minimum, we need as many employees as there are shifts
    
    # Only add a small buffer for night-morning transition if needed
    has_night_shift = any(shift['start_time'].hour == 22 for shift in shifts)
    has_morning_shift = any(shift['start_time'].hour in [6, 7, 8] for shift in shifts)
    
    if has_night_shift and has_morning_shift and min_required < 5:
        # Only add 1 extra employee for night-morning transitions if we have few employees
        min_required += 1
        logger.info("Added 1 buffer employee for night-morning transitions")
    
    logger.info(f"Calculated minimum required employees: {min_required} for {min_shifts_per_day} shifts per day")
    
    if len(employees) < min_required:
        error_msg = (f"Not enough employees ({len(employees)}) to cover all shifts. " +
                    f"Minimum required: {min_required}")
        logger.error(error_msg)
        raise ValueError(error_msg)
    
    # All checks passed, create the schedule
    scheduler = AdaptiveScheduler(db_session)
    return scheduler.create_two_month_shift_schedule(employees, shifts, start_date)