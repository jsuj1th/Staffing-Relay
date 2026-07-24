"""Telnyx inbound webhook signature verification (ed25519)."""
import base64
import json
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, Client, override_settings
from nacl.signing import SigningKey

from apps.accounts.models import Employee
from apps.locations.models import Location
from apps.messaging.views import _verify_telnyx_signature

# A fixed ed25519 keypair for tests.
_SIGNING_KEY = SigningKey.generate()
_PUBLIC_KEY_B64 = base64.b64encode(bytes(_SIGNING_KEY.verify_key)).decode()


def _sign(payload: bytes, timestamp: str) -> str:
    signed = timestamp.encode("utf-8") + b"|" + payload
    return base64.b64encode(_SIGNING_KEY.sign(signed).signature).decode()


class SignatureUnitTests(TestCase):
    def test_valid_signature_passes(self):
        payload = b'{"hello":"world"}'
        ts = "1700000000"
        self.assertTrue(_verify_telnyx_signature(payload, _sign(payload, ts), ts, _PUBLIC_KEY_B64))

    def test_tampered_payload_fails(self):
        payload = b'{"hello":"world"}'
        ts = "1700000000"
        sig = _sign(payload, ts)
        self.assertFalse(_verify_telnyx_signature(b'{"hello":"evil"}', sig, ts, _PUBLIC_KEY_B64))

    def test_garbage_signature_fails(self):
        self.assertFalse(_verify_telnyx_signature(b"{}", "not-base64!!", "1700000000", _PUBLIC_KEY_B64))


@override_settings(TELNYX_PUBLIC_KEY=_PUBLIC_KEY_B64)
class WebhookEndpointTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()
        loc = Location.objects.create(name="L", address="a", city="c", state="TX")
        Employee.objects.create(
            name="Tester", phone="+15550009999",
            employee_type=Employee.Type.PROVIDER, location=loc,
        )
        self.body = json.dumps({
            "data": {
                "event_type": "message.received",
                "payload": {"id": "msg-abc-123", "from": {"phone_number": "+15550009999"}, "text": "HI"},
            }
        }).encode()

    def _post(self, sig, ts="1700000000"):
        return self.client.post(
            "/webhooks/telnyx/", data=self.body, content_type="application/json",
            HTTP_TELNYX_SIGNATURE_ED25519=sig, HTTP_TELNYX_TIMESTAMP=ts,
        )

    @patch("apps.messaging.leave_menu.send_sms")  # "HI" -> start_leave_menu sends a prompt
    def test_valid_signature_processes(self, _mock):
        resp = self._post(_sign(self.body, "1700000000"))
        self.assertEqual(resp.status_code, 200)

    def test_invalid_signature_rejected(self):
        resp = self._post("AAAA")
        self.assertEqual(resp.status_code, 403)

    @patch("apps.messaging.views._process_command", return_value=(None, None))
    def test_duplicate_message_id_processed_once(self, mock_proc):
        sig = _sign(self.body, "1700000000")
        self._post(sig)
        self._post(sig)  # Telnyx retry: same message id
        self.assertEqual(mock_proc.call_count, 1)
