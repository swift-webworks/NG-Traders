"""
Small fixed-window rate limiter (per client IP) for public endpoints.

Uses Django's cache. With the default local-memory cache each Gunicorn worker counts
separately, so the effective limit is `limit x workers` - fine as basic abuse control for a
single-shop site. Use a shared cache (e.g. Redis) later if stricter limits are needed.
"""
import functools

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse


def client_ip(request):
    if getattr(settings, "TRUST_X_FORWARDED_FOR", False):
        fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def rate_limit(name, limit, window, as_json=True):
    def decorator(view):
        @functools.wraps(view)
        def wrapper(request, *args, **kwargs):
            if getattr(settings, "RATE_LIMITS_ENABLED", True):
                key = f"rl:{name}:{client_ip(request)}"
                if cache.add(key, 1, timeout=window):
                    count = 1
                else:
                    try:
                        count = cache.incr(key)
                    except ValueError:  # key expired between add and incr
                        cache.add(key, 1, timeout=window)
                        count = 1
                if count > limit:
                    if as_json:
                        return JsonResponse({"error": {
                            "en": "Too many requests. Please wait a minute and try again.",
                            "ta": "அதிக கோரிக்கைகள். ஒரு நிமிடம் காத்திருந்து மீண்டும் முயற்சிக்கவும்."}}, status=429)
                    return HttpResponse("Too many requests. Please wait a minute and try again.", status=429)
            return view(request, *args, **kwargs)
        return wrapper
    return decorator
