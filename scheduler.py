from ortools.sat.python import cp_model
from ortools.linear_solver import pywraplp
import datetime

def create_monthly_shift_schedule(employees, shifts, start_date):
    num_days = 28
    num_employees = len(employees)
    num_shifts = len(shifts)

    # Step 1: CSP to Generate Initial Feasible Solutions
    csp_model = cp_model.CpModel()

    # Create variables for each employee, day, and shift
    shift_vars = {}
    for e in range(num_employees):
        for d in range(num_days):
            for s in range(num_shifts):
                shift_vars[(e, d, s)] = csp_model.NewBoolVar(f'shift_{e}_{d}_{s}')

    # Constraints: Each employee works exactly 20 days in a month (5 days per week * 4 weeks)
    for e in range(num_employees):
        csp_model.Add(sum(shift_vars[(e, d, s)] for d in range(num_days) for s in range(num_shifts)) == 20)

    # Constraints: No more than 3 consecutive working days
    for e in range(num_employees):
        for d in range(num_days - 3):
            csp_model.Add(sum(shift_vars[(e, d+i, s)] for i in range(4) for s in range(num_shifts)) <= 3)

    # Constraints: At least one person per shift
    for d in range(num_days):
        for s in range(num_shifts):
            csp_model.Add(sum(shift_vars[(e, d, s)] for e in range(num_employees)) >= 1)

    # Constraints: Night shift (10pm-6am) and Evening shift (2pm-10pm) restrictions
    night_shift = next((i for i, s in enumerate(shifts) if s['start_time'].strftime('%H:%M') == '22:00'), None)
    evening_shift = next((i for i, s in enumerate(shifts) if s['start_time'].strftime('%H:%M') == '14:00'), None)

    for e in range(num_employees):
        for d in range(num_days - 1):
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
            csp_model.Add(sum(shift_vars[(e, d, s)] for d in range(week_start, week_start + 7) for s in range(num_shifts)) <= 5)

    # Solve the CSP model
    csp_solver = cp_model.CpSolver()
    csp_status = csp_solver.Solve(csp_model)

    if csp_status != cp_model.OPTIMAL:
        raise Exception('No feasible solution found by CSP')

    # Extract the initial feasible solution
    initial_schedule = {}
    for e in range(num_employees):
        emp_schedule = {}
        for d in range(num_days):
            for s in range(num_shifts):
                if csp_solver.Value(shift_vars[(e, d, s)]):
                    emp_schedule[d] = shifts[s]['id']
        initial_schedule[employees[e]['id']] = emp_schedule

    # Step 2: ILP to Optimize the Feasible Solutions
    ilp_solver = pywraplp.Solver.CreateSolver('GLOP')

    # Create ILP variables based on the initial CSP solution
    ilp_vars = {}
    for e in range(num_employees):
        for d in range(num_days):
            for s in range(num_shifts):
                ilp_vars[(e, d, s)] = ilp_solver.BoolVar(f'shift_{e}_{d}_{s}')

    # ILP Constraints: Each employee works exactly 20 days in a month
    for e in range(num_employees):
        ilp_solver.Add(sum(ilp_vars[(e, d, s)] for d in range(num_days) for s in range(num_shifts)) == 20)

    # ILP Constraints: No more than 3 consecutive working days
    for e in range(num_employees):
        for d in range(num_days - 3):
            ilp_solver.Add(sum(ilp_vars[(e, d+i, s)] for i in range(4) for s in range(num_shifts)) <= 3)

    # ILP Constraints: At least one person per shift
    for d in range(num_days):
        for s in range(num_shifts):
            ilp_solver.Add(sum(ilp_vars[(e, d, s)] for e in range(num_employees)) >= 1)

    # ILP Constraints: Night shift and Evening shift restrictions
    for e in range(num_employees):
        for d in range(num_days - 1):
            if night_shift is not None:
                ilp_solver.Add(ilp_vars[(e, d, night_shift)] + 
                               sum(ilp_vars[(e, d+1, s)] for s in range(num_shifts) if s != night_shift) <= 1)
            if evening_shift is not None:
                ilp_solver.Add(ilp_vars[(e, d, evening_shift)] + 
                               sum(ilp_vars[(e, d+1, s)] for s in range(num_shifts) if s != evening_shift) <= 1)

    # ILP Constraints: Ensure at least 2 days off per week
    for e in range(num_employees):
        for w in range(4):  # 4 weeks
            week_start = w * 7
            ilp_solver.Add(sum(ilp_vars[(e, d, s)] for d in range(week_start, week_start + 7) for s in range(num_shifts)) <= 5)

    # Objective: Minimize deviations from the initial schedule (fairness optimization)
    objective = ilp_solver.Objective()
    for e in range(num_employees):
        for d in range(num_days):
            for s in range(num_shifts):
                if (employees[e]['id'] in initial_schedule and
                        d in initial_schedule[employees[e]['id']] and
                        shifts[s]['id'] == initial_schedule[employees[e]['id']][d]):
                    objective.SetCoefficient(ilp_vars[(e, d, s)], 1)
                else:
                    objective.SetCoefficient(ilp_vars[(e, d, s)], 0)
    objective.SetMaximization()

    ilp_status = ilp_solver.Solve()

    optimized_schedule = {}
    if ilp_status == pywraplp.Solver.OPTIMAL:
        for e in range(num_employees):
            emp_schedule = {}
            for d in range(num_days):
                for s in range(num_shifts):
                    if ilp_vars[(e, d, s)].solution_value() > 0.5:
                        emp_schedule[d] = shifts[s]['id']
            optimized_schedule[employees[e]['id']] = emp_schedule
    else:
        raise Exception('No optimal solution found by ILP')

    return optimized_schedule