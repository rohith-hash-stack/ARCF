"""Authenticated identity — pure data, no auth logic.

Lives in domain/ (not infrastructure/auth.py, where it originated) so
that ExecutionContext — a domain object — can embed it without domain/
depending on infrastructure/. The actual API-key/JWT verification stays
in infrastructure/auth.py; this is just the resulting value object.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class Principal(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    auth_method: Literal["api_key", "jwt"]
