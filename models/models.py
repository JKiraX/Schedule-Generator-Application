from app import db
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

class User(db.Model):
    __tablename__ = 'users'

    userID = db.Column(db.Integer, primary_key=True)
    firstName = db.Column(db.String(50), nullable=False)
    lastName = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)

    schedules = db.relationship('Schedule', back_populates='user')

    def set_password(self, password):
        self.password = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password, password)

    def __repr__(self):
        return f'<User {self.firstName} {self.lastName}>'

class Shift(db.Model):
    __tablename__ = 'shifts'

    shiftID = db.Column(db.Integer, primary_key=True)
    startTime = db.Column(db.Time, nullable=False)
    endTime = db.Column(db.Time, nullable=False)
    duration = db.Column(db.Interval, nullable=False)
    shiftName = db.Column(db.String(50), nullable=False)

    schedules = db.relationship('Schedule', back_populates='shift')

    def __repr__(self):
        return f'<Shift {self.shiftName} {self.startTime}-{self.endTime}>'

class Schedule(db.Model):
    __tablename__ = 'schedules'

    scheduleID = db.Column(db.Integer, primary_key=True)
    shiftDate = db.Column(db.Date, nullable=False)
    userID = db.Column(db.Integer, db.ForeignKey('users.userID'), nullable=False)
    shiftID = db.Column(db.Integer, db.ForeignKey('shifts.shiftID'), nullable=False)
    scheduleHours = db.Column(db.Float, nullable=False)

    user = db.relationship('User', back_populates='schedules')
    shift = db.relationship('Shift', back_populates='schedules')

    def __repr__(self):
        return f'<Schedule {self.shiftDate} User:{self.userID} Shift:{self.shiftID}>'