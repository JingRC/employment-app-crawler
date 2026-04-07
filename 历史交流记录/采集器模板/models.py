from dataclasses import dataclass
from typing import Optional


@dataclass
class JobRecord:
    source_code: str
    company_name: str
    title: str
    city_name: str = ""
    district_name: str = ""
    salary_text: str = ""
    degree_text: str = ""
    experience_text: str = ""
    description_text: str = ""
    source_url: str = ""
    official_apply_url: str = ""
    published_at: Optional[str] = None
