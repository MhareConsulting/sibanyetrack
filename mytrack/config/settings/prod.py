from .base import *  # noqa: F401, F403

DEBUG = False
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# TLS is usually terminated at nginx; the app sees HTTP from the proxy. Without this,
# request.is_secure() is False, Origin/Referer checks disagree with the browser, and
# POST forms return 403 CSRF verification failed.
if env.bool("DJANGO_BEHIND_REVERSE_PROXY", default=True):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = env.bool("DJANGO_USE_X_FORWARDED_HOST", default=True)

# Optional explicit allowlist (scheme + host, no path). Example:
# DJANGO_CSRF_TRUSTED_ORIGINS=https://track.example.co.za
_csrf = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])
if _csrf:
    CSRF_TRUSTED_ORIGINS = _csrf

# HSTS: tell browsers to always use HTTPS for 1 year
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Prevent MIME-type sniffing
SECURE_CONTENT_TYPE_NOSNIFF = True

# Referrer header: full URL on same-origin, origin only cross-origin
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
