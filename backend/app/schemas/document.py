from pydantic import BaseModel, ConfigDict, field_validator

from app.enums import DocumentStatus


class DocumentCreate(BaseModel):
    title: str
    text: str

    @field_validator("title", "text", mode="after")
    @classmethod
    def _trim_and_require_non_blank(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("значение не может быть пустым после удаления пробелов")
        return trimmed


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: str
    title: str
    text: str
    status: DocumentStatus
