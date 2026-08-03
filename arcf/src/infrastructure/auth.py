"""API-key and JWT authentication for the Secure Fast Path.

Two credential schemes are accepted on every request: a static API key
(`X-API-Key` header) resolved against configured principals, or a JWT
bearer token whose `sub` claim names the principal. Neither scheme knows
about FastAPI — this module raises plain `AuthenticationError` and the
API layer (Phase 2's dependencies.py) translates that into a 401.
"""

import hmac

import jwt

from domain.principal import Principal
from shared.config import Settings
from shared.errors import AuthenticationError

__all__ = ["Authenticator", "Principal"]


class Authenticator:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def authenticate(self, api_key: str | None, bearer_token: str | None) -> Principal:
        if api_key is not None:
            return self._authenticate_api_key(api_key)
        if bearer_token is not None:
            return self._authenticate_jwt(bearer_token)
        raise AuthenticationError("Missing credentials: provide X-API-Key or a Bearer token")

    def _authenticate_api_key(self, api_key: str) -> Principal:
        for configured_key, principal_id in self._settings.api_keys.items():
            if hmac.compare_digest(configured_key, api_key):
                return Principal(id=principal_id, auth_method="api_key")
        raise AuthenticationError("Invalid API key")

    def _authenticate_jwt(self, token: str) -> Principal:
        try:
            payload = jwt.decode(
                token,
                self._settings.jwt_secret,
                algorithms=[self._settings.jwt_algorithm],
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationError(f"Invalid JWT: {exc}") from exc

        subject = payload.get("sub")
        if not isinstance(subject, str) or not subject:
            raise AuthenticationError("JWT missing 'sub' claim")
        return Principal(id=subject, auth_method="jwt")
