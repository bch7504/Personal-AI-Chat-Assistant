from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime


@dataclass
class ComponentHealth:
    ready: bool
    detail: str
    checked_at: str


class ComponentHealthRegistry:
    def __init__(self) -> None:
        self._components: dict[str, ComponentHealth] = {}

    def set(self, name: str, *, ready: bool, detail: str) -> None:
        self._components[name] = ComponentHealth(
            ready=ready,
            detail=detail,
            checked_at=datetime.now(UTC).isoformat(),
        )

    def get(self, name: str) -> ComponentHealth | None:
        return self._components.get(name)

    def snapshot(self) -> dict[str, dict]:
        return {name: asdict(value) for name, value in sorted(self._components.items())}


component_health = ComponentHealthRegistry()
