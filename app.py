from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from scheduler import create_two_month_shift_schedule
from flask_apscheduler import APScheduler

import datetime
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# Initialize APScheduler
scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()

# Get the database connection details from environment variables
db_user = os.getenv('DATABASE_USER')
db_password = os.getenv('DATABASE_PASSWORD')
db_host = os.getenv('DATABASE_HOST')
db_port = os.getenv('DATABASE_PORT')
db_name = os.getenv('DATABASE_NAME')

# Ensure all environment variables are loaded
assert all([db_user, db_password, db_host, db_port, db_name]), "Database environment variables missing"

app.config['SQLALCHEMY_DATABASE_URI'] = f'postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}'
db = SQLAlchemy(app)

class Employee(db.Model):
    __tablename__ = 'appuser'
    __table_args__ = {'schema': 'public'}
    id = db.Column('Id', db.Integer, primary_key=True)  # Use 'Id' with correct case
    first_name = db.Column('firstName', db.String(100), nullable=False)
    last_name = db.Column('lastName', db.String(100), nullable=False)

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

class Shift(db.Model):
    __tablename__ = 'shifts'
    __table_args__ = {'schema': 'public'}
    id = db.Column('shiftID', db.Integer, primary_key=True)  # Corrected to 'shiftID'
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)

class Schedule(db.Model):
    __tablename__ = 'schedules'
    __table_args__ = {'schema': 'public'}
    
    schedule_id = db.Column('scheduleID', db.Integer, primary_key=True)  # Corrected to 'scheduleID'
    employee_id = db.Column('Id', db.Integer, nullable=False)  # Corrected to 'Id'
    shift_id = db.Column('shiftID', db.Integer, db.ForeignKey('public.shifts.shiftID'), nullable=False)
    work_date = db.Column(db.Date, nullable=False)
    schedule_hours = db.Column('scheduleHours', db.Integer, nullable=False, default=8)  # Default value set to 8

class IdentityUserRole(db.Model):
    __tablename__ = 'identityuserrole'
    __table_args__ = {'schema': 'public'}
    
    user_id = db.Column('UserId', db.Integer, db.ForeignKey('public.appuser.Id'), primary_key=True)
    role_id = db.Column('RoleId', db.Integer, nullable=False)


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/add_employee', methods=['POST'])
def add_employee():
    try:
        first_name = request.form['first_name']
        last_name = request.form['last_name']
        if not (first_name and last_name):
            return jsonify({'message': 'First name and last name are required'}), 400
        
        new_employee = Employee(first_name=first_name, last_name=last_name)
        db.session.add(new_employee)
        db.session.commit()
        return jsonify({'message': 'Employee added successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/add_shift', methods=['POST'])
def add_shift():
    try:
        start_time = datetime.datetime.strptime(request.form['start_time'], '%H:%M').time()
        end_time = datetime.datetime.strptime(request.form['end_time'], '%H:%M').time()
        
        if not (start_time and end_time):
            return jsonify({'message': 'Both start_time and end_time are required'}), 400
        
        new_shift = Shift(start_time=start_time, end_time=end_time)
        db.session.add(new_shift)
        db.session.commit()
        return jsonify({'message': 'Shift added successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

        

@app.route('/generate_schedule', methods=['POST'])
def generate_schedule():
    try:
        start_date = datetime.datetime.strptime(request.form['start_date'], '%Y-%m-%d').date()
        generate_schedule_task(start_date)
        return jsonify({'message': 'Schedule generated successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/trigger_schedule_generation', methods=['POST'])
def trigger_schedule_generation():
    try:
        generate_schedule_task()
        return jsonify({'message': 'Schedule generation triggered successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def generate_schedule_task(start_date=None):
    with app.app_context():
        try:
            if start_date is None:
                start_date = datetime.date.today().replace(day=1)  # Start from the first day of the current month
            
            # Calculate the end of the second month
            first_day_next_month = (start_date.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
            end_date = (first_day_next_month.replace(day=28) + datetime.timedelta(days=32)).replace(day=1) - datetime.timedelta(days=1)

            # Check if schedules already exist for the given period
            existing_schedules_count = Schedule.query.filter(Schedule.work_date >= start_date, Schedule.work_date <= end_date).count()
            if existing_schedules_count > 0:
                print(f"Schedules already exist for the period: {start_date} to {end_date}. Skipping generation.")
                return

            # Exclude users who are admins (RoleId = 1)
            non_admin_users = db.session.query(Employee.id, Employee.first_name, Employee.last_name).\
                join(IdentityUserRole, Employee.id == IdentityUserRole.user_id).\
                filter(IdentityUserRole.role_id != 1).all()

            employees = [{'id': user.id, 'name': f"{user.first_name} {user.last_name}"} for user in non_admin_users]
            shifts = [{'id': s.id, 'start_time': s.start_time, 'end_time': s.end_time} for s in Shift.query.all()]
            
            two_month_schedule = create_two_month_shift_schedule(employees, shifts, start_date)
            
            for emp_id, emp_schedule in two_month_schedule.items():
                for day, shift_id in emp_schedule.items():
                    work_date = start_date + datetime.timedelta(days=day)
                    if work_date > end_date:
                        continue
                    new_schedule = Schedule(employee_id=emp_id, shift_id=shift_id, work_date=work_date)
                    db.session.add(new_schedule)
            
            db.session.commit()
            print(f"Schedule generated for period: {start_date} to {end_date}")
        except Exception as e:
            db.session.rollback()
            print(f"Error generating schedule: {str(e)}")


# @scheduler.task('cron', id='generate_schedule', minute='*/1') - for testing (generating every minute)
@scheduler.task('cron', id='generate_schedule', day=1, month='1,3,5,7,9,11', hour=0, minute=0)
def scheduled_generate_schedule():
    generate_schedule_task()
def check_and_generate_schedule():
    
    with app.app_context():
        try:
            # Get the start date of the current month
            start_date = datetime.date.today().replace(day=1)
            
            # Calculate the end of the second month
            first_day_next_month = (start_date.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
            end_date = (first_day_next_month.replace(day=28) + datetime.timedelta(days=32)).replace(day=1) - datetime.timedelta(days=1)

            # Check if there are existing schedules for the period
            existing_schedules = Schedule.query.filter(Schedule.work_date >= start_date, Schedule.work_date <= end_date).count()

            if existing_schedules == 0:
                # No schedules exist for this period, so generate new ones
                print(f"No existing schedules found for period: {start_date} to {end_date}. Generating new schedules.")
                generate_schedule_task(start_date)
            else:
                print(f"Schedules already exist for period: {start_date} to {end_date}. No action taken.")
        except Exception as e:
            print(f"Error checking schedules: {str(e)}")

# Route to manually trigger the check and generate function
@app.route('/check_and_generate_schedule', methods=['POST'])
def check_and_generate_schedule_route():
    try:
        check_and_generate_schedule()
        return jsonify({'message': 'Check and generate schedule task completed successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True)
