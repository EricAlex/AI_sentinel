# rate_limiter.py

import time
from redis import Redis
import os

# Connect to Redis using the same environment variable as Celery
redis_client = Redis.from_url(os.getenv('CELERY_BROKER_URL'))

class RateLimiter:
    """
    A simple token bucket rate limiter implemented with Redis.
    This ensures we don't exceed a certain number of actions in a given time period.
    """
    def __init__(self, key_prefix: str, limit: int, period: int):
        self.key = f"rate-limit:{key_prefix}"
        self.limit = limit
        self.period = period # in seconds

    def acquire(self):
        """
        Attempts to acquire a token.
        
        Returns:
            True if a token was acquired (action is allowed).
            False if the limit has been reached (action should be blocked).
        """
        # Use a pipeline for atomic operations
        p = redis_client.pipeline()
        
        # 1. Remove tokens that are older than our time window
        # The score is the timestamp, so we remove all members with a score
        # less than the start of the current time window.
        now = time.time()
        window_start = now - self.period
        p.zremrangebyscore(self.key, 0, window_start)
        
        # 2. Get the current number of tokens in the set (within the window)
        p.zcard(self.key)
        
        # Execute the pipeline and get the results
        # result[1] will be the current count of tokens
        results = p.execute()
        current_count = results[1]
        
        # 3. Check if we are under the limit
        if current_count < self.limit:
            # If so, add a new token with the current timestamp as its score
            p.zadd(self.key, {now: now})
            # Set an expiration on the key itself as a fallback cleanup mechanism
            p.expire(self.key, self.period)
            p.execute()
            return True
        else:
            # If we are at or over the limit, the action is denied
            return False

def wait_for_token(limiter: RateLimiter):
    """
    A blocking function that waits until a token can be acquired from the limiter.
    """
    while not limiter.acquire():
        print(f"RATE_LIMITER: Limit for '{limiter.key}' reached. Waiting 5 seconds...")
        time.sleep(5)