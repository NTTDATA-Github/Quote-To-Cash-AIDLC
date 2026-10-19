"""GraphQL request context: the wired container + the authenticated tenant/roles.

`tenant_id`/`roles` come from the validated JWT (Keycloak or Entra, ADR-0023) in
production (see api/app.py).
Resolvers read the container from here; they never import infrastructure directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from strawberry.fastapi import BaseContext

if TYPE_CHECKING:
    from src.composition import Container


@dataclass
class GraphQLContext(BaseContext):
    container: Container
    tenant_id: str
    roles: tuple[str, ...]

    def require_role(self, role: str) -> None:
        if role not in self.roles:
            raise PermissionError(f"role '{role}' required")
