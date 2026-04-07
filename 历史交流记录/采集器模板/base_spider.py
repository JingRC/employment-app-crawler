from abc import ABC, abstractmethod
from typing import Any, List

from models import JobRecord


class BaseSpider(ABC):
    source_code = "base"

    @abstractmethod
    def fetch(self) -> Any:
        raise NotImplementedError

    @abstractmethod
    def parse(self, raw: Any) -> List[dict]:
        raise NotImplementedError

    @abstractmethod
    def normalize(self, item: dict) -> JobRecord:
        raise NotImplementedError

    def run(self) -> List[JobRecord]:
        raw = self.fetch()
        rows = self.parse(raw)
        return [self.normalize(item) for item in rows]
