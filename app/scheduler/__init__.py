from apscheduler.schedulers.background import BackgroundScheduler
from app.scheduler.jobs import generate_monthly_schedules

def start():
    scheduler = BackgroundScheduler()
    scheduler.add_job(generate_monthly_schedules, 'cron', day=1, hour=0, minute=0)
    scheduler.start()
