from .dev import *

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Strip whitenoise — not installed in all local environments
MIDDLEWARE = [m for m in MIDDLEWARE if "whitenoise" not in m.lower()]

# Disable Axes brute-force protection — it requires a request object
# which Django's test client.login() doesn't provide
AXES_ENABLED = False
AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]

# Fixed token so webhook tests that send "Bearer dev-ingest-token" pass auth
INGEST_API_TOKEN = "dev-ingest-token"
