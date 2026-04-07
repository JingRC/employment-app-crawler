"""
使用 DrissionPage (CDP) 批量采集 Boss 直聘的真实职位数据
CDP 协议比 Selenium WebDriver 更难被反爬检测
"""
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

from DrissionPage import ChromiumPage, ChromiumOptions

# ===== 配置 =====
DB_DIR = Path(__file__).parent / "就业App原型" / "backend_api" / "data"
DB_PATH = DB_DIR / "jobs.db"

QUERIES = ["Java", "Python", "前端", "测试", "C++", "产品经理"]
CITIES = {
    "101120200": "青岛",
    "101120100": "济南",
    "101010100": "北京",
    "101020100": "上海",
    "101280100": "广州",
    "101280600": "深圳",
    "101210100": "杭州",
    "101270100": "成都",
}

MAX_PAGES = 2


def configure_stdio():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except OSError:
            pass


def ensure_db():
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_job_id TEXT UNIQUE,
            title TEXT NOT NULL,
            company_name TEXT NOT NULL,
            city_name TEXT DEFAULT '',
            district_name TEXT DEFAULT '',
            salary_text TEXT DEFAULT '',
            degree_text TEXT DEFAULT '',
            experience_text TEXT DEFAULT '',
            brand_scale TEXT DEFAULT '',
            brand_stage TEXT DEFAULT '',
            job_type TEXT DEFAULT '',
            source_url TEXT DEFAULT '',
            official_apply_url TEXT DEFAULT '',
            description_text TEXT DEFAULT '',
            unique_hash TEXT UNIQUE,
            content_hash TEXT DEFAULT '',
            source_code TEXT DEFAULT '',
            first_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'active'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            notification_type TEXT NOT NULL DEFAULT 'new_job',
            title TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            related_job_id INTEGER,
            related_company_id INTEGER,
            is_read INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def parse_search_cards(page):
    """解析搜索结果页面的职位卡片 (使用 DrissionPage 元素查找)"""
    jobs = []

    # 搜索结果页的卡片 - 实际 CSS 类是 job-card-wrap (非 wrapper)
    cards = page.eles("css:.job-card-box")

    for card in cards:
        try:
            title = ""
            try:
                title = card.ele("css:.job-name").text.strip()
            except Exception:
                pass

            salary = ""
            try:
                salary = card.ele("css:.job-salary").text.strip()
            except Exception:
                pass

            city, district = "", ""
            try:
                loc_text = card.ele("css:.company-location").text.strip()
                parts = loc_text.split("·")
                city = parts[0].strip() if parts else ""
                district = parts[1].strip() if len(parts) > 1 else ""
            except Exception:
                pass

            company = ""
            try:
                company = card.ele("css:.boss-name").text.strip()
            except Exception:
                pass

            exp, degree = "", ""
            try:
                tags = card.eles("css:.tag-list li")
                for tag in tags:
                    t = tag.text.strip()
                    if any(k in t for k in ["年", "经验", "应届"]):
                        exp = t
                    elif any(k in t for k in ["本科", "硕士", "大专", "博士", "学历", "不限"]):
                        degree = t
            except Exception:
                pass

            source_url, enc_id = "", ""
            try:
                link = card.ele("css:a.job-name")
                href = link.attr("href") or ""
                if href and not href.startswith("http"):
                    href = "https://www.zhipin.com" + href
                source_url = href
                m = re.search(r"/job_detail/([^.?]+)", href)
                if m:
                    enc_id = m.group(1)
            except Exception:
                pass

            if title and company:
                jobs.append({
                    "job_name": title,
                    "salary": salary,
                    "city": city,
                    "area": district,
                    "experience": exp,
                    "degree": degree,
                    "brand": company,
                    "brand_scale": "",
                    "brand_stage": "",
                    "job_type": "",
                    "encrypt_job_id": enc_id,
                    "source_url": source_url,
                })
        except Exception as e:
            print(f"  Card parse error: {e}")
    return jobs


def parse_homepage_cards(page):
    """解析首页推荐的职位卡片"""
    jobs = []
    cards = page.eles("css:.sub-li")

    for card in cards:
        try:
            title = ""
            try:
                title = card.ele("css:.name", index=1).text.strip()
            except Exception:
                try:
                    title = card.ele("css:p.name").text.strip()
                except Exception:
                    pass

            company = ""
            # 公司名在第二个 .name 中
            try:
                names = card.eles("css:.name")
                if len(names) >= 2:
                    company = names[1].text.strip()
            except Exception:
                pass

            city, district = "", ""
            try:
                loc = card.ele("css:.job-card-location + .name")
                if loc:
                    area_text = loc.text.strip()
                    parts = area_text.split("·")
                    city = parts[0].strip() if parts else ""
                    district = parts[1].strip() if len(parts) > 1 else ""
            except Exception:
                pass

            source_url, enc_id = "", ""
            try:
                link = card.ele("css:a[href*='job_detail']")
                href = link.attr("href") or ""
                if href and not href.startswith("http"):
                    href = "https://www.zhipin.com" + href
                source_url = href
                m = re.search(r"/job_detail/([^.?]+)", href)
                if m:
                    enc_id = m.group(1)
            except Exception:
                pass

            if title and company:
                jobs.append({
                    "job_name": title,
                    "salary": "",
                    "city": city,
                    "area": district,
                    "experience": "",
                    "degree": "",
                    "brand": company,
                    "brand_scale": "",
                    "brand_stage": "",
                    "job_type": "",
                    "encrypt_job_id": enc_id,
                    "source_url": source_url,
                })
        except Exception as e:
            print(f"  Homepage card parse error: {e}")
    return jobs


def save_to_db(jobs, source_code="boss"):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    stats = {"new": 0, "updated": 0, "unchanged": 0}

    for item in jobs:
        title = item.get("job_name", "")
        company = item.get("brand", "")
        city = item.get("city", "")
        if not title or not company:
            continue

        raw_u = f"{source_code}|{company}|{title}|{city}"
        u_hash = hashlib.sha256(raw_u.encode()).hexdigest()[:32]
        raw_c = f"{title}|{item.get('salary', '')}"
        c_hash = hashlib.sha256(raw_c.encode()).hexdigest()[:32]

        existing = conn.execute(
            "SELECT id, content_hash FROM jobs WHERE unique_hash = ?", (u_hash,)
        ).fetchone()

        if existing is None:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO jobs (
                    source_job_id, title, company_name, city_name, district_name,
                    salary_text, degree_text, experience_text, brand_scale, brand_stage,
                    job_type, source_url, unique_hash, content_hash, source_code, status
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'active')""",
                (
                    item.get("encrypt_job_id", ""), title, company, city,
                    item.get("area", ""), item.get("salary", ""),
                    item.get("degree", ""), item.get("experience", ""),
                    item.get("brand_scale", ""), item.get("brand_stage", ""),
                    item.get("job_type", ""), item.get("source_url", ""),
                    u_hash, c_hash, source_code,
                ),
            )
            if cursor.rowcount > 0:
                stats["new"] += 1
                conn.execute(
                    "INSERT INTO notifications (notification_type,title,content,related_job_id) VALUES ('new_job',?,?,?)",
                    ("新职位发现", f"{company} 发布了 {title}（{city}）", cursor.lastrowid),
                )
        elif existing["content_hash"] != c_hash:
            conn.execute(
                """UPDATE jobs SET salary_text=?, degree_text=?, experience_text=?,
                   brand_scale=?, brand_stage=?, content_hash=?, last_seen_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (item.get("salary", ""), item.get("degree", ""), item.get("experience", ""),
                 item.get("brand_scale", ""), item.get("brand_stage", ""), c_hash, existing["id"]),
            )
            stats["updated"] += 1
        else:
            conn.execute("UPDATE jobs SET last_seen_at=CURRENT_TIMESTAMP WHERE id=?", (existing["id"],))
            stats["unchanged"] += 1

    conn.commit()
    conn.close()
    return stats


def main():
    configure_stdio()
    ensure_db()

    queries = os.getenv("BATCH_QUERIES", ",".join(QUERIES)).split(",")
    city_keys = os.getenv("BATCH_CITIES", ",".join(CITIES.keys())).split(",")
    city_items = [(k.strip(), CITIES.get(k.strip(), k.strip())) for k in city_keys if k.strip() in CITIES]
    max_pages = int(os.getenv("BATCH_MAX_PAGES", str(MAX_PAGES)))

    # 配置 ChromiumOptions
    co = ChromiumOptions()
    # 不使用无头模式（会被反爬检测），使用最小化窗口代替
    co.set_argument("--no-sandbox")
    co.set_argument("--disable-blink-features=AutomationControlled")
    co.set_argument("--no-proxy-server")  # 直连
    co.set_argument("--disable-gpu")
    co.set_argument("--window-size=1200,800")

    print("Starting Chrome (anti-detect)...")
    page = ChromiumPage(co)

    total_new = 0
    total_fetched = 0

    try:
        for query in queries:
            query = query.strip()
            for city_code, city_name in city_items:
                print(f"\n{'='*60}")
                print(f"采集: {query} - {city_name}")

                all_jobs = []
                for pg in range(1, max_pages + 1):
                    url = f"https://www.zhipin.com/web/geek/job?query={query}&city={city_code}&page={pg}"
                    print(f"  Page {pg}: loading...")

                    try:
                        page.get(url)
                    except Exception as e:
                        print(f"  Load error: {e}")
                        break

                    # 等待加载 - SPA 需要更多时间渲染
                    time.sleep(6)

                    # 尝试等待职位卡片元素出现
                    try:
                        page.wait.ele_displayed("css:.job-card-wrapper", timeout=10)
                    except Exception:
                        pass

                    cur_url = page.url
                    cur_title = page.title

                    # 检查是否被重定向
                    if "/web/geek/job" not in cur_url:
                        print(f"  Redirected to: {cur_url}")
                        # 如果在首页，尝试解析首页推荐
                        if pg == 1:
                            hp_jobs = parse_homepage_cards(page)
                            if hp_jobs:
                                print(f"  Found {len(hp_jobs)} homepage recommended jobs")
                                all_jobs.extend(hp_jobs)
                        break

                    # 正常搜索页面
                    page_jobs = parse_search_cards(page)
                    if not page_jobs:
                        # 保存调试
                        debug_path = Path(__file__).parent / "_dp_debug.html"
                        debug_path.write_text(page.html, encoding="utf-8")
                        print(f"  No data on page {pg} (title: {cur_title})")
                        break

                    all_jobs.extend(page_jobs)
                    print(f"  Got {len(page_jobs)} jobs (total: {len(all_jobs)})")

                    time.sleep(3 + pg)

                if all_jobs:
                    stats = save_to_db(all_jobs)
                    total_new += stats["new"]
                    total_fetched += len(all_jobs)
                    print(f"  DB: new={stats['new']}, updated={stats['updated']}, unchanged={stats['unchanged']}")

                time.sleep(2)

    finally:
        page.quit()

    print(f"\n{'='*60}")
    print(f"采集完成! 获取 {total_fetched} 条, 新增 {total_new} 条")

    conn = sqlite3.connect(DB_PATH)
    total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    companies = conn.execute("SELECT COUNT(DISTINCT company_name) FROM jobs").fetchone()[0]
    cities_list = [r[0] for r in conn.execute("SELECT DISTINCT city_name FROM jobs").fetchall() if r[0]]
    conn.close()
    print(f"数据库: {total} 职位, {companies} 企业, {len(cities_list)} 城市")
    print(f"城市: {', '.join(cities_list)}")


if __name__ == "__main__":
    main()
