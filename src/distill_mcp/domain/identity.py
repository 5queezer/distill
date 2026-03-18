"""User identity — resolved from local environment."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Identity:
    email: str | None = None
    repos: list[str] = field(default_factory=list)

    @property
    def is_anonymous(self) -> bool:
        return self.email is None


ANONYMOUS = Identity()
