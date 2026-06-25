from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent

env = environ.Env()
env_file = BASE_DIR / ".env"
if env_file.exists():
    env.read_env(str(env_file))

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-insecure-change-me")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third-party
    "rest_framework",
    "rest_framework.authtoken",
    "django_htmx",
    "axes",
    # local
    "mytrack.tenancy.apps.TenancyConfig",
    "mytrack.vehicles.apps.VehiclesConfig",
    "mytrack.tracking.apps.TrackingConfig",
    "mytrack.drivers.apps.DriversConfig",
    "mytrack.geofences.apps.GeofencesConfig",
    "mytrack.intelligence.apps.IntelligenceConfig",
    "mytrack.compliance.apps.ComplianceConfig",
    "mytrack.notifications.apps.NotificationsConfig",
    "mytrack.fuel.apps.FuelConfig",
    "mytrack.video_telematics.apps.VideoTelematicsConfig",
    "mytrack.reporting.apps.ReportingConfig",
    "mytrack.webhooks.apps.WebhooksConfig",
    "mytrack.mobile.apps.MobileConfig",
    "django_otp",
    "django_otp.plugins.otp_totp",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "axes.middleware.AxesMiddleware",
]

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 0.25
AXES_LOCKOUT_PARAMETERS = ["ip_address", "username"]
AXES_RESET_ON_SUCCESS = True

ROOT_URLCONF = "mytrack.config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "mytrack" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "mytrack.intelligence.context_processors.alert_badge",
            ],
        },
    },
]

WSGI_APPLICATION = "mytrack.config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", default="mytrack"),
        "USER": env("POSTGRES_USER", default="mytrack"),
        "PASSWORD": env("POSTGRES_PASSWORD", default="mytrack"),
        "HOST": env("POSTGRES_HOST", default="localhost"),
        "PORT": env("POSTGRES_PORT", default="5432"),
        "CONN_MAX_AGE": 0,
    }
}

AUTH_USER_MODEL = "tenancy.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-za"
TIME_ZONE = "Africa/Johannesburg"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "static_collected"
STATICFILES_DIRS = [BASE_DIR / "mytrack" / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/accounts/login/"

# Sessions expire after 3 days of inactivity; closing the browser does not log out.
SESSION_COOKIE_AGE = 259200  # 3 days in seconds
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_SAVE_EVERY_REQUEST = True

DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "30/min",
        "user": "600/min",  # GPS pings are high-frequency
        "cron_email_jobs": "10/hour",
        "cron_flush_outbox": "200/hour",
    },
}

# Shared secret for GPS ingest (Traccar → myTrack, Flutter → myTrack)
INGEST_API_TOKEN = env("INGEST_API_TOKEN", default="dev-ingest-token")

# Fallback org slug when Traccar doesn't pass one in position attributes
TRACCAR_DEFAULT_ORG_SLUG = env("TRACCAR_DEFAULT_ORG_SLUG", default="")

# myTrack → myRoutes sync push (driver/vehicle created or updated in myTrack)
MYROUTES_SYNC_URL = env("MYROUTES_SYNC_URL", default="")
MYROUTES_SYNC_TOKEN = env("MYROUTES_SYNC_TOKEN", default="")

# Azure Communication Services
ACS_CONNECTION_STRING = env("ACS_CONNECTION_STRING", default="")
ACS_SENDER_EMAIL = env("ACS_SENDER_EMAIL", default="")

# Public-facing base URL used in delivery tracking links
SITE_URL = env("SITE_URL", default="http://localhost:8000")

# Bearer token for POST /api/cron/email-jobs/ (GitHub Actions or external scheduler). Empty = endpoint disabled.
CRON_EMAIL_TRIGGER_TOKEN = env("CRON_EMAIL_TRIGGER_TOKEN", default="")

# Public hostname or IP that GPS devices in the field reach to send data.
# This is shown in the device SMS setup instructions.
# In production set this to your server's public IP or domain (e.g. track.mycompany.co.za)
TRACCAR_PUBLIC_HOST = env("TRACCAR_PUBLIC_HOST", default="your-server-ip")

# Video telematics: optional dedicated Bearer token (falls back to INGEST_API_TOKEN when unset).
VIDEO_INGEST_TOKEN = env("VIDEO_INGEST_TOKEN", default="")

# Meta (WhatsApp Business) Cloud API — shared credentials with MyRoutes
WHATSAPP = {
    "PHONE_NUMBER_ID": env("WHATSAPP_PHONE_NUMBER_ID", default=""),
    "ACCESS_TOKEN": env("WHATSAPP_ACCESS_TOKEN", default=""),
    "APP_SECRET": env("WHATSAPP_APP_SECRET", default=""),
    "GRAPH_API_VERSION": env("WHATSAPP_GRAPH_API_VERSION", default="v25.0"),
    # Pre-approved template name — body must have 3 params: {{1}} event, {{2}} vehicle reg, {{3}} detail
    "TEMPLATE_DRIVER_ALERT": env("WHATSAPP_TEMPLATE_DRIVER_ALERT", default="driver_fleet_alert"),
}

# local — bytes under MEDIA_ROOT; s3 — presigned PUT/GET (requires boto3 + VIDEO_S3_BUCKET).
VIDEO_STORAGE_BACKEND = env("VIDEO_STORAGE_BACKEND", default="local")
VIDEO_UPLOAD_URL_EXPIRY = env.int("VIDEO_UPLOAD_URL_EXPIRY", default=3600)
VIDEO_PLAYBACK_URL_EXPIRY = env.int("VIDEO_PLAYBACK_URL_EXPIRY", default=3600)
VIDEO_UPLOAD_MAX_BYTES = env.int("VIDEO_UPLOAD_MAX_BYTES", default=524288000)

VIDEO_S3_BUCKET = env("VIDEO_S3_BUCKET", default="")
VIDEO_S3_REGION = env("VIDEO_S3_REGION", default="")
VIDEO_S3_ENDPOINT_URL = env("VIDEO_S3_ENDPOINT_URL", default="")
VIDEO_S3_ACCESS_KEY_ID = env("VIDEO_S3_ACCESS_KEY_ID", default="")
VIDEO_S3_SECRET_ACCESS_KEY = env("VIDEO_S3_SECRET_ACCESS_KEY", default="")
VIDEO_S3_RESPONSE_CONTENT_TYPE = env("VIDEO_S3_RESPONSE_CONTENT_TYPE", default="video/mp4")

# Auto-correlation: window (minutes) to search for matching Alert when a clip arrives
VIDEO_ALERT_CORRELATION_WINDOW_MINUTES = env.int("VIDEO_ALERT_CORRELATION_WINDOW_MINUTES", default=5)

# Reporting feature flag for staged rollout.
REPORTING_FEATURE_ENABLED = env.bool("REPORTING_FEATURE_ENABLED", default=True)

# Proactive clip requests: vendor API endpoint and auth token
VIDEO_CLIP_REQUEST_URL   = env("VIDEO_CLIP_REQUEST_URL",   default="")
VIDEO_CLIP_REQUEST_TOKEN = env("VIDEO_CLIP_REQUEST_TOKEN", default="")

# Seconds of footage to request before and after the alert event time
VIDEO_CLIP_PRE_EVENT_SECONDS  = env.int("VIDEO_CLIP_PRE_EVENT_SECONDS",  default=30)
VIDEO_CLIP_POST_EVENT_SECONDS = env.int("VIDEO_CLIP_POST_EVENT_SECONDS", default=30)

# Camera health: hours without a clip before a channel is marked stale
VIDEO_CAMERA_STALE_HOURS = env.int("VIDEO_CAMERA_STALE_HOURS", default=24)

# Streamax AD Plus 2.0 event push: shared secret configured on the camera's alarm-push screen.
# Set this in .env; leave blank only in local dev (all pushes accepted with a warning).
STREAMAX_WEBHOOK_TOKEN = env("STREAMAX_WEBHOOK_TOKEN", default="")

# Public base URL of this server as seen by the Streamax camera (e.g. http://20.164.200.242:8001).
# Shown in the device setup instructions so the operator knows what to enter on the camera.
STREAMAX_PUSH_BASE_URL = env("STREAMAX_PUSH_BASE_URL", default="")
