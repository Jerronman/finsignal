"""HTTP Basic Auth gate for the whole app. Not per-user accounts -- one
shared username/password for everyone you give the link to (e.g. you and
your dad). Toggled on automatically once APP_PASSWORD is set -- see
app/config.py.
"""
from __future__ import annotations

import base64
import binascii
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app import config


class BasicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not config.AUTH_ENABLED:
            return await call_next(request)

        username, password = _parse_basic_auth(request.headers.get("authorization", ""))
        if secrets.compare_digest(username, config.APP_USERNAME) and secrets.compare_digest(
            password, config.APP_PASSWORD
        ):
            return await call_next(request)

        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="FinSignal"'},
            content="Authentication required.",
        )


def _parse_basic_auth(header: str) -> tuple[str, str]:
    if not header.startswith("Basic "):
        return "", ""
    try:
        decoded = base64.b64decode(header[6:]).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return "", ""
    username, _, password = decoded.partition(":")
    return username, password
