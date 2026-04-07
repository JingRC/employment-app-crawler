import hashlib

from models import JobRecord


def build_unique_hash(record: JobRecord) -> str:
    raw = "|".join(
        [
            record.source_code,
            record.company_name,
            record.title,
            record.city_name,
            record.source_url,
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_content_hash(record: JobRecord) -> str:
    raw = "|".join(
        [
            record.title,
            record.salary_text,
            record.degree_text,
            record.experience_text,
            record.description_text,
            record.official_apply_url,
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
