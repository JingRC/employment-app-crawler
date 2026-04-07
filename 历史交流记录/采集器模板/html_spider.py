import requests
from bs4 import BeautifulSoup

from base_spider import BaseSpider
from models import JobRecord


class HtmlSpider(BaseSpider):
    source_code = "html_site"
    url = "https://example.com/jobs"

    def fetch(self) -> str:
        response = requests.get(self.url, timeout=15)
        response.raise_for_status()
        return response.text

    def parse(self, raw: str) -> list[dict]:
        soup = BeautifulSoup(raw, "lxml")
        rows = []
        for item in soup.select("div.job-item"):
            rows.append(
                {
                    "title": item.select_one(".job-title").get_text(strip=True) if item.select_one(".job-title") else "",
                    "company_name": item.select_one(".company-name").get_text(strip=True) if item.select_one(".company-name") else "",
                    "city_name": item.select_one(".city-name").get_text(strip=True) if item.select_one(".city-name") else "",
                    "source_url": item.select_one("a")['href'] if item.select_one("a") else "",
                }
            )
        return rows

    def normalize(self, item: dict) -> JobRecord:
        return JobRecord(
            source_code=self.source_code,
            company_name=item.get("company_name", ""),
            title=item.get("title", ""),
            city_name=item.get("city_name", ""),
            source_url=item.get("source_url", ""),
        )
