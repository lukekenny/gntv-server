from collections import deque
from collections.abc import Iterable
from typing import Any
from uuid import uuid4


class FakeResult:
    def __init__(
        self,
        *,
        scalar_values: Iterable[Any] = (),
        row: Any | None = None,
    ) -> None:
        self.scalar_values = list(scalar_values)
        self.row = row

    def scalars(self) -> "FakeResult":
        return self

    def all(self) -> list[Any]:
        return self.scalar_values

    def one_or_none(self) -> Any | None:
        return self.row


class FakeAsyncSession:
    def __init__(self, results: Iterable[FakeResult] = ()) -> None:
        self.added: list[Any] = []
        self.executed: list[Any] = []
        self.results = deque(results)
        self.flush_count = 0

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        self.flush_count += 1
        for instance in self.added:
            if hasattr(instance, "id") and instance.id is None:
                instance.id = uuid4()

    async def execute(self, statement: Any) -> FakeResult:
        self.executed.append(statement)
        if self.results:
            return self.results.popleft()
        return FakeResult()
