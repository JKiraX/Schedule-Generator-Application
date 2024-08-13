from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from scheduler import create_monthly_shift_schedule
import datetime
import os
from dotenv import load_dotenv
# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
# Get the database connection details from environment variables
db_user = os.getenv('DATABASE_USER')
db_password = os.getenv('DATABASE_PASSWORD')
db_host = os.getenv('DATABASE_HOST')
db_port = os.getenv('DATABASE_PORT')
db_name = os.getenv('DATABASE_NAME')

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
    name = request.form['name']
    new_employee = Employee(name=name)
    db.session.add(new_employee)
    db.session.commit()
    return jsonify({'message': 'Employee added successfully'})

@app.route('/add_shift', methods=['POST'])
def add_shift():
    start_time = request.form['start_time']
    end_time = request.form['end_time']
    new_shift = Shift(start_time=start_time, end_time=end_time)
    db.session.add(new_shift)
    db.session.commit()
    return jsonify({'message': 'Shift added successfully'})

@app.route('/generate_schedule', methods=['POST'])
def generate_schedule():
    employees = [{'id': e.id, 'name': e.name} for e in Employee.query.all()]
    shifts = [{'id': s.id, 'start_time': s.start_time, 'end_time': s.end_time} for s in Shift.query.all()]
    start_date = datetime.datetime.strptime(request.form['start_date'], '%Y-%m-%d').date()
    
    monthly_schedule = create_monthly_shift_schedule(employees, shifts, start_date)
    
    # Clear existing schedules
    Schedule.query.delete()
    
    for emp_id, emp_schedule in monthly_schedule.items():
        for day, shift_id in emp_schedule.items():
            work_date = start_date + datetime.timedelta(days=day)
            new_schedule = Schedule(employee_id=emp_id, shift_id=shift_id, work_date=work_date)
            db.session.add(new_schedule)
    
    db.session.commit()
    
    # Prepare schedule data for the template
    schedule_data = {}
    for emp in employees:
        schedule_data[emp['name']] = {}
        for schedule in Schedule.query.filter_by(employee_id=emp['id']).all():
            if schedule.work_date not in schedule_data[emp['name']]:
                schedule_data[emp['name']][schedule.work_date] = []
            shift = Shift.query.get(schedule.shift_id)
            schedule_data[emp['name']][schedule.work_date].append(f"{shift.start_time.strftime('%H:%M')}-{shift.end_time.strftime('%H:%M')}")
    
    return render_template('index.html', schedule=schedule_data, start_date=start_date, datetime=datetime)

if __name__ == '__main__':
    app.run(debug=True)
