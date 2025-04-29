# flask_api_endpoints.py
from flask import Blueprint, request, jsonify
from flask_cors import CORS
import datetime
import logging
from models import db, Employee, Shift, Schedule, EmployeePreference, EmployeeConsecutiveDayPreference, ShiftTransition, ScheduleFeedback, EmployeeAvailability, IdentityUserRole
from scheduler import create_two_month_shift_schedule
from ml_scheduler import ScheduleOptimizer

# Setup logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create Blueprint for API routes
api = Blueprint('api', __name__, url_prefix='/api')

# Apply CORS to this blueprint
CORS(api)

@api.route('/generate-schedule', methods=['POST'])
def generate_schedule_api():
    try:
        # Get start date from request
        data = request.json
        start_date_str = data.get('start_date')
        
        logger.info(f"Generate schedule requested with start date: {start_date_str}")
        
        if not start_date_str:
            return jsonify({'error': 'Start date is required'}), 400
            
        start_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d').date()
        
        # Calculate the end of the second month
        first_day_next_month = (start_date.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
        end_date = (first_day_next_month.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1)

        # Get employees and shifts
        non_admin_users = db.session.query(Employee.id, Employee.first_name, Employee.last_name).\
            join(IdentityUserRole, Employee.id == IdentityUserRole.user_id).\
            filter(IdentityUserRole.role_id != 1).all()
            
        logger.info(f"Found {len(non_admin_users)} non-admin users")

        employees = [{'id': user.id, 'name': f"{user.first_name} {user.last_name}"} for user in non_admin_users]
        shifts = [{'id': s.shift_id, 'name': s.shift_name, 'start_time': s.start_time, 'end_time': s.end_time} for s in Shift.query.all()]
        
        logger.info(f"Generating schedule for {len(employees)} employees and {len(shifts)} shifts")

        # If there are no employees or shifts, return
        if not employees or not shifts:
            logger.warning("No employees or shifts found. Schedule generation aborted.")
            return jsonify({'error': 'No employees or shifts found'}), 400

        # Generate the schedule
        two_month_schedule = create_two_month_shift_schedule(employees, shifts, start_date, db.session)
        
        # Log the received schedule structure
        logger.info(f"Schedule generated with {len(two_month_schedule)} employees")
        
        # Save schedules to database
        schedules_added = 0
        try:
            # Clear any existing schedules in this date range
            existing_schedules = Schedule.query.filter(
                Schedule.work_date >= start_date, 
                Schedule.work_date <= end_date
            ).all()
            
            if existing_schedules:
                logger.info(f"Deleting {len(existing_schedules)} existing schedules in the date range")
                for schedule in existing_schedules:
                    db.session.delete(schedule)
                db.session.commit()
            
            # Add new schedules
            for emp_id, emp_schedule in two_month_schedule.items():
                for day, shift_id in emp_schedule.items():
                    work_date = start_date + datetime.timedelta(days=int(day))
                    if work_date > end_date:
                        continue
                        
                    # Create new schedule
                    new_schedule = Schedule(
                        user_id=emp_id, 
                        shift_id=shift_id, 
                        work_date=work_date, 
                        schedule_hours=8
                    )
                    db.session.add(new_schedule)
                    schedules_added += 1
            
            # Commit changes
            db.session.commit()
            logger.info(f"Successfully saved {schedules_added} schedules to database")
            
        except Exception as save_error:
            db.session.rollback()
            logger.error(f"Error saving schedules: {str(save_error)}")
            import traceback
            logger.error(traceback.format_exc())
            return jsonify({'error': f'Error saving schedules: {str(save_error)}'}), 500
        
        return jsonify({
            'message': 'Schedule generated successfully',
            'schedules_added': schedules_added,
            'start_date': start_date.strftime('%Y-%m-%d'),
            'end_date': end_date.strftime('%Y-%m-%d')
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error generating schedule: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@api.route('/optimize-preferences', methods=['POST'])
def optimize_preferences_api():
    """API endpoint to run ML-based optimization of employee preferences"""
    try:
        # Get database URI from app config
        from flask import current_app
        db_uri = current_app.config['SQLALCHEMY_DATABASE_URI']
        
        # Create optimizer with database URI
        optimizer = ScheduleOptimizer(db_uri)
        
        # Run full optimization
        success = optimizer.run_optimization()
        
        if success:
            logger.info("Preference optimization completed successfully")
            return jsonify({'message': 'Preference optimization completed successfully'}), 200
        else:
            logger.warning("Preference optimization did not complete successfully")
            return jsonify({'error': 'Preference optimization did not complete successfully'}), 400
            
    except Exception as e:
        logger.error(f"Error optimizing preferences: {str(e)}")
        return jsonify({'error': str(e)}), 500

@api.route('/update-preference', methods=['POST'])
def update_preference_api():
    """API endpoint to update employee preference"""
    try:
        data = request.json
        user_id = data.get('user_id')
        shift_id = data.get('shift_id')
        day_of_week = data.get('day_of_week')
        weight = float(data.get('weight', 1.0))
        
        if not user_id or not shift_id:
            return jsonify({'error': 'User ID and Shift ID are required'}), 400
        
        # Check if preference exists
        pref = EmployeePreference.query.filter_by(
            user_id=user_id, 
            shift_id=shift_id,
            day_of_week=day_of_week if day_of_week else None
        ).first()
        
        if pref:
            # Update existing preference
            pref.weight = weight
            db.session.commit()
            return jsonify({'message': 'Preference updated successfully'}), 200
        else:
            # Create new preference
            new_pref = EmployeePreference(
                user_id=user_id,
                shift_id=shift_id,
                day_of_week=day_of_week if day_of_week else None,
                weight=weight
            )
            db.session.add(new_pref)
            db.session.commit()
            return jsonify({'message': 'Preference saved successfully'}), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating preference: {str(e)}")
        return jsonify({'error': str(e)}), 500

@api.route('/update-consecutive-preference', methods=['POST'])
def update_consecutive_preference_api():
    """API endpoint to update employee consecutive day preference"""
    try:
        data = request.json
        user_id = data.get('user_id')
        min_days = int(data.get('min_days', 1))
        max_days = int(data.get('max_days', 3))
        preferred_days = int(data.get('preferred_days', 2))
        
        if not user_id:
            return jsonify({'error': 'User ID is required'}), 400
        
        # Check if preference exists
        pref = EmployeeConsecutiveDayPreference.query.filter_by(user_id=user_id).first()
        
        if pref:
            # Update existing preference
            pref.min_consecutive_days = min_days
            pref.max_consecutive_days = max_days
            pref.preferred_consecutive_days = preferred_days
            db.session.commit()
            return jsonify({'message': 'Consecutive day preference updated successfully'}), 200
        else:
            # Create new preference
            new_pref = EmployeeConsecutiveDayPreference(
                user_id=user_id,
                min_consecutive_days=min_days,
                max_consecutive_days=max_days,
                preferred_consecutive_days=preferred_days
            )
            db.session.add(new_pref)
            db.session.commit()
            return jsonify({'message': 'Consecutive day preference saved successfully'}), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating consecutive preferences: {str(e)}")
        return jsonify({'error': str(e)}), 500

@api.route('/update-availability', methods=['POST'])
def update_availability_api():
    """API endpoint to update employee availability"""
    try:
        data = request.json
        user_id = data.get('user_id')
        date_str = data.get('date')
        is_available = data.get('is_available', True)
        reason = data.get('reason', '')
        
        if not user_id or not date_str:
            return jsonify({'error': 'User ID and date are required'}), 400
        
        # Parse date string to date object
        date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
        
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
            return jsonify({'message': f"Availability updated successfully for {date_str}"}), 200
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
            return jsonify({'message': f"Availability saved successfully for {date_str}"}), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating availability: {str(e)}")
        return jsonify({'error': str(e)}), 500

@api.route('/submit-feedback', methods=['POST'])
def submit_feedback_api():
    """API endpoint to submit shift feedback"""
    try:
        data = request.json
        schedule_id = data.get('schedule_id')
        satisfaction_score = data.get('satisfaction_score')
        feedback_text = data.get('feedback', '')
        
        if not schedule_id or not satisfaction_score:
            return jsonify({'error': 'Schedule ID and satisfaction score are required'}), 400
            
        try:
            schedule_id = int(schedule_id)
            satisfaction_score = int(satisfaction_score)
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid data format'}), 400
        
        # Verify the schedule exists
        schedule = Schedule.query.get(schedule_id)
        if not schedule:
            return jsonify({'error': f"Schedule with ID {schedule_id} does not exist"}), 404
        
        if not (1 <= satisfaction_score <= 5):
            return jsonify({'error': f"Satisfaction score must be between 1 and 5"}), 400
        
        # Check if feedback already exists
        existing_feedback = ScheduleFeedback.query.filter_by(schedule_id=schedule_id).first()
        
        if existing_feedback:
            # Update existing feedback
            existing_feedback.satisfaction_score = satisfaction_score
            existing_feedback.feedback = feedback_text
            db.session.commit()
            
            return jsonify({'message': 'Feedback updated successfully'}), 200
        else:
            # Create new feedback
            new_feedback = ScheduleFeedback(
                schedule_id=schedule_id,
                satisfaction_score=satisfaction_score,
                feedback=feedback_text,
                created_at=datetime.datetime.now()
            )
            db.session.add(new_feedback)
            db.session.commit()
            
            return jsonify({'message': 'Feedback saved successfully'}), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error submitting feedback: {str(e)}")
        return jsonify({'error': str(e)}), 500

@api.route('/simple-schedules', methods=['GET'])
def simple_schedules():
    try:
        # Get all schedules with no filtering, sort by date
        schedules = Schedule.query.order_by(Schedule.work_date.desc()).limit(500).all()
        
        # Log count retrieved
        logger.info(f"Retrieved {len(schedules)} schedules from database")
        
        # Format the results
        schedules_list = []
        for schedule in schedules:
            try:
                # Ensure date is in ISO format string (YYYY-MM-DD)
                date_str = schedule.work_date.strftime('%Y-%m-%d')
                
                schedules_list.append({
                    "scheduleID": schedule.schedule_id,
                    "userID": schedule.user_id,
                    "shiftID": schedule.shift_id,
                    "shiftDate": date_str,  # Use consistent format
                    "scheduleHours": schedule.schedule_hours,
                    "firstName": schedule.users.first_name if schedule.users else "Unknown",
                    "lastName": schedule.users.last_name if schedule.users else "Unknown",
                    "shiftName": schedule.shifts.shift_name if schedule.shifts else "Unknown",
                    "startTime": schedule.shifts.start_time.strftime('%H:%M:%S') if schedule.shifts and schedule.shifts.start_time else None,
                    "endTime": schedule.shifts.end_time.strftime('%H:%M:%S') if schedule.shifts and schedule.shifts.end_time else None
                })
            except Exception as row_error:
                logger.error(f"Error processing schedule {schedule.schedule_id}: {str(row_error)}")
        
        # Log some examples for debugging
        if schedules_list:
            logger.info(f"First schedule example: {schedules_list[0]}")
            
        logger.info(f"Returning {len(schedules_list)} schedules")
        
        return jsonify({
            "count": len(schedules_list),
            "schedules": schedules_list
        })
        
    except Exception as e:
        logger.error(f"Error in simple schedules: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500