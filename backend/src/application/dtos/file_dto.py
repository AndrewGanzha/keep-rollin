from uuid import UUID

from pydantic import BaseModel


class UploadResultDTO(BaseModel):
    file_id: UUID
    url: str
