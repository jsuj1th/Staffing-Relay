"""Thin wrapper around Telnyx for sending SMS replies."""
import logging
from django.conf import settings

logger = logging.getLogger(__name__)


def send_sms(to: str, text: str) -> bool:
    """Send an SMS via Telnyx. Returns True on success."""
    logger.debug("send_sms: to=%s", to)
    if not settings.TELNYX_API_KEY:
        logger.warning("SMS skipped: TELNYX_API_KEY not set")
        return False
    try:
        import telnyx
        telnyx.api_key = settings.TELNYX_API_KEY
        telnyx.Message.create(
            from_=settings.TELNYX_PHONE_NUMBER,
            to=to,
            text=text,
        )
        logger.info("SMS sent: to=%s msg_len=%d", to, len(text))
        return True
    except Exception as exc:
        logger.error("SMS send failed: %s", exc)
        return False
