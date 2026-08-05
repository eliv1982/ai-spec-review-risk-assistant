from typing import Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Document


class DocumentRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, *, title: str, text: str) -> Document:
        document = Document(title=title, text=text)
        self.db.add(document)
        return document

    def get_by_id(self, document_id: str) -> Optional[Document]:
        return self.db.get(Document, document_id)

    def list(
        self, *, status: Optional[str], limit: int, offset: int
    ) -> tuple[Sequence[Document], int]:
        filters = []
        if status is not None:
            filters.append(Document.status == status)

        total = self.db.scalar(select(func.count()).select_from(Document).where(*filters)) or 0

        stmt = (
            select(Document)
            .where(*filters)
            .order_by(Document.created_at.desc(), Document.id.desc())
            .limit(limit)
            .offset(offset)
        )
        items = self.db.scalars(stmt).all()
        return items, total
