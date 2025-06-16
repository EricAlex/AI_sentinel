# django_settings.py

import os
from dotenv import load_dotenv

# Load environment variables to get the database URL
load_dotenv()

# This is the secret key that Django uses for cryptographic signing.
# It's not critical for our use case, but it's required.
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "a-default-secret-key-for-development")

# This list tells Django which components are active in this "project".
# We only need to add the app that provides the database-backed scheduler.
INSTALLED_APPS = [
    'django_celery_beat',
]

# Use the same database that the rest of our application uses.
# Django needs the database configuration in this specific dictionary format.
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'ai_progress',
        'USER': 'user',
        'PASSWORD': 'password',
        'HOST': os.getenv("DB_HOST_FOR_DJANGO", "postgres"), # Use an env var to be flexible
        'PORT': '5432',
    }
}

# Set the default timezone. UTC is a good practice for servers.
TIME_ZONE = 'UTC'
USE_TZ = True