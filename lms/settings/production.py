from .base import *  # noqa
import os

DEBUG = False
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")

# SMS Debug Mode: When True, all notifications are sent immediately (not batched)
# In production, this should be False to use normal batching
SMS_DEBUG = os.getenv("SMS_DEBUG", "false").lower() == "true"

# HTTPS. Off when running HTTP-only (no domain/cert yet) to avoid a redirect
# loop and cookies that never get sent. Set HTTPS_ENABLED=true once a domain +
# ACM cert are in place. ponytail: single env toggle, flip it when the cert lands.
HTTPS_ENABLED = env.bool("HTTPS_ENABLED", default=True)
if HTTPS_ENABLED:
    SECURE_SSL_REDIRECT = True
    # The ALB terminates TLS and forwards plain HTTP to the container, setting
    # X-Forwarded-Proto. Without this, Django treats every request as insecure
    # and SECURE_SSL_REDIRECT sends it into a redirect loop.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    # ALB health checks hit /health/ directly over HTTP (no X-Forwarded-Proto),
    # so exempt it from the redirect or the target group never sees a 200.
    SECURE_REDIRECT_EXEMPT = [r"^health/$"]
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

# Trusted origins for CSRF (POST forms like login). Comma-separated, e.g.
# "http://my-alb-123.us-east-1.elb.amazonaws.com". Required over plain HTTP.
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# S3 Static & Media Files. Credentials come from the ECS task IAM role (see
# iam.tf task_s3) via boto3's default chain — no keys in env.
AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME")
AWS_S3_REGION_NAME = env("AWS_S3_REGION_NAME", default="us-east-1")
AWS_DEFAULT_ACL = "public-read"
AWS_S3_CUSTOM_DOMAIN = f"{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com"
AWS_S3_OBJECT_PARAMETERS = {"CacheControl": "max-age=86400"}

STATICFILES_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"
STATIC_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/static/"

# Logging to CloudWatch via stdout (ECS captures it)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "apps": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
