# health.py

import os
import psutil
from redis import Redis, exceptions as redis_exceptions
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from celery_app import celery
from dotenv import load_dotenv

# Load environment variables to get connection strings
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL")

def get_celery_stats():
    """
    A simplified and more robust function to get Celery stats.
    It prioritizes getting worker stats but gracefully reports status
    if workers are busy or the broker is down.
    """
    # First, check if the broker itself is reachable.
    if get_redis_status() != "Online":
        return {"status": "Error", "message": "Broker connection is down."}

    try:
        inspector = celery.control.inspect(timeout=2.0)
        stats = inspector.stats()
        
        if not stats:
            # If no stats are returned, it means workers are offline or too busy to respond.
            return {
                "status": "Idle / Unresponsive",
                "message": "No workers responded to ping. They may be busy or offline.",
                "active_workers": 0,
                "total_tasks_processed": "N/A",
                "tasks_in_progress": "N/A"
            }

        # If we get here, at least one worker responded.
        worker_count = len(stats)
        total_processed = 0
        for worker_stats in stats.values():
            if isinstance(worker_stats, dict) and isinstance(worker_stats.get('total'), int):
                total_processed += worker_stats.get('total', 0)

        tasks_in_progress = 0
        active = inspector.active()
        if active:
            for worker_tasks in active.values():
                if isinstance(worker_tasks, list):
                    tasks_in_progress += len(worker_tasks)
            
        return {
            "status": "Online",
            "message": f"{worker_count} worker(s) responding.",
            "active_workers": worker_count,
            "total_tasks_processed": total_processed,
            "tasks_in_progress": tasks_in_progress
        }

    except Exception as e:
        # This catches any other unexpected errors from celery.control
        print(f"HEALTH: An unexpected error occurred in get_celery_stats: {e}")
        return {"status": "Error", "message": "Failed to inspect workers."}


def get_redis_status():
    """
    Checks the Redis message broker connection and returns 'Online' or 'Offline'.
    """
    if not CELERY_BROKER_URL:
        return "Not Configured"
    try:
        # Use the same connection method as our other services for consistency
        redis_client = Redis.from_url(CELERY_BROKER_URL, socket_connect_timeout=2)
        return "Online" if redis_client.ping() else "Offline"
    except redis_exceptions.ConnectionError:
        return "Offline"
    except Exception as e:
        print(f"HEALTH: An unexpected Redis error occurred: {e}")
        return "Error"

def get_db_status():
    """
    Checks the PostgreSQL database connection and returns 'Online' or 'Offline'.
    """
    if not DATABASE_URL:
        return "Not Configured"
    try:
        engine = create_engine(DATABASE_URL, connect_args={"connect_timeout": 5})
        with engine.connect() as connection:
            # Execute a simple, fast query to verify connection.
            result = connection.execute(text("SELECT 1"))
            return "Online" if result.scalar() == 1 else "Offline"
    except OperationalError as e:
        print(f"HEALTH: DB connection failed: {e}")
        return "Offline"
    except Exception as e:
        print(f"HEALTH: An unexpected DB error occurred: {e}")
        return "Error"

def get_redis_status():
    """
    Checks the Redis message broker connection and returns 'Online' or 'Offline'.
    """
    if not CELERY_BROKER_URL:
        return "Not Configured"
    try:
        redis_client = Redis.from_url(CELERY_BROKER_URL, socket_connect_timeout=5)
        return "Online" if redis_client.ping() else "Offline"
    except redis_exceptions.ConnectionError as e:
        print(f"HEALTH: Redis connection failed: {e}")
        return "Offline"
    except Exception as e:
        print(f"HEALTH: An unexpected Redis error occurred: {e}")
        return "Error"

def get_system_usage():
    """
    Gets CPU and Memory usage of the host system where this script is running.
    Note: In a containerized environment, this reflects the container's resource view
    unless configured otherwise. For system-wide metrics, monitoring tools are better.
    
    Returns: A dictionary with CPU and memory percentages.
    """
    try:
        # psutil.cpu_percent(interval=1) gets a non-blocking comparison over 1 second.
        return {
            "cpu_percent": psutil.cpu_percent(interval=1),
            "memory_percent": psutil.virtual_memory().percent
        }
    except Exception as e:
        print(f"HEALTH: Could not get system usage: {e}")
        return {
            "cpu_percent": "N/A",
            "memory_percent": "N/A"
        }