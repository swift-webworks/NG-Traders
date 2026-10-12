import json

from django.http import JsonResponse

MAX_BODY_BYTES = 64 * 1024


class BadRequest(Exception):
    pass


def json_body(request):
    """Parse a small JSON object body, or raise BadRequest."""
    if len(request.body) > MAX_BODY_BYTES:
        raise BadRequest("Request too large")
    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        raise BadRequest("Invalid JSON")
    if not isinstance(data, dict):
        raise BadRequest("Invalid JSON")
    return data


def bad_request(message_en="Something was wrong with that request.", message_ta="கோரிக்கையில் தவறு உள்ளது.", status=400):
    return JsonResponse({"error": {"en": message_en, "ta": message_ta}}, status=status)
