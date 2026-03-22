# Domain layer — pure business logic

Nothing in `domain/` imports from `adapters/`, `server.py`, or any framework. Dependencies point inward only.

## Models (models.py)

```python
@dataclass
class Memory:
    id: str
    content: str          # distilled text only
    type: str             # decision | pattern | failure | dependency | context
    repos: list[str]
    tags: list[str]
    author: str | None    # null=anonymous, hash=pseudonym, name=named
    created_at: datetime

@dataclass
class SearchResult:
    memory: Memory
    score: float          # RRF hybrid score
```

## Services (services.py)

Use cases: `search`, `get`, `update`, `list_recent`, `forget`. Memory ingestion happens outside the domain layer via the hooks → ingest.py → worker.py pipeline.

## Ports (ports.py)

```python
class StoragePort(Protocol):
    async def save(self, memory: Memory) -> str: ...
    async def get(self, id: str) -> Memory | None: ...
    async def search(self, query_text: str, query_vec: list[float], top_k: int) -> list[SearchResult]: ...
    async def delete(self, id: str) -> None: ...

class EmbeddingPort(Protocol):
    async def embed(self, text: str) -> list[float]: ...

class DistillerPort(Protocol):
    async def distill(self, raw_text: str) -> str: ...
```
