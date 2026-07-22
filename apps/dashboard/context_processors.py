from django.conf import settings


def debug_flag(request):
    """Expose settings.DEBUG to all templates (the built-in `debug` processor
    only fires for INTERNAL_IPS, so it's unreliable for feature-gating)."""
    return {"debug": settings.DEBUG}
