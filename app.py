# app.py
from flask import Flask, request, jsonify, render_template, redirect, url_for, flash
from flask_apscheduler import APScheduler
from sqlalchemy import func, and_, or_
import logging
import datetime
import os
from dotenv import load_dotenv
import numpy as np
from threading import Thread

# Import our models and scheduler
from models import db, Employee, Shift, Schedule, IdentityUserRole, ReportLeave
from models import EmployeePreference, EmployeeConsecutiveDayPreference, ShiftTransition, ScheduleFeedback, EmployeeAvailability
from scheduler import create_two_month_shift_schedule
from ml_scheduler import ScheduleOptimizer

# Import API blueprint
from flask_api_endpoints import api

# Load environment variables from .env file
load_dotenv()

# For debugging purposes - you can remove this later
print("Environment variables:", {
    "DB_USER": os.getenv('DB_USER'),
    "DB_PASSWORD": os.getenv('DB_PASSWORD'),
    "DB_HOST": os.getenv('DB_HOST'),
    "DB_PORT": os.getenv('DB_PORT'),
    "DB_NAME": os.getenv('DB_NAME')
})

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev_secret_key_change_in_production')

# Initialize APScheduler
scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get the database connection details from environment variables
db_user = os.getenv('DB_USER')
db_password = os.getenv('DB_PASSWORD')
db_host = os.getenv('DB_HOST')
db_port = os.getenv('DB_PORT')
db_name = os.getenv('DB_NAME')

# Ensure all environment variables are loaded
assert all([db_user, db_password, db_host, db_port, db_name]), "Database environment variables missing"

# Configure the database connection
app.config['SQLALCHEMY_DATABASE_URI'] = f'postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize the database with our app
db.init_app(app)

# Register the API blueprint
app.register_blueprint(api)

# Helper functions
def get_employee_name(employee_id):
    employee = Employee.query.get(employee_id)
    if employee:
        return employee.full_name
    return f"Employee {employee_id}"

def get_shift_name(shift_id):
    shift = Shift.query.get(shift_id)
    if shift:
        return shift.shift_name
    return f"Shift {shift_id}"

# =============== ROUTES ===============

@app.route('/')
def index():
    employees = Employee.query.all()
    shifts = Shift.query.all()
    
    # Get counts for status boxes
    employee_count = Employee.query.count()
    shift_count = Shift.query.count()
    schedule_count = Schedule.query.count()
    
    # Check if schedules exist and display if they do
    today = datetime.date.today()
    start_of_month = datetime.date(today.year, today.month, 1)
    
    # Handle December to January transition
    if today.month == 12:
        end_of_next_month = datetime.date(today.year + 1, 2, 1) - datetime.timedelta(days=1)
    else:
        end_of_next_month = datetime.date(today.year, today.month + 2, 1) - datetime.timedelta(days=1)
    
    schedules_exist = Schedule.query.filter(
        Schedule.work_date >= start_of_month,
        Schedule.work_date <= end_of_next_month
    ).first() is not None
    
    if schedules_exist:
        return display_schedule(start_of_month)
    
    return render_template(
        'index.html', 
        employees=employees, 
        shifts=shifts,
        employee_count=employee_count,
        shift_count=shift_count,
        schedule_count=schedule_count
    )

@app.route('/view_schedules', methods=['GET'])
def view_schedules():
    try:
        # Get query parameters
        start_date_str = request.args.get('start_date')
        
        if not start_date_str:
            # Default to first day of current month
            today = datetime.date.today()
            start_date = datetime.date(today.year, today.month, 1)
        else:
            start_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d').date()
        
        # Return the display_schedule function with the date parameters
        return display_schedule(start_date)
        
    except Exception as e:
        logger.error(f"Error viewing schedules: {str(e)}")
        flash(f"Error viewing schedules: {str(e)}", "error")
        return redirect(url_for('index'))

@app.route('/add_employee', methods=['POST'])
def add_employee():
    try:
        first_name = request.form['first_name']
        last_name = request.form['last_name']
        
        if not (first_name and last_name):
            flash("First name and last name are required", "error")
            return redirect(url_for('index'))
        
        # Create a username from first name and last name
        username = f"{first_name.lower()}.{last_name.lower()}"
        
        new_employee = Employee(first_name=first_name, last_name=last_name, username=username)
        db.session.add(new_employee)
        db.session.commit()
        
        # Set default role (non-admin)
        user_role = IdentityUserRole(user_id=new_employee.id, role_id=2)  # Assuming 2 is user role
        db.session.add(user_role)
        db.session.commit()
        
        flash(f"Employee {first_name} {last_name} added successfully", "success")
        return redirect(url_for('index'))
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error adding employee: {str(e)}")
        flash(f"Error adding employee: {str(e)}", "error")
        return redirect(url_for('index'))

@app.route('/add_shift', methods=['POST'])
def add_shift():
    try:
        shift_name = request.form['shift_name']
        start_time = datetime.datetime.strptime(request.form['start_time'], '%H:%M').time()
        end_time = datetime.datetime.strptime(request.form['end_time'], '%H:%M').time()
        
        # Calculate duration in hours
        start_datetime = datetime.datetime.combine(datetime.date.today(), start_time)
        end_datetime = datetime.datetime.combine(datetime.date.today(), end_time)
        
        # Handle overnight shifts
        if end_datetime < start_datetime:
            end_datetime = end_datetime + datetime.timedelta(days=1)
        
        duration = (end_datetime - start_datetime).seconds // 3600
        
        if not (shift_name and start_time and end_time):
            flash("Shift name, start time, and end time are required", "error")
            return redirect(url_for('index'))
        
        new_shift = Shift(
            shift_name=shift_name,
            start_time=start_time,
            end_time=end_time,
            duration=duration
        )
        db.session.add(new_shift)
        db.session.commit()
        
        flash(f"Shift {shift_name} added successfully", "success")
        return redirect(url_for('index'))
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error adding shift: {str(e)}")
        flash(f"Error adding shift: {str(e)}", "error")
        return redirect(url_for('index'))

@app.route('/generate_schedule', methods=['POST'])
def generate_schedule():
    try:
        start_date_str = request.form['start_date']
        start_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d').date()
        
        generate_schedule_task(start_date)
        
        flash(f"Schedule generated successfully starting from {start_date.strftime('%Y-%m-%d')}", "success")
        # Get the generated schedule to display
        return display_schedule(start_date)
    except Exception as e:
        logger.error(f"Error generating schedule: {str(e)}")
        flash(f"Error generating schedule: {str(e)}", "error")
        return redirect(url_for('index'))

@app.route('/trigger_schedule_generation', methods=['POST'])
def trigger_schedule_generation():
    try:
        # Generate schedule for next month
        today = datetime.date.today()
        if today.month == 12:
            next_month = datetime.date(today.year + 1, 1, 1)
        else:
            next_month = datetime.date(today.year, today.month + 1, 1)
        
        generate_schedule_task(next_month)
        
        flash(f"Schedule generated successfully for {next_month.strftime('%B %Y')}", "success")
        # Get the generated schedule to display
        return display_schedule(next_month)
    except Exception as e:
        logger.error(f"Error generating schedule: {str(e)}")
        flash(f"Error generating schedule: {str(e)}", "error")
        return redirect(url_for('index'))

@app.route('/optimize_preferences', methods=['POST'])
def optimize_preferences():
    try:
        # Run in background to not block the UI
        thread = Thread(target=optimize_preferences_task)
        thread.daemon = True
        thread.start()
        
        flash("AI optimization started in the background", "success")
        return redirect(url_for('index'))
    except Exception as e:
        logger.error(f"Error optimizing preferences: {str(e)}")
        flash(f"Error optimizing preferences: {str(e)}", "error")
        return redirect(url_for('index'))

@app.route('/update_preference', methods=['POST'])
def update_preference():
    try:
        user_id = request.form['user_id']
        shift_id = request.form['shift_id']
        day_of_week = request.form.get('day_of_week')
        weight = float(request.form['weight'])
        
        print(f"Updating preference: user_id={user_id}, shift_id={shift_id}, day={day_of_week}, weight={weight}")
        
        if not user_id or not shift_id:
            flash("User ID and Shift ID are required", "error")
            return redirect(url_for('index'))
        
        # Check if preference exists
        pref = EmployeePreference.query.filter_by(
            user_id=user_id, 
            shift_id=shift_id,
            day_of_week=day_of_week if day_of_week else None
        ).first()
        
        if pref:
            # Update existing preference
            print(f"Updating existing preference (ID: {pref.preference_id})")
            pref.weight = weight
            db.session.commit()
            flash("Preference updated successfully", "success")
        else:
            # Create new preference
            print("Creating new preference")
            new_pref = EmployeePreference(
                user_id=user_id,
                shift_id=shift_id,
                day_of_week=day_of_week if day_of_week else None,
                weight=weight
            )
            db.session.add(new_pref)
            db.session.commit()
            flash("Preference saved successfully", "success")
        
        return redirect(url_for('index'))
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating preference: {str(e)}")
        print(f"Error updating preference: {str(e)}")
        flash(f"Error updating preference: {str(e)}", "error")
        return redirect(url_for('index'))

@app.route('/update_consecutive_preference', methods=['POST'])
def update_consecutive_preference():
    try:
        user_id = request.form['user_id']
        min_days = int(request.form['min_days'])
        max_days = int(request.form['max_days'])
        preferred_days = int(request.form['preferred_days'])
        
        print(f"Updating consecutive preference: user_id={user_id}, min={min_days}, max={max_days}, preferred={preferred_days}")
        
        if not user_id:
            flash("User ID is required", "error")
            return redirect(url_for('index'))
        
        # Check if preference exists
        pref = EmployeeConsecutiveDayPreference.query.filter_by(user_id=user_id).first()
        
        if pref:
            # Update existing preference
            print(f"Updating existing consecutive preference (ID: {pref.preference_id})")
            pref.min_consecutive_days = min_days
            pref.max_consecutive_days = max_days
            pref.preferred_consecutive_days = preferred_days
            db.session.commit()
            flash("Consecutive day preference updated successfully", "success")
        else:
            # Create new preference
            print("Creating new consecutive preference")
            new_pref = EmployeeConsecutiveDayPreference(
                user_id=user_id,
                min_consecutive_days=min_days,
                max_consecutive_days=max_days,
                preferred_consecutive_days=preferred_days
            )
            db.session.add(new_pref)
            db.session.commit()
            flash("Consecutive day preference saved successfully", "success")
        
        return redirect(url_for('index'))
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating consecutive preferences: {str(e)}")
        print(f"Error updating consecutive preferences: {str(e)}")
        flash(f"Error updating consecutive preferences: {str(e)}", "error")
        return redirect(url_for('index'))

@app.route('/update_availability', methods=['POST'])
def update_availability():
    try:
        user_id = request.form['user_id']
        date = datetime.datetime.strptime(request.form['date'], '%Y-%m-%d').date()
        is_available = request.form['is_available'] == 'true'
        reason = request.form.get('reason', '')
        
        if not user_id or not date:
            flash("User ID and date are required", "error")
            return redirect(url_for('index'))
        
        # Check if we have an existing record
        existing_avail = EmployeeAvailability.query.filter_by(
            user_id=user_id,
            date=date
        ).first()
        
        if existing_avail:
            # Update existing record
            existing_avail.is_available = is_available
            existing_avail.reason = reason
            db.session.commit()
            flash(f"Availability updated successfully for {date.strftime('%Y-%m-%d')}", "success")
        else:
            # Create new record
            new_avail = EmployeeAvailability(
                user_id=user_id,
                date=date,
                is_available=is_available,
                reason=reason
            )
            db.session.add(new_avail)
            db.session.commit()
            flash(f"Availability saved successfully for {date.strftime('%Y-%m-%d')}", "success")
        
        return redirect(url_for('index'))
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating availability: {str(e)}")
        flash(f"Error updating availability: {str(e)}", "error")
        return redirect(url_for('index'))

@app.route('/submit_feedback', methods=['POST'])
def submit_feedback():
    try:
        # Get form data
        schedule_id = request.form.get('schedule_id')
        satisfaction_score = request.form.get('satisfaction_score')
        
        # Debug info
        print(f"Feedback submission received: schedule_id={schedule_id}, score={satisfaction_score}")
        print(f"Form data: {request.form}")
        
        # Validation
        if not schedule_id:
            flash("Schedule ID is missing", "error")
            return redirect(url_for('index'))
            
        try:
            schedule_id = int(schedule_id)
            satisfaction_score = int(satisfaction_score)
        except (ValueError, TypeError):
            flash(f"Invalid data: schedule_id={schedule_id}, score={satisfaction_score}", "error")
            return redirect(url_for('index'))
        
        # Verify the schedule exists
        schedule = Schedule.query.get(schedule_id)
        if not schedule:
            flash(f"Schedule with ID {schedule_id} does not exist", "error")
            return redirect(url_for('index'))
            
        print(f"Found schedule: user_id={schedule.user_id}, date={schedule.work_date}, shift_id={schedule.shift_id}")
        
        if not (1 <= satisfaction_score <= 5):
            flash(f"Satisfaction score must be between 1 and 5, got {satisfaction_score}", "error")
            return redirect(url_for('index'))
        
        # Check if feedback already exists
        existing_feedback = ScheduleFeedback.query.filter_by(schedule_id=schedule_id).first()
        
        if existing_feedback:
            # Update existing feedback
            print(f"Updating existing feedback (ID: {existing_feedback.feedback_id})")
            existing_feedback.satisfaction_score = satisfaction_score
            db.session.commit()
            
            print("Feedback updated successfully")
            flash("Feedback updated successfully", "success")
        else:
            # Create new feedback
            print(f"Creating new feedback entry")
            new_feedback = ScheduleFeedback(
                schedule_id=schedule_id,
                satisfaction_score=satisfaction_score,
                created_at=datetime.datetime.now()
            )
            db.session.add(new_feedback)
            db.session.commit()
            
            print("Feedback saved successfully")
            flash("Feedback saved successfully", "success")
        
        # Check if the optimization should be triggered
        feedback_count = ScheduleFeedback.query.filter(
            ScheduleFeedback.created_at >= datetime.datetime.now() - datetime.timedelta(days=1)
        ).count()
        
        print(f"Recent feedback count: {feedback_count}")
        if feedback_count >= 5:
            print("Triggering optimization due to sufficient feedback")
            # Run in background to not delay the response
            thread = Thread(target=optimize_preferences_task)
            thread.daemon = True
            thread.start()
        
        # Redirect back to the page with the schedule
        return redirect(request.referrer or url_for('index'))
        
    except Exception as e:
        db.session.rollback()
        error_msg = f"Error submitting feedback: {str(e)}"
        print(f"Exception: {error_msg}")
        logger.error(error_msg)
        flash(error_msg, "error")
        return redirect(url_for('index'))

# =============== DEBUGGING ROUTES ===============

@app.route('/debug/feedback', methods=['GET'])
def debug_feedback():
    """Debug endpoint to view and test feedback functionality"""
    try:
        # Get all feedback entries
        all_feedback = db.session.query(
            ScheduleFeedback, Schedule, Employee, Shift
        ).join(
            Schedule, ScheduleFeedback.schedule_id == Schedule.schedule_id
        ).join(
            Employee, Schedule.user_id == Employee.id
        ).join(
            Shift, Schedule.shift_id == Shift.shift_id
        ).all()
        
        # Format for display
        feedback_data = [{
            'feedback_id': f.ScheduleFeedback.feedback_id,
            'schedule_id': f.ScheduleFeedback.schedule_id,
            'employee': f.Employee.full_name,
            'shift': f.Shift.shift_name,
            'date': f.Schedule.work_date.strftime('%Y-%m-%d'),
            'score': f.ScheduleFeedback.satisfaction_score,
            'created_at': f.ScheduleFeedback.created_at.strftime('%Y-%m-%d %H:%M:%S')
        } for f in all_feedback]
        
        # Get a sample of schedules that can be used for testing
        sample_schedules = db.session.query(
            Schedule, Employee, Shift
        ).join(
            Employee, Schedule.user_id == Employee.id
        ).join(
            Shift, Schedule.shift_id == Shift.shift_id
        ).order_by(Schedule.work_date.desc()).limit(10).all()
        
        test_schedules = [{
            'schedule_id': s.Schedule.schedule_id,
            'employee': s.Employee.full_name,
            'shift': s.Shift.shift_name,
            'date': s.Schedule.work_date.strftime('%Y-%m-%d')
        } for s in sample_schedules]
        
        return render_template(
            'debug_feedback.html',
            feedback_data=feedback_data,
            test_schedules=test_schedules
        )
    except Exception as e:
        return f"Error: {str(e)}", 500

@app.route('/debug/tables')
def debug_tables():
    """Debug endpoint to view database tables and their contents"""
    try:
        # Check all our tables
        table_data = {
            'employees': Employee.query.count(),
            'shifts': Shift.query.count(),
            'schedules': Schedule.query.count(),
            'employee_preferences': EmployeePreference.query.count(),
            'consecutive_preferences': EmployeeConsecutiveDayPreference.query.count(),
            'schedule_feedback': ScheduleFeedback.query.count(),
            'employee_availability': EmployeeAvailability.query.count()
        }
        
        # Get some sample data from each table
        employees = [{
            'id': e.id,
            'name': e.full_name,
            'username': e.username
        } for e in Employee.query.limit(5).all()]
        
        shifts = [{
            'id': s.shift_id,
            'name': s.shift_name,
            'start': s.start_time.strftime('%H:%M'),
            'end': s.end_time.strftime('%H:%M')
        } for s in Shift.query.limit(5).all()]
        
        schedules = [{
            'id': s.schedule_id,
            'user_id': s.user_id,
            'shift_id': s.shift_id,
            'date': s.work_date.strftime('%Y-%m-%d')
        } for s in Schedule.query.limit(5).all()]
        
        preferences = [{
            'id': p.preference_id,
            'user_id': p.user_id,
            'shift_id': p.shift_id,
            'day': p.day_of_week,
            'weight': p.weight
        } for p in EmployeePreference.query.limit(5).all()]
        
        feedback = [{
            'id': f.feedback_id,
            'schedule_id': f.schedule_id,
            'score': f.satisfaction_score,
            'created_at': f.created_at.strftime('%Y-%m-%d %H:%M:%S')
        } for f in ScheduleFeedback.query.limit(5).all()]
        
        return jsonify({
            'table_counts': table_data,
            'sample_data': {
                'employees': employees,
                'shifts': shifts,
                'schedules': schedules,
                'preferences': preferences,
                'feedback': feedback
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)})

# =============== HELPER FUNCTIONS ===============

def display_schedule(start_date):
    # Calculate end date (two months)
    end_date = start_date + datetime.timedelta(days=56)  # 2 months
    
    # Query schedules in date range
    schedules = db.session.query(
        Schedule, Employee, Shift
    ).join(
        Employee, Schedule.user_id == Employee.id
    ).join(
        Shift, Schedule.shift_id == Shift.shift_id
    ).filter(
        Schedule.work_date >= start_date,
        Schedule.work_date < end_date
    ).all()
    
    # Format schedules for the template
    formatted_schedule = {}
    shift_names = {}
    schedule_ids = {}
    
    for s in schedules:
        employee_name = s.Employee.full_name
        shift_id = s.Shift.shift_id
        work_date = s.Schedule.work_date
        schedule_id = s.Schedule.schedule_id
        
        # Calculate day number from start date
        day_number = (work_date - start_date).days
        
        if employee_name not in formatted_schedule:
            formatted_schedule[employee_name] = {}
        
        formatted_schedule[employee_name][day_number] = shift_id
        shift_names[shift_id] = s.Shift.shift_name
        schedule_ids[f"{employee_name}_{day_number}"] = schedule_id
    
    # Print debug info
    print(f"Generated schedule_ids map with {len(schedule_ids)} entries")
    
    # Get data for the template
    employees = Employee.query.all()
    shifts = Shift.query.all()
    
    # Get counts for status boxes
    employee_count = Employee.query.count()
    shift_count = Shift.query.count()
    schedule_count = Schedule.query.count()
    
    # Add previous and next month links
    prev_month = start_date - datetime.timedelta(days=30)
    next_month = start_date + datetime.timedelta(days=30)
    
    return render_template(
        'index.html',
        employees=employees,
        shifts=shifts,
        schedule=formatted_schedule,
        shift_names=shift_names,
        schedule_ids=schedule_ids,
        start_date=start_date,
        datetime=datetime,
        employee_count=employee_count,
        shift_count=shift_count,
        schedule_count=schedule_count,
        prev_month=prev_month,
        next_month=next_month,
        show_schedule=True
    )

# =============== SCHEDULED TASKS ===============

# Scheduler task to run on the 1st day of specified months at 00:00
@scheduler.task('cron', id='generate_schedule', month='1,3,5,7,9,11', day=1, hour=0, minute=0, max_instances=1)
def scheduled_generate_schedule():
    with app.app_context():
        current_date = datetime.date.today()
        logger.info(f"Generating schedule for month: {current_date.month}")
        generate_schedule_task(current_date)

# Scheduler task to run weekly to optimize preferences based on feedback
@scheduler.task('cron', id='weekly_optimize', day_of_week=0, hour=1, minute=0, max_instances=1)
def scheduled_optimize_preferences():
    with app.app_context():
        logger.info("Running weekly preference optimization")
        optimize_preferences_task()

def generate_schedule_task(start_date=None):
    try:
        if start_date is None:
            start_date = datetime.date.today()
            
        logger.info(f"Starting schedule generation for date: {start_date}")
        
        # Calculate the end of the second month
        first_day_next_month = (start_date.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
        end_date = (first_day_next_month.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1)

        # Check if schedules already exist for the given period
        existing_schedules = Schedule.query.filter(Schedule.work_date >= start_date, Schedule.work_date <= end_date).first()
        if existing_schedules:
            logger.info(f"Schedules already exist for the period: {start_date} to {end_date}. Skipping generation.")
            return

        # Exclude users who are admins (RoleId = 1)
        non_admin_users = db.session.query(Employee.id, Employee.first_name, Employee.last_name).\
            join(IdentityUserRole, Employee.id == IdentityUserRole.user_id).\
            filter(IdentityUserRole.role_id != 1).all()

        employees = [{'id': user.id, 'name': f"{user.first_name} {user.last_name}"} for user in non_admin_users]
        shifts = [{'id': s.shift_id, 'name': s.shift_name, 'start_time': s.start_time, 'end_time': s.end_time} for s in Shift.query.all()]
        
        logger.info(f"Generating schedule for {len(employees)} employees and {len(shifts)} shifts")

        # If there are no employees or shifts, return
        if not employees or not shifts:
            logger.warning("No employees or shifts found. Schedule generation aborted.")
            return

        two_month_schedule = create_two_month_shift_schedule(employees, shifts, start_date, db.session)
        
        schedules_added = 0
        for emp_id, emp_schedule in two_month_schedule.items():
            for day, shift_id in emp_schedule.items():
                work_date = start_date + datetime.timedelta(days=day)
                if work_date > end_date:
                    continue
                new_schedule = Schedule(user_id=emp_id, shift_id=shift_id, work_date=work_date, schedule_hours=8)
                db.session.add(new_schedule)
                schedules_added += 1
        
        db.session.commit()
        logger.info(f"Schedule generated successfully. Added {schedules_added} entries for period: {start_date} to {end_date}")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error generating schedule: {str(e)}")
        raise

def optimize_preferences_task():
    """Run the ML-based optimization of employee preferences"""
    try:
        logger.info("Starting preference optimization")
        
        # Create optimizer with database URI
        db_uri = app.config['SQLALCHEMY_DATABASE_URI']
        optimizer = ScheduleOptimizer(db_uri)
        
        # Run full optimization
        success = optimizer.run_optimization()
        
        if success:
            logger.info("Preference optimization completed successfully")
        else:
            logger.warning("Preference optimization did not complete successfully")
            
    except Exception as e:
        logger.error(f"Error optimizing preferences: {str(e)}")

# Create the debug feedback template if it doesn't exist
def create_debug_template():
    """Create the debug feedback template if it doesn't exist"""
    template_path = os.path.join(app.root_path, 'templates', 'debug_feedback.html')
    
    if not os.path.exists(os.path.dirname(template_path)):
        os.makedirs(os.path.dirname(template_path))
    
    if not os.path.exists(template_path):
        debug_template = """
<!DOCTYPE html>
<html>
<head>
    <title>Feedback Debug</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        h1, h2 { color: #333; }
        table { border-collapse: collapse; width: 100%; margin-bottom: 20px; }
        th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
        th { background-color: #f2f2f2; }
        form { margin-bottom: 20px; padding: 15px; border: 1px solid #ddd; border-radius: 5px; }
        button { padding: 8px 16px; background-color: #4CAF50; color: white; border: none; cursor: pointer; }
        button:hover { background-color: #45a049; }
    </style>
</head>
<body>
    <h1>Feedback Debug Panel</h1>
    
    <h2>Test Feedback Submission</h2>
    <form action="/submit_feedback" method="post">
        <div>
            <label>Schedule ID:</label>
            <select name="schedule_id" required>
                <option value="">Select a schedule</option>
                {% for schedule in test_schedules %}
                <option value="{{ schedule.schedule_id }}">ID: {{ schedule.schedule_id }} - {{ schedule.employee }} - {{ schedule.date }} - {{ schedule.shift }}</option>
                {% endfor %}
            </select>
        </div>
        <div style="margin-top: 10px;">
            <label>Satisfaction Score:</label>
            <select name="satisfaction_score" required>
                <option value="5">5 - Very Happy</option>
                <option value="4">4 - Happy</option>
                <option value="3" selected>3 - Neutral</option>
                <option value="2">2 - Unhappy</option>
                <option value="1">1 - Very Unhappy</option>
            </select>
        </div>
        <button type="submit" style="margin-top: 10px;">Submit Test Feedback</button>
    </form>
    
    <h2>Existing Feedback Data</h2>
    {% if feedback_data %}
    <table>
        <thead>
            <tr>
                <th>Feedback ID</th>
                <th>Schedule ID</th>
                <th>Employee</th>
                <th>Shift</th>
                <th>Date</th>
                <th>Score</th>
                <th>Created At</th>
            </tr>
        </thead>
        <tbody>
            {% for feedback in feedback_data %}
            <tr>
                <td>{{ feedback.feedback_id }}</td>
                <td>{{ feedback.schedule_id }}</td>
                <td>{{ feedback.employee }}</td>
                <td>{{ feedback.shift }}</td>
                <td>{{ feedback.date }}</td>
                <td>{{ feedback.score }}</td>
                <td>{{ feedback.created_at }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    {% else %}
    <p>No feedback data found.</p>
    {% endif %}
    
    <a href="/debug/tables" target="_blank">View All Tables</a>
</body>
</html>
        """
        
        with open(template_path, 'w') as f:
            f.write(debug_template)

if __name__ == '__main__':
    with app.app_context():
        # Create the tables for our models if they don't exist
        try:
            db.create_all()
            logger.info("Database tables created/verified successfully")
            
            # Create debug template
            create_debug_template()
        except Exception as e:
            logger.error(f"Error creating database tables: {str(e)}")
        
        # Start the scheduler if it's not already running
        if not scheduler.running:
            scheduler.start()
    
    # Run the app with debug mode
    app.run(debug=True, host='0.0.0.0', port=5000)