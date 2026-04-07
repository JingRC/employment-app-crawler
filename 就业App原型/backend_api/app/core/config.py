from pydantic import BaseModel


class Settings(BaseModel):
    app_name: str = "Job Aggregator API"


settings = Settings()
