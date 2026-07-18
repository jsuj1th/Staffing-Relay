"""Thin wrapper around Telnyx for sending SMS replies."""
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

# ponytail: debug SMS guard — everyone but Sujith is test data right now.
# Empty the allowlist (or delete the guard in send_sms) when real recipients go live.
DEBUG_SMS_ALLOWLIST = {"+19793449880"}  # Sujith Julakanti


def send_sms(to: str, text: str) -> bool:
    """Send an SMS via Telnyx. Returns True on success."""
    if settings.DEBUG and to not in DEBUG_SMS_ALLOWLIST:
        logger.info("DEBUG: SMS to %s suppressed (not in debug allowlist)", to)
        return True

    print(f"DEBUG: send_sms called with to={to}")
    if not settings.TELNYX_API_KEY:
        print("DEBUG: API_KEY not set")
        logger.warning("SMS skipped: TELNYX_API_KEY not set")
        return False

    try:
        print(f"DEBUG: API_KEY={settings.TELNYX_API_KEY[:20]}...")
        print(f"DEBUG: FROM={settings.TELNYX_PHONE_NUMBER}")
        import telnyx
        client = telnyx.Client(api_key=settings.TELNYX_API_KEY)
        print(f"DEBUG: Client created, calling send...")
        response = client.messages.send(
            from_=settings.TELNYX_PHONE_NUMBER,
            to=to,
            text=text,
        )
        print(f"DEBUG: SMS sent successfully, response={response}")
        logger.info("SMS sent: to=%s msg_len=%d", to, len(text))
        return True
    except Exception as exc:
        print(f"DEBUG: Exception occurred: {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()
        logger.error("SMS send failed: %s | type=%s", exc, type(exc).__name__)
        return False
