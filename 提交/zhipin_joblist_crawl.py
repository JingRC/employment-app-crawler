import csv
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import requests
import urllib3


SECRETS_FILE = Path(__file__).with_name("zhipin_secrets.json")
API_URL = "https://www.zhipin.com/wapi/zpgeek/search/joblist.json"
DEFAULT_OUTPUT_DIR = Path(r"D:\file\python网络爬虫\实验三\代码\提交")


def configure_stdio_encoding() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except OSError:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except OSError:
            pass


def load_local_secrets() -> Dict[str, str]:
    if not SECRETS_FILE.exists():
        return {}

    try:
        data = json.loads(SECRETS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(data, dict):
        return {}

    result: Dict[str, str] = {}
    for key in ("cookie", "zp_token", "token", "verify_ssl", "ca_bundle"):
        value = data.get(key, "")
        if isinstance(value, str):
            result[key] = value.strip()
    return result


def load_ssl_options(local: Dict[str, str]) -> Union[bool, str]:
    verify_ssl_raw = os.getenv("ZHIPIN_VERIFY_SSL", local.get("verify_ssl", "true")).strip().lower()
    ca_bundle = os.getenv("ZHIPIN_CA_BUNDLE", local.get("ca_bundle", "")).strip()

    if ca_bundle:
        return ca_bundle
    return verify_ssl_raw not in {"0", "false", "no", "off"}


def build_headers(local: Dict[str, str], query: str, city: str) -> Dict[str, str]:
    cookie = os.getenv("ZHIPIN_COOKIE", local.get("cookie", "")).strip()
    zp_token = os.getenv("ZHIPIN_ZP_TOKEN", local.get("zp_token", "")).strip()
    token = os.getenv("ZHIPIN_TOKEN", local.get("token", "")).strip()

    headers: Dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"https://www.zhipin.com/web/geek/jobs?query={query}&city={city}",
    }

    if cookie:
        headers["Cookie"] = cookie
    if zp_token:
        headers["zp_token"] = zp_token
    if token:
        headers["token"] = token

    return headers


def find_job_list(node: Any) -> Optional[List[Dict[str, Any]]]:
    if isinstance(node, dict):
        for key in ("jobList", "list", "jobs"):
            value = node.get(key)
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return value

        for value in node.values():
            result = find_job_list(value)
            if result:
                return result

    if isinstance(node, list):
        if node and isinstance(node[0], dict) and (
            "jobName" in node[0] or "salaryDesc" in node[0] or "jobId" in node[0]
        ):
            return node
        for value in node:
            result = find_job_list(value)
            if result:
                return result

    return None


def pick_text(item: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value is None:
            continue
        if isinstance(value, (str, int, float)):
            return str(value)
    return ""


def normalize_job(item: Dict[str, Any]) -> Dict[str, str]:
    brand = item.get("brandName")
    if not brand and isinstance(item.get("brand"), dict):
        brand = pick_text(item["brand"], "brandName", "name")

    city = item.get("cityName")
    if not city and isinstance(item.get("city"), dict):
        city = pick_text(item["city"], "name", "cityName")

    area = item.get("areaDistrict")
    if not area and isinstance(item.get("areaDistrict"), dict):
        area = pick_text(item["areaDistrict"], "name")

    return {
        "job_name": pick_text(item, "jobName", "title", "positionName"),
        "salary": pick_text(item, "salaryDesc", "salary"),
        "city": str(city or ""),
        "area": str(area or ""),
        "experience": pick_text(item, "jobExperience", "experienceName"),
        "degree": pick_text(item, "jobDegree", "degreeName"),
        "brand": str(brand or ""),
        "brand_scale": pick_text(item, "brandScaleName", "brandScale"),
        "brand_stage": pick_text(item, "brandStageName", "brandStage"),
        "job_type": pick_text(item, "jobType", "jobTypeDesc"),
        "encrypt_job_id": pick_text(item, "encryptJobId", "securityId", "jobId"),
    }


def fetch_one_page(
    session: requests.Session,
    headers: Dict[str, str],
    city: str,
    query: str,
    page: int,
    page_size: int,
    verify: Union[bool, str],
) -> Dict[str, Any]:
    params = {
        "scene": "1",
        "query": query,
        "city": city,
        "page": str(page),
        "pageSize": str(page_size),
        "_": str(int(time.time() * 1000)),
    }

    response = session.get(API_URL, headers=headers, params=params, timeout=20, verify=verify)
    response.raise_for_status()

    text = response.content.decode("utf-8", errors="replace")
    data = json.loads(text)
    return data


def crawl_jobs(query: str, city: str, max_pages: int = 3, page_size: int = 30) -> List[Dict[str, str]]:
    local = load_local_secrets()
    headers = build_headers(local, query, city)
    verify = load_ssl_options(local)

    if verify is False:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    print("Header keys present:")
    print(f"- Cookie: {'Cookie' in headers}")
    print(f"- zp_token: {'zp_token' in headers}")
    print(f"- token: {'token' in headers}")
    print(f"- SSL verify setting: {verify}")

    results: List[Dict[str, str]] = []

    with requests.Session() as session:
        for page in range(1, max_pages + 1):
            data = fetch_one_page(session, headers, city, query, page, page_size, verify)
            code = data.get("code")
            message = data.get("message")
            print(f"Page {page}: code={code}, message={message}")

            if code != 0:
                if str(code) == "37":
                    print("Stop reason: risk control triggered (code=37, environment abnormal).")
                else:
                    print(f"Stop on page {page}: business failed")
                break

            job_list_raw = find_job_list(data) or []
            page_jobs = [normalize_job(x) for x in job_list_raw if isinstance(x, dict)]

            if not page_jobs:
                print(f"Page {page}: no job data found, stop.")
                break

            results.extend(page_jobs)
            print(f"Page {page}: +{len(page_jobs)} jobs, total={len(results)}")

            time.sleep(0.8)

    return results


def save_results(base_dir: Path, query: str, city: str, jobs: List[Dict[str, str]]) -> None:
    base_dir.mkdir(parents=True, exist_ok=True)

    base_name = f"joblist_{query}_{city}".replace(" ", "_")
    json_path = base_dir / f"{base_name}.json"
    csv_path = base_dir / f"{base_name}.csv"

    json_path.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")

    fieldnames = [
        "job_name",
        "salary",
        "city",
        "area",
        "experience",
        "degree",
        "brand",
        "brand_scale",
        "brand_stage",
        "job_type",
        "encrypt_job_id",
    ]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(jobs)

    print("=" * 60)
    print(f"Saved JSON: {json_path}")
    print(f"Saved CSV : {csv_path}")


def main() -> None:
    configure_stdio_encoding()

    query = os.getenv("ZHIPIN_QUERY", "Java")
    city = os.getenv("ZHIPIN_CITY", "101120200")
    max_pages = int(os.getenv("ZHIPIN_MAX_PAGES", "3"))
    page_size = int(os.getenv("ZHIPIN_PAGE_SIZE", "30"))

    print(f"Start crawl: query={query}, city={city}, max_pages={max_pages}, page_size={page_size}")

    output_dir = Path(os.getenv("ZHIPIN_OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR)))

    jobs = crawl_jobs(query=query, city=city, max_pages=max_pages, page_size=page_size)
    print(f"Crawl done, total jobs={len(jobs)}")

    if jobs:
        save_results(output_dir, query, city, jobs)
        print("Sample rows:")
        for row in jobs[:5]:
            print(f"- {row['job_name']} | {row['salary']} | {row['brand']}")


if __name__ == "__main__":
    main()
