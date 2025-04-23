#models.py

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, Float, Time, Date, DateTime
from sqlalchemy.orm import relationship

# This will be initialized in app.py
db = SQLAlchemy()

class Employee(db.Model):
    __tablename__ = 'appuser'
    __table_args__ = {'schema': 'public'}
    id = db.Column('Id', db.Integer, primary_key=True)  
    username = db.Column('UserName', db.String(256), nullable=True)
    first_name = db.Column('firstName', db.String(100), nullable=False)  
    last_name = db.Column('lastName', db.String(100), nullable=False)  
    
    # Add relationships matching your .NET model
    schedules = relationship("Schedule", back_populates="users")
    report_leaves = relationship("ReportLeave", back_populates="users")

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

class Shift(db.Model):
    __tablename__ = 'shifts'
    __table_args__ = {'schema': 'public'}
    shift_id = db.Column('shift_id', db.Integer, primary_key=True)  
    shift_name = db.Column('shift_name', db.String(100), nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    duration = db.Column(db.Integer, nullable=False)
    
    # Add relationship matching your .NET model
    schedules = relationship("Schedule", back_populates="shifts")

class Schedule(db.Model):
    __tablename__ = 'schedules'
    __table_args__ = {'schema': 'public'}
    
    schedule_id = db.Column('schedule_id', db.Integer, primary_key=True) 
    user_id = db.Column('user_id', db.Integer, db.ForeignKey('public.appuser.Id'), nullable=False)  
    shift_id = db.Column('shift_id', db.Integer, db.ForeignKey('public.shifts.shift_id'), nullable=False) 
    work_date = db.Column(db.Date, nullable=False)
    schedule_hours = db.Column('schedule_hours', db.Integer, nullable=False, default=8)  
    
    # Add relationships matching your .NET model
    users = relationship("Employee", back_populates="schedules")
    shifts = relationship("Shift", back_populates="schedules")

class IdentityUserRole(db.Model):
    __tablename__ = 'identityuserrole'
    __table_args__ = {'schema': 'public'}
    
    user_id = db.Column('UserId', db.Integer, db.ForeignKey('public.appuser.Id'), primary_key=True) 
    role_id = db.Column('RoleId', db.Integer, nullable=False)

class ReportLeave(db.Model):
    __tablename__ = 'report_leave'
    __table_args__ = {'schema': 'public'}
    
    report_leave_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('public.appuser.Id'), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    reason = db.Column(db.String(255), nullable=True)
    
    # Add relationship matching your .NET model
    users = relationship("Employee", back_populates="report_leaves")

# New AI-related models for preferences and feedback

class EmployeePreference(db.Model):
    __tablename__ = 'employee_preferences'
    __table_args__ = {'schema': 'public'}
    
    preference_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('public.appuser.Id'), nullable=False)
    shift_id = db.Column(db.Integer, db.ForeignKey('public.shifts.shift_id'), nullable=False)
    day_of_week = db.Column(db.Integer, nullable=True)  # 0=Monday, 6=Sunday, None=any day
    weight = db.Column(db.Float, nullable=False, default=1.0)
    
    # Relationships
    employee = relationship("Employee", backref="preferences")
    shift = relationship("Shift", backref="employee_preferences")
    
class EmployeeConsecutiveDayPreference(db.Model):
    __tablename__ = 'employee_consecutive_preferences'
    __table_args__ = {'schema': 'public'}
    
    preference_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('public.appuser.Id'), nullable=False)
    min_consecutive_days = db.Column(db.Integer, nullable=False, default=1)
    max_consecutive_days = db.Column(db.Integer, nullable=False, default=3)
    preferred_consecutive_days = db.Column(db.Integer, nullable=False, default=2)
    
    # Relationship
    employee = relationship("Employee", backref="consecutive_preferences")

class ShiftTransition(db.Model):
    __tablename__ = 'shift_transitions'
    __table_args__ = {'schema': 'public'}
    
    transition_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('public.appuser.Id'), nullable=False)
    from_shift_id = db.Column(db.Integer, db.ForeignKey('public.shifts.shift_id'), nullable=False)
    to_shift_id = db.Column(db.Integer, db.ForeignKey('public.shifts.shift_id'), nullable=False)
    penalty_weight = db.Column(db.Float, nullable=False, default=1.0)  # Higher = more undesirable
    
    # Relationships
    employee = relationship("Employee", backref="shift_transitions")
    from_shift = relationship("Shift", foreign_keys=[from_shift_id])
    to_shift = relationship("Shift", foreign_keys=[to_shift_id])

class ScheduleFeedback(db.Model):
    """Stores employee feedback on assigned schedules for ML learning"""
    __tablename__ = 'schedule_feedback'
    __table_args__ = {'schema': 'public'}
    
    feedback_id = db.Column(db.Integer, primary_key=True)
    schedule_id = db.Column(db.Integer, db.ForeignKey('public.schedules.schedule_id'), nullable=False)
    satisfaction_score = db.Column(db.Integer, nullable=False)  # 1-5 scale
    feedback = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    
    # Relationship
    schedule = relationship("Schedule", backref="feedback")

class EmployeeAvailability(db.Model):
    """Stores employee availability for specific dates"""
    __tablename__ = 'employee_availability'
    __table_args__ = {'schema': 'public'}
    
    availability_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('public.appuser.Id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    is_available = db.Column(db.Boolean, nullable=False, default=True)
    reason = db.Column(db.String(255), nullable=True)
    
    # Relationship
    employee = relationship("Employee", backref="availability")