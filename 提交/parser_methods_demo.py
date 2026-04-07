import json
import re
from pathlib import Path
import sys
from typing import Any, Dict, List

from bs4 import BeautifulSoup
from lxml import etree

try:
    from jsonpath_ng.ext import parse as jsonpath_parse
except ImportError:  # pragma: no cover
    jsonpath_parse = None


DEFAULT_JSON_PATH = Path(__file__).with_name("joblist_Java_101120200.json")


def configure_stdio_encoding() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(errors="replace")
        except OSError:
            pass


def should_escape_non_ascii() -> bool:
    encoding = (getattr(sys.stdout, "encoding", "") or "").lower()
    return "utf-8" not in encoding


def parse_with_re(html: str) -> List[Dict[str, str]]:
    pattern = re.compile(
        r'<div class="job-item">\s*'
        r'<a class="job-name"[^>]*>(?P<job_name>.*?)</a>\s*'
        r'<span class="salary">(?P<salary>.*?)</span>\s*'
        r'<span class="brand">(?P<brand>.*?)</span>\s*'
        r'</div>',
        re.S,
    )
    return [m.groupdict() for m in pattern.finditer(html)]


def parse_with_xpath(html: str) -> List[Dict[str, str]]:
    tree = etree.HTML(html)
    rows = []
    nodes = tree.xpath('//div[@class="job-item"]')
    for node in nodes:
        rows.append(
            {
                "job_name": "".join(node.xpath('.//a[@class="job-name"]/text()')).strip(),
                "salary": "".join(node.xpath('.//span[@class="salary"]/text()')).strip(),
                "brand": "".join(node.xpath('.//span[@class="brand"]/text()')).strip(),
            }
        )
    return rows


def parse_with_lxml(html: str) -> List[Dict[str, str]]:
    # lxml usage demonstration separated from parse_with_xpath for report structure.
    root = etree.HTML(html)
    rows = []
    for node in root.xpath('//div[@class="job-item"]'):
        job_name = "".join(node.xpath('.//a[@class="job-name"]/text()')).strip()
        salary = "".join(node.xpath('.//span[@class="salary"]/text()')).strip()
        brand = "".join(node.xpath('.//span[@class="brand"]/text()')).strip()
        rows.append({"job_name": job_name, "salary": salary, "brand": brand})
    return rows


def parse_with_bs4(html: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for item in soup.select("div.job-item"):
        job_name_node = item.select_one("a.job-name")
        salary_node = item.select_one("span.salary")
        brand_node = item.select_one("span.brand")
        rows.append(
            {
                "job_name": job_name_node.get_text(strip=True) if job_name_node else "",
                "salary": salary_node.get_text(strip=True) if salary_node else "",
                "brand": brand_node.get_text(strip=True) if brand_node else "",
            }
        )
    return rows


def parse_with_jsonpath(data: Dict[str, Any]) -> List[Dict[str, str]]:
    if jsonpath_parse is None:
        raise RuntimeError("jsonpath-ng not installed. Please run: pip install jsonpath-ng")

    expr_job_name = jsonpath_parse("$[*].job_name")
    expr_salary = jsonpath_parse("$[*].salary")
    expr_brand = jsonpath_parse("$[*].brand")

    job_names = [m.value for m in expr_job_name.find(data)]
    salaries = [m.value for m in expr_salary.find(data)]
    brands = [m.value for m in expr_brand.find(data)]

    rows = []
    for job_name, salary, brand in zip(job_names, salaries, brands):
        rows.append({"job_name": str(job_name), "salary": str(salary), "brand": str(brand)})
    return rows


def load_jobs(json_path: Path) -> List[Dict[str, Any]]:
    if not json_path.exists():
        raise FileNotFoundError(f"Job JSON not found: {json_path}")

    data = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Job JSON must be a list")
    return [x for x in data if isinstance(x, dict)]


def build_jobs_html(jobs: List[Dict[str, Any]], limit: int = 0) -> str:
    parts = ["<html><body>"]
    if limit and limit > 0:
        source = jobs[:limit]
    else:
        source = jobs

    for item in source:
        job_name = str(item.get("job_name", "")).strip()
        salary = str(item.get("salary", "")).strip()
        brand = str(item.get("brand", "")).strip()
        parts.append(
            "<div class=\"job-item\">"
            f"<a class=\"job-name\">{job_name}</a>"
            f"<span class=\"salary\">{salary}</span>"
            f"<span class=\"brand\">{brand}</span>"
            "</div>"
        )
    parts.append("</body></html>")
    return "".join(parts)


def show_rows(tag: str, rows: List[Dict[str, str]], ensure_ascii: bool) -> None:
    print(f"[{tag}] count={len(rows)}")
    for row in rows:
        print(json.dumps(row, ensure_ascii=ensure_ascii))


def main() -> None:
    configure_stdio_encoding()
    ensure_ascii = should_escape_non_ascii()

    if ensure_ascii:
        print("[info] Non-UTF8 terminal detected. Chinese is printed as \\uXXXX escapes (not an error).")
    else:
        print("[info] UTF-8 terminal detected. Chinese will be displayed directly.")

    jobs = load_jobs(DEFAULT_JSON_PATH)
    html = build_jobs_html(jobs)

    show_rows("re", parse_with_re(html), ensure_ascii=ensure_ascii)
    show_rows("xpath", parse_with_xpath(html), ensure_ascii=ensure_ascii)
    show_rows("lxml", parse_with_lxml(html), ensure_ascii=ensure_ascii)
    show_rows("bs4", parse_with_bs4(html), ensure_ascii=ensure_ascii)

    try:
        show_rows("jsonpath", parse_with_jsonpath(jobs), ensure_ascii=ensure_ascii)
    except RuntimeError as exc:
        print(f"[jsonpath] skipped: {exc}")


if __name__ == "__main__":
    main()
