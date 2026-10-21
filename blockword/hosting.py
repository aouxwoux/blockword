import os
from urllib.parse import urlsplit


def public_origin():
    vercel_url = os.getenv("VERCEL_URL") if os.getenv("VERCEL") else None
    value = (os.getenv("BLOCKWORD_PUBLIC_ORIGIN") or os.getenv("RENDER_EXTERNAL_URL")
             or (f"https://{vercel_url}" if vercel_url else "")).rstrip("/")
    if not value:
        return None
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment or any(c.isspace() for c in value)
            or "\\" in value):
        raise ValueError("BLOCKWORD_PUBLIC_ORIGIN must be an HTTPS origin, such as https://demo.example.com.")
    # urlsplit only validates the port when we read it.
    parsed.port
    return value


def request_origin(request):
    return request.state.public_origin


def secure_cookie(request):
    return request_origin(request).startswith("https://")
