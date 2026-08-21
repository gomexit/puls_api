from pydantic import BaseModel


class AppVersionResponse(BaseModel):
    current_version: str
    min_supported_version: str
    download_url: str | None
