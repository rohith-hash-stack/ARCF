import pytest
from pydantic import ValidationError

from domain.principal import Principal


def test_principal_holds_id_and_auth_method() -> None:
    principal = Principal(id="alice", auth_method="jwt")
    assert principal.id == "alice"
    assert principal.auth_method == "jwt"


def test_principal_is_frozen() -> None:
    principal = Principal(id="alice", auth_method="api_key")
    with pytest.raises(ValidationError):
        principal.id = "bob"
