"""Single-box production settings: one EC2 instance runs the web app, Postgres
lives on RDS (via DATABASE_URL), static files are served by WhiteNoise. No S3,
no Redis, no Celery. SMS batches are flushed by a cron job running
`manage.py send_pending_sms`. ponytail: smallest thing that runs in prod."""
from .base import *  # noqa
import os

DEBUG = False
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["*"])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# SMS_DEBUG forces immediate (unbatched) sends; keep off in prod.
SMS_DEBUG = os.getenv("SMS_DEBUG", "false").lower() == "true"

# WhiteNoise serves static straight from the app — no S3/CDN on a single box.
MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Plain HTTP for now (reached by the instance's public IP). Add a domain + TLS
# (e.g. Caddy) before real use, then turn the secure-cookie/HSTS knobs on.
# ponytail: HTTP-only until a domain lands.
