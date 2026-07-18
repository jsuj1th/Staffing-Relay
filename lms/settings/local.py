from .base import *  # noqa
import os

DEBUG = True
ALLOWED_HOSTS = ["*"]

# SMS Debug Mode: When True, all notifications are sent immediately (not batched)
# Default: False (use normal batching). Set env var SMS_DEBUG=true to enable
SMS_DEBUG = os.getenv("SMS_DEBUG", "false").lower() == "true"
