# celery_app.py

import os
from celery import Celery
from celery.schedules import crontab
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Define the Celery application instance
# The first argument is the name of the current module.
# The `include` argument is a list of modules to import when the worker starts,
# so it can find the decorated tasks.
celery = Celery(
    'tasks',
    broker=os.getenv('CELERY_BROKER_URL'),
    backend=os.getenv('CELERY_RESULT_BACKEND'),
    include=['tasks', 'sourcerer']
)

# Optional configuration, specifying UTC for timezone-aware scheduling
celery.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
)

# --- CELERY BEAT SCHEDULE ---
# This dictionary defines all recurring tasks for the application.
# Celery Beat will read this schedule and dispatch tasks at the specified times.
celery.conf.beat_schedule = {
    # Task to scrape all active sources every hour at minute 0
    'run-scraper-every-hour': {
        'task': 'tasks.run_scraper_cycle',
        'schedule': crontab(minute=0, hour='*'),
    },
    # Task to discover new potential sources once a day at 2 AM
    'find-new-sources-daily': {
        'task': 'sourcerer.find_new_sources',
        'schedule': crontab(hour=2, minute=0),
    },
    # Task to send the weekly digest email every Sunday at 8 AM UTC
    'send-weekly-digest-every-sunday': {
        'task': 'tasks.send_weekly_digest',
        'schedule': crontab(hour=8, minute=0, day_of_week=0),
        # Arguments to pass to the task. Fetches recipient from .env
        'args': ([os.getenv('DIGEST_RECIPIENT_EMAIL', 'admin@example.com')]),
    },
}

if __name__ == '__main__':
    celery.start()