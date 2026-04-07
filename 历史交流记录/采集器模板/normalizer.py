from models import JobRecord


def normalize_text(value: str) -> str:
    return " ".join((value or "").split())


def normalize_record(record: JobRecord) -> JobRecord:
    record.company_name = normalize_text(record.company_name)
    record.title = normalize_text(record.title)
    record.city_name = normalize_text(record.city_name)
    record.salary_text = normalize_text(record.salary_text)
    record.source_url = normalize_text(record.source_url)
    record.official_apply_url = normalize_text(record.official_apply_url)
    return record
