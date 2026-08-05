import uuid
from typing import Any, Optional

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.enums import DocumentStatus
from app.utils.json_type import JSONText
from app.utils.time import utc_now_iso


def _new_uuid() -> str:
    return str(uuid.uuid4())


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_new_uuid)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=utc_now_iso)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default=DocumentStatus.created.value)

    reviews: Mapped[list["Review"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint("status IN ('created', 'reviewed', 'review_failed')", name="ck_documents_status"),
        Index("ix_documents_status", "status"),
        Index("ix_documents_created_at", "created_at"),
    )


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_new_uuid)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=utc_now_iso)
    document_id: Mapped[str] = mapped_column(
        Text, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    review_json: Mapped[dict[str, Any]] = mapped_column(JSONText, nullable=False)
    confidence: Mapped[str] = mapped_column(Text, nullable=False)
    readiness: Mapped[str] = mapped_column(Text, nullable=False)
    needs_review: Mapped[int] = mapped_column(Integer, nullable=False)
    reason_codes_json: Mapped[list[str]] = mapped_column(JSONText, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    document: Mapped["Document"] = relationship(back_populates="reviews")

    __table_args__ = (
        CheckConstraint("confidence IN ('high', 'medium', 'low')", name="ck_reviews_confidence"),
        CheckConstraint(
            "readiness IN ('ready', 'needs_clarification', 'not_ready')", name="ck_reviews_readiness"
        ),
        CheckConstraint("needs_review IN (0, 1)", name="ck_reviews_needs_review"),
        Index("ix_reviews_document_id", "document_id"),
        Index("ix_reviews_needs_review", "needs_review"),
        Index("ix_reviews_confidence", "confidence"),
        Index("ix_reviews_readiness", "readiness"),
        Index("ix_reviews_created_at", "created_at"),
    )


class AuditRun(Base):
    __tablename__ = "audit_runs"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_new_uuid)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=utc_now_iso)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    entity_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    input_json: Mapped[Optional[Any]] = mapped_column(JSONText, nullable=True)
    output_json: Mapped[Optional[Any]] = mapped_column(JSONText, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        CheckConstraint("status IN ('success', 'needs_review', 'error')", name="ck_audit_runs_status"),
        CheckConstraint("duration_ms >= 0", name="ck_audit_runs_duration_ms"),
        Index("ix_audit_runs_status", "status"),
        Index("ix_audit_runs_action", "action"),
        Index("ix_audit_runs_created_at", "created_at"),
        Index("ix_audit_runs_entity", "entity_type", "entity_id"),
    )
