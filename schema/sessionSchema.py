from datetime import datetime
from pydantic import BaseModel, field_validator


class SessionResponse(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UpdateSessionTitleRequest(BaseModel):
    title: str

    @field_validator("title")
    @classmethod
    def title_valid(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Title tidak boleh kosong.")
        if len(v) > 255:
            raise ValueError("Title terlalu panjang, maksimal 255 karakter.")
        return v
