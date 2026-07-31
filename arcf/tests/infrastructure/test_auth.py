import jwt
import pytest

from infrastructure.auth import Authenticator
from shared.config import Settings
from shared.errors import AuthenticationError


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "api_keys_raw": "secret123:alice,secret456:bob",
        "jwt_secret": "test-jwt-secret",
        "jwt_algorithm": "HS256",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def test_valid_api_key_resolves_principal() -> None:
    auth = Authenticator(_settings())
    principal = auth.authenticate(api_key="secret123", bearer_token=None)
    assert principal.id == "alice"
    assert principal.auth_method == "api_key"


def test_unknown_api_key_rejected() -> None:
    auth = Authenticator(_settings())
    with pytest.raises(AuthenticationError):
        auth.authenticate(api_key="not-a-real-key", bearer_token=None)


def test_valid_jwt_resolves_principal() -> None:
    settings = _settings()
    token = jwt.encode({"sub": "carol"}, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    auth = Authenticator(settings)
    principal = auth.authenticate(api_key=None, bearer_token=token)
    assert principal.id == "carol"
    assert principal.auth_method == "jwt"


def test_jwt_with_wrong_secret_rejected() -> None:
    settings = _settings()
    token = jwt.encode({"sub": "carol"}, "wrong-secret", algorithm=settings.jwt_algorithm)
    auth = Authenticator(settings)
    with pytest.raises(AuthenticationError):
        auth.authenticate(api_key=None, bearer_token=token)


def test_jwt_missing_sub_claim_rejected() -> None:
    settings = _settings()
    token = jwt.encode({"role": "admin"}, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    auth = Authenticator(settings)
    with pytest.raises(AuthenticationError):
        auth.authenticate(api_key=None, bearer_token=token)


def test_no_credentials_rejected() -> None:
    auth = Authenticator(_settings())
    with pytest.raises(AuthenticationError):
        auth.authenticate(api_key=None, bearer_token=None)
