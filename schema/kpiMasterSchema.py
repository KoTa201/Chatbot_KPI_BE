from pydantic import BaseModel
from typing import List


class KPIMasterIngestionResponse(BaseModel):
    sheet_id: str
    sheet_name: str
    tahun: int
    total_rows: int
    ingested: int
    failed: int
    errors: List[str]
    status: str
