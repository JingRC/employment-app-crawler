"""公司名称归一化模块。

提供统一的企业名称清洗、标准化和跨来源匹配能力，
用于提升去重质量和跨来源公司归并。

核心策略：
1. 去除常见后缀（有限公司、股份有限公司、集团等）
2. 去除括号内的补充信息（注册号、英文名等）
3. 去除空格和标点
4. 统一全角/半角
5. 生成归一化键用于跨来源匹配
"""

from __future__ import annotations

import re
from typing import Any

# 常见的公司名称后缀，按长度降序排列以确保最长匹配优先
_CORPORATE_SUFFIXES = (
    "股份有限公司",
    "有限责任公司",
    "有限公司",
    "集团公司",
    "集团",
    "总公司",
    "有限公司分公司",
    "分公司",
    "公司",
    "厂",
    "中心",
    "研究院",
    "研究所",
    "学院",
    "大学",
    "医院",
    "诊所",
    "门店",
    "店",
    "工作室",
    "事务所",
)

# 括号模式 — 去除括号及其中内容
_BRACKET_PATTERN = re.compile(r"[（(][^）)]*[）)]")

# 全角转半角映射
_FULLWIDTH_MAP: dict[int, int] = {}
for _i in range(0xFF01, 0xFF5F):
    _FULLWIDTH_MAP[_i] = _i - 0xFEE0


def _fullwidth_to_halfwidth(text: str) -> str:
    return text.translate(_FULLWIDTH_MAP)


def normalize_company_name(raw_name: str) -> str:
    """清洗并归一化公司名称，返回可用于匹配的核心名称。

    示例：
        "阿里巴巴（中国）有限公司" -> "阿里巴巴"
        "腾讯科技(深圳)有限公司" -> "腾讯科技"
        "华为技术有限公司" -> "华为技术"
    """
    text = str(raw_name or "").strip()
    if not text:
        return ""

    # 全角转半角
    text = _fullwidth_to_halfwidth(text)

    # 去除括号及其中内容
    text = _BRACKET_PATTERN.sub("", text)

    # 去除多余空白和标点
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[，。；;：:,\.\-_/|]", "", text)

    # 去除常见后缀（最长匹配优先）
    for suffix in _CORPORATE_SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix):
            text = text[: -len(suffix)]
            break

    # 再次清理可能残留的标点
    text = re.sub(r"[，。；;：:,\.\-_/|]", "", text)

    return text.strip()


def normalize_company_key(raw_name: str) -> str:
    """生成归一化键，用于数据库索引和跨来源匹配。

    比 normalize_company_name 更激进：全小写 + 去空格。
    """
    normalized = normalize_company_name(raw_name)
    return normalized.lower().replace(" ", "")


def build_company_unified_key(source_code: str, company_name: str) -> str:
    """生成跨来源企业统一键，用于在多个来源间关联同一企业。"""
    normalized = normalize_company_key(company_name)
    if not normalized:
        return f"{source_code}|unknown"
    return normalized


def normalize_city_name(raw_city: str) -> str:
    """清洗城市名。"""
    text = str(raw_city or "").strip()
    if not text:
        return ""

    # 去除"市"后缀（保留直辖市）
    for municipality in ("北京", "上海", "天津", "重庆"):
        if municipality in text:
            return municipality

    # 去除省级前缀
    for marker in ("特别行政区", "自治区", "省"):
        if marker in text:
            _, tail = text.rsplit(marker, 1)
            tail = tail.strip()
            if tail:
                text = tail
                break

    # 去除"市"后缀
    if text.endswith("市") and len(text) <= 6:
        text = text[:-1]

    return text.strip()


def build_job_dedup_key(source_code: str, company_name: str, title: str, city_name: str) -> str:
    """生成跨来源职位去重键。

    优先级：
    1. 归一化后的 (公司名 + 职位名 + 城市)
    2. 保留了来源信息但降低了公司名差异的影响
    """
    normalized_company = normalize_company_key(company_name)
    normalized_title = normalize_company_key(title)
    normalized_city = normalize_city_name(city_name).lower()

    parts = [p for p in (normalized_company, normalized_title, normalized_city) if p]
    if len(parts) >= 2:
        # 至少需要公司名+职位名两个有意义的部分
        return "|".join(parts)
    # 退回到来源内去重
    return f"{source_code}|{company_name}|{title}|{city_name}"


def extract_company_aliases(company_name: str) -> list[str]:
    """从括号内提取公司别名/缩写。

    示例：
        "京东（JD.com）" -> ["JD.com"]
        "字节跳动（ByteDance）" -> ["ByteDance"]
    """
    text = str(company_name or "").strip()
    aliases: list[str] = []
    for match in re.finditer(r"[（(]([^）)]*)[）)]", text):
        alias = match.group(1).strip()
        if alias and len(alias) >= 2:
            aliases.append(alias)
    return aliases


def generate_company_search_terms(company_name: str) -> list[str]:
    """生成多个搜索用名称变体，用于模糊匹配。"""
    normalized = normalize_company_name(company_name)
    terms = [normalized]

    # 添加别名
    aliases = extract_company_aliases(company_name)
    terms.extend(aliases)

    # 如果不含"集团"，添加带"集团"的版本
    if "集团" not in normalized:
        terms.append(f"{normalized}集团")

    return list(set(t for t in terms if t))


def build_cross_source_company_index_sql() -> str:
    """返回在 jobs 表上建立公司名归一化索引的 SQL。

    用于跨来源查找同一公司的所有职位。
    """
    return """
    CREATE INDEX IF NOT EXISTS idx_jobs_normalized_company
    ON jobs(source_code, company_name)
    """


def normalize_title_key(raw_title: str) -> str:
    """归一化职位标题，去除无关修饰词。"""
    text = str(raw_title or "").strip()
    if not text:
        return ""

    # 全角转半角
    text = _fullwidth_to_halfwidth(text)

    # 去除常见修饰词
    stop_words = (
        "急聘", "高薪", "诚聘", "五险一金", "包吃住", "双休",
        "周末双休", "年终奖", "年底双薪", "待遇好", "环境好",
        "全职", "兼职", "实习",
    )
    for word in stop_words:
        text = text.replace(word, "")

    # 去括号内容
    text = _BRACKET_PATTERN.sub("", text)

    # 去空白和标点
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[，。；;：:,\.\-_/|]", "", text)

    return text.strip()


def compute_cross_source_dedup_hash(record: dict[str, Any]) -> str:
    """为职位记录计算跨来源去重哈希。

    hash(归一化公司 + 归一化标题 + 归一化城市)
    """
    import hashlib

    company = normalize_company_key(str(record.get("company_name") or ""))
    title = normalize_title_key(str(record.get("title") or ""))
    city = normalize_city_name(str(record.get("city_name") or ""))

    dedup_key = f"{company}|{title}|{city}"
    return hashlib.sha256(dedup_key.encode("utf-8")).hexdigest()[:32]
