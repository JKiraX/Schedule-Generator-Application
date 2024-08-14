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
    __tablename__ = 'employees'
    __table_args__ = {'schema': 'schedule1'}
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)

class Shift(db.Model):
    __tablename__ = 'shifts'
    __table_args__ = {'schema': 'schedule1'}
    id = db.Column(db.Integer, primary_key=True)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)

class Schedule(db.Model):
    __tablename__ = 'schedules'
    __table_args__ = {'schema': 'schedule1'}
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('schedule1.employees.id'), nullable=False)
    shift_id = db.Column(db.Integer, db.ForeignKey('schedule1.shifts.id'), nullable=False)
    work_date = db.Column(db.Date, nullable=False)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/add_employee', methods=['POST'])
def add_employee():
    try:
        name = request.form['name']
        if not name:
            return jsonify({'message': 'Name is required'}), 400
        
        new_employee = Employee(name=name)
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
            
            employees = [{'id': e.id, 'name': e.name} for e in Employee.query.all()]
            shifts = [{'id': s.id, 'start_time': s.start_time, 'end_time': s.end_time} for s in Shift.query.all()]
            
            two_month_schedule = create_two_month_shift_schedule(employees, shifts, start_date)
            
            # Clear existing schedules for the period
            end_date = start_date + datetime.timedelta(days=56)
            Schedule.query.filter(Schedule.work_date >= start_date, Schedule.work_date < end_date).delete()
            
            for emp_id, emp_schedule in two_month_schedule.items():
                for day, shift_id in emp_schedule.items():
                    work_date = start_date + datetime.timedelta(days=day)
                    new_schedule = Schedule(employee_id=emp_id, shift_id=shift_id, work_date=work_date)
                    db.session.add(new_schedule)
            
            db.session.commit()
            print(f"Schedule generated for period: {start_date} to {end_date}")
        except Exception as e:
            db.session.rollback()
            print(f"Error generating schedule: {str(e)}")

@scheduler.task('cron', id='generate_schedule', day=1, month='1,3,5,7,9,11', hour=0, minute=0)
def scheduled_generate_schedule():
    generate_schedule_task()



if __name__ == '__main__':
    app.run(debug=True)
