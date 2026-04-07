from models import JobRecord


def build_new_job_message(record: JobRecord) -> str:
    return f"发现新职位：{record.company_name} - {record.title} ({record.city_name})"


def build_job_updated_message(record: JobRecord) -> str:
    return f"职位已更新：{record.company_name} - {record.title}"
