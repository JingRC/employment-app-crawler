import requests
from jsonpath_ng.ext import parse as jsonpath_parse

from base_spider import BaseSpider
from models import JobRecord


class JsonSpider(BaseSpider):
    source_code = "json_api"
    url = "https://example.com/api/jobs"

    def fetch(self) -> dict:
        response = requests.get(self.url, timeout=15)
        response.raise_for_status()
        return response.json()

    def parse(self, raw: dict) -> list[dict]:
        expr = jsonpath_parse("$.data.items[*]")
        return [match.value for match in expr.find(raw)]

    def normalize(self, item: dict) -> JobRecord:
        return JobRecord(
            source_code=self.source_code,
            company_name=str(item.get("company_name", "")),
            title=str(item.get("title", "")),
            city_name=str(item.get("city_name", "")),
            salary_text=str(item.get("salary_text", "")),
            source_url=str(item.get("source_url", "")),
            official_apply_url=str(item.get("official_apply_url", "")),
        )
