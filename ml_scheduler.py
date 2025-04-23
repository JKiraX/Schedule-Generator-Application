#ml_schedular.py

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sqlalchemy import create_engine, text
import datetime
import os
import logging

logger = logging.getLogger(__name__)

class ScheduleOptimizer:
    def __init__(self, db_uri):
        self.db_uri = db_uri
        self.engine = create_engine(db_uri)
        
    def fetch_historical_data(self, lookback_months=6):
        """Fetch historical scheduling and feedback data"""
        today = datetime.date.today()
        start_date = today - datetime.timedelta(days=30 * lookback_months)
        
        query = f"""
        SELECT 
            s.user_id, 
            s.shift_id, 
            s.work_date, 
            extract(isodow from s.work_date) as day_of_week,
            extract(day from s.work_date) as day_of_month,
            sh.start_time,
            sh.end_time,
            COALESCE(sf.satisfaction_score, 3) as satisfaction_score,
            COALESCE(sf.feedback, '') as feedback
        FROM 
            public.schedules s
        JOIN 
            public.shifts sh ON s.shift_id = sh.shift_id
        LEFT JOIN 
            public.schedule_feedback sf ON s.schedule_id = sf.schedule_id
        WHERE 
            s.work_date >= '{start_date}'
        ORDER BY 
            s.user_id, s.work_date
        """
        
        return pd.read_sql(query, self.engine)
    
    def analyze_employee_patterns(self, historical_data):
        """Analyze patterns in employee scheduling preferences"""
        patterns = {}
        
        for user_id, user_data in historical_data.groupby('user_id'):
            # Calculate shift frequency by day of week
            shift_day_freq = user_data.groupby(['shift_id', 'day_of_week']).size().reset_index(name='count')
            shift_day_freq_dict = {(row['shift_id'], row['day_of_week']): row['count'] 
                                  for _, row in shift_day_freq.iterrows()}
            
            # Calculate satisfaction by shift and day
            satisfaction = user_data.groupby(['shift_id', 'day_of_week'])['satisfaction_score'].mean().reset_index()
            satisfaction_dict = {(row['shift_id'], row['day_of_week']): row['satisfaction_score'] 
                                for _, row in satisfaction.iterrows()}
            
            # Find consecutive day patterns
            consecutive_days = []
            
            # Sort work dates
            work_dates = sorted(user_data['work_date'].unique())
            streak = 1
            
            for i in range(1, len(work_dates)):
                delta = (work_dates[i] - work_dates[i-1]).days
                if delta == 1:
                    streak += 1
                else:
                    if streak > 1:
                        consecutive_days.append(streak)
                    streak = 1
            
            if streak > 1:
                consecutive_days.append(streak)
            
            avg_consecutive = np.mean(consecutive_days) if consecutive_days else 1
            
            # Find preferred shifts based on satisfaction score
            preferred_shifts = user_data.groupby('shift_id')['satisfaction_score'].mean().sort_values(ascending=False).index.tolist()
            
            # Store employee patterns
            patterns[user_id] = {
                'shift_day_frequency': shift_day_freq_dict,
                'satisfaction_by_shift_day': satisfaction_dict,
                'avg_consecutive_days': avg_consecutive,
                'preferred_shifts': preferred_shifts
            }
        
        return patterns
    
    def cluster_employees(self, historical_data):
        """Group employees with similar preferences using clustering"""
        if len(historical_data['user_id'].unique()) < 3:  # Not enough data for meaningful clustering
            return {}
            
        # Feature engineering for clustering
        user_features = []
        user_ids = []
        
        # Prepare feature columns
        all_shifts = historical_data['shift_id'].unique()
        all_days = range(1, 8)  # 1-7 for Monday-Sunday
        
        for user_id, user_data in historical_data.groupby('user_id'):
            # Features vector
            features = []
            
            # Add shift preference features
            shift_counts = user_data.groupby('shift_id').size()
            for shift in all_shifts:
                features.append(shift_counts.get(shift, 0))
            
            # Add day of week features
            day_counts = user_data.groupby('day_of_week').size()
            for day in all_days:
                features.append(day_counts.get(day, 0))
            
            # Add satisfaction score
            features.append(user_data['satisfaction_score'].mean())
            
            user_features.append(features)
            user_ids.append(user_id)
        
        if not user_features:
            return {}
        
        # Convert to numpy array
        X = np.array(user_features)
        
        # Handle the case if we have all zeros (no features)
        if np.all(X == 0):
            return {user_id: 0 for user_id in user_ids}
        
        # Standardize features
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        
        # Determine optimal number of clusters
        n_clusters = min(max(2, len(user_ids) // 3), 5)
        
        # Apply KMeans clustering
        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        clusters = kmeans.fit_predict(X_scaled)
        
        # Create employee clusters mapping
        employee_clusters = {user_id: int(cluster) for user_id, cluster in zip(user_ids, clusters)}
        
        return employee_clusters
    
    def generate_preference_weights(self, employee_patterns, clusters=None):
        """Generate preference weights for the scheduling algorithm"""
        preference_weights = {}
        
        for user_id, patterns in employee_patterns.items():
            # Initialize weights
            shift_day_weights = {}
            consecutive_day_preference = 2  # Default
            
            # Calculate shift-day weights from frequency and satisfaction
            for shift_id in patterns['preferred_shifts']:
                for day in range(1, 8):  # 1-7 for Monday-Sunday
                    key = (shift_id, day)
                    frequency = patterns['shift_day_frequency'].get(key, 0)
                    satisfaction = patterns['satisfaction_by_shift_day'].get(key, 3)
                    
                    # Calculate weight: higher for preferred shifts/days
                    weight = 1.0  # Neutral
                    
                    if frequency > 0:
                        # Normalize satisfaction to a weight (1.0-2.0 for positive, 0.5-1.0 for negative)
                        if satisfaction >= 3:  # Positive satisfaction
                            weight = 1.0 + (satisfaction - 3) / 2
                        else:  # Negative satisfaction
                            weight = 1.0 - (3 - satisfaction) / 2
                    
                    shift_day_weights[key] = weight
            
            # Set consecutive day preference
            consecutive_day_preference = round(patterns['avg_consecutive_days'])
            
            # Ensure consecutive days are within reasonable bounds
            consecutive_day_preference = max(1, min(5, consecutive_day_preference))
            
            # Store preferences
            preference_weights[user_id] = {
                'shift_day_weights': shift_day_weights,
                'consecutive_days': consecutive_day_preference
            }
        
        return preference_weights
    
    def update_employee_preferences(self, preference_weights):
        """Update employee preferences in database"""
        with self.engine.connect() as conn:
            # Begin transaction
            trans = conn.begin()
            try:
                for user_id, preferences in preference_weights.items():
                    # Update shift-day preferences
                    for (shift_id, day), weight in preferences['shift_day_weights'].items():
                        # Check if preference exists
                        check_sql = text("""
                            SELECT preference_id FROM public.employee_preferences 
                            WHERE user_id = :user_id AND shift_id = :shift_id AND day_of_week = :day
                        """)
                        
                        result = conn.execute(check_sql, {"user_id": user_id, "shift_id": shift_id, "day": day}).fetchone()
                        
                        if result:
                            # Update existing preference
                            update_sql = text("""
                                UPDATE public.employee_preferences 
                                SET weight = :weight
                                WHERE preference_id = :pref_id
                            """)
                            conn.execute(update_sql, {"weight": weight, "pref_id": result[0]})
                        else:
                            # Insert new preference
                            insert_sql = text("""
                                INSERT INTO public.employee_preferences (user_id, shift_id, day_of_week, weight)
                                VALUES (:user_id, :shift_id, :day, :weight)
                            """)
                            conn.execute(insert_sql, {"user_id": user_id, "shift_id": shift_id, "day": day, "weight": weight})
                    
                    # Update consecutive day preferences
                    consec_days = preferences['consecutive_days']
                    check_consec_sql = text("""
                        SELECT preference_id FROM public.employee_consecutive_preferences 
                        WHERE user_id = :user_id
                    """)
                    
                    consec_result = conn.execute(check_consec_sql, {"user_id": user_id}).fetchone()
                    
                    if consec_result:
                        # Update existing preference
                        update_consec_sql = text("""
                            UPDATE public.employee_consecutive_preferences 
                            SET preferred_consecutive_days = :days,
                                min_consecutive_days = :min_days,
                                max_consecutive_days = :max_days
                            WHERE preference_id = :pref_id
                        """)
                        conn.execute(update_consec_sql, {
                            "days": consec_days, 
                            "min_days": max(1, consec_days - 1),
                            "max_days": min(5, consec_days + 1),
                            "pref_id": consec_result[0]
                        })
                    else:
                        # Insert new preference
                        insert_consec_sql = text("""
                            INSERT INTO public.employee_consecutive_preferences 
                            (user_id, preferred_consecutive_days, min_consecutive_days, max_consecutive_days)
                            VALUES (:user_id, :days, :min_days, :max_days)
                        """)
                        conn.execute(insert_consec_sql, {
                            "user_id": user_id, 
                            "days": consec_days,
                            "min_days": max(1, consec_days - 1),
                            "max_days": min(5, consec_days + 1)
                        })
                
                # Commit transaction
                trans.commit()
                logger.info(f"Updated preferences for {len(preference_weights)} employees")
                return True
                
            except Exception as e:
                trans.rollback()
                logger.error(f"Error updating employee preferences: {str(e)}")
                return False
    
    def run_optimization(self):
        """Run the full optimization pipeline"""
        try:
            # Fetch historical data
            logger.info("Fetching historical scheduling data")
            historical_data = self.fetch_historical_data()
            
            if len(historical_data) == 0:
                logger.info("No historical data available for analysis")
                return False
            
            # Analyze employee patterns
            logger.info("Analyzing employee scheduling patterns")
            employee_patterns = self.analyze_employee_patterns(historical_data)
            
            # Cluster employees by preference similarity
            logger.info("Clustering employees by preferences")
            employee_clusters = self.cluster_employees(historical_data)
            
            # Generate preference weights
            logger.info("Generating preference weights")
            preference_weights = self.generate_preference_weights(employee_patterns, employee_clusters)
            
            # Update employee preferences in database
            logger.info("Updating employee preferences in database")
            success = self.update_employee_preferences(preference_weights)
            
            return success
            
        except Exception as e:
            logger.error(f"Error in optimization pipeline: {str(e)}")
            return False