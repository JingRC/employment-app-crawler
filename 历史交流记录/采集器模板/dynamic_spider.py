from playwright.sync_api import sync_playwright

from base_spider import BaseSpider
from models import JobRecord


class DynamicSpider(BaseSpider):
    source_code = "dynamic_site"
    url = "https://example.com/careers"

    def fetch(self) -> str:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(self.url, wait_until="networkidle")
            html = page.content()
            browser.close()
        return html

    def parse(self, raw: str) -> list[dict]:
        # 实际项目中可继续接入 BeautifulSoup 或 lxml
        return []

    def normalize(self, item: dict) -> JobRecord:
        return JobRecord(
            source_code=self.source_code,
            company_name=item.get("company_name", ""),
            title=item.get("title", ""),
        )
