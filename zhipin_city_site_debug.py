import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Union

import requests
import urllib3


URL = "https://www.zhipin.com/wapi/zpgeek/common/data/city/site.json"
SECRETS_FILE = Path(__file__).with_name("zhipin_secrets.json")


def configure_stdio_encoding() -> None:
    # Force UTF-8 output where supported to reduce mojibake on Windows.
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


def build_headers(local: Dict[str, str]) -> Dict[str, str]:

    cookie = os.getenv("ZHIPIN_COOKIE", local.get("cookie", "")).strip()
    zp_token = os.getenv("ZHIPIN_ZP_TOKEN", local.get("zp_token", "")).strip()
    token = os.getenv("ZHIPIN_TOKEN", local.get("token", "")).strip()

    headers: Dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://www.zhipin.com/web/geek/jobs?query=Java&city=101120200",
    }

    if cookie:
        headers["Cookie"] = cookie
    if zp_token:
        headers["zp_token"] = zp_token
    if token:
        headers["token"] = token

    return headers


def print_preview(title: str, value: str, max_len: int = 300) -> None:
    preview = value[:max_len]
    print(f"{title}: {preview}")


def parse_response(resp: requests.Response) -> Dict[str, Any]:
    response_text = resp.content.decode("utf-8", errors="replace")

    print("=" * 60)
    print(f"URL: {resp.url}")
    print(f"HTTP Status: {resp.status_code}")
    print(f"Content-Type: {resp.headers.get('Content-Type', '')}")
    print_preview("Body Preview", response_text, max_len=500)

    resp.raise_for_status()

    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Response is not valid JSON") from exc

    code = data.get("code")
    message = data.get("message")
    print(f"Business Code: {code}")
    print(f"Business Message: {message}")

    if code != 0:
        raise RuntimeError(f"Business failed: code={code}, message={message}")

    return data


def show_city_summary(data: Dict[str, Any]) -> None:
    zp_data = data.get("zpData", {})
    other_city_sites: List[Dict[str, Any]] = zp_data.get("otherCitySites", [])
    site_group: List[Dict[str, Any]] = zp_data.get("siteGroup", [])

    print("=" * 60)
    print(f"otherCitySites count: {len(other_city_sites)}")
    print(f"siteGroup count: {len(site_group)}")
    print("Top 10 cities:")

    for city in other_city_sites[:10]:
        name = city.get("name", "")
        code = city.get("code", "")
        url = city.get("url", "")
        print(f"- {name}\t{code}\t{url}")


def main() -> None:
    configure_stdio_encoding()

    local = load_local_secrets()
    headers = build_headers(local)
    verify = load_ssl_options(local)

    if verify is False:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # Do not print full secret values to avoid leaking credentials.
    print("Header keys present:")
    print(f"- Cookie: {'Cookie' in headers}")
    print(f"- zp_token: {'zp_token' in headers}")
    print(f"- token: {'token' in headers}")
    print(f"- local secrets file exists: {SECRETS_FILE.exists()}")
    print(f"- SSL verify setting: {verify}")

    with requests.Session() as session:
        resp = session.get(URL, headers=headers, timeout=15, verify=verify)
        data = parse_response(resp)
        show_city_summary(data)


if __name__ == "__main__":
    main()
