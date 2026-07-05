"""
SQLite-backed store for the human review queue (ReviewItem / ReviewLog).

This sits alongside the existing JSON-file persistence (tracked_influencers.json,
influencer_alerts/*.json, uploads/holdings_index.json) rather than replacing it —
it's the structured, queryable home for AI outputs that need a human
approve/reject/edit decision plus an audit trail.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

_DB_PATH = Path(__file__).parent / "review.db"
engine = create_engine(f"sqlite:///{_DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
Base = declarative_base()


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


class ReviewItem(Base):
    __tablename__ = "review_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_type = Column(String, nullable=False)        # "influencer_alert" | "holdings_anomaly"
    source_ref = Column(String, nullable=False)        # influencer_id, or "{version_id}:{ticker}"
    title = Column(String, nullable=False)
    ai_summary = Column(Text, nullable=False)
    confidence = Column(String, nullable=False)         # "high" | "medium" | "low"
    ai_relevant = Column(Boolean, nullable=False, default=True)
    source_urls_json = Column(Text, nullable=False, default="[]")
    raw_payload_json = Column(Text, nullable=False, default="{}")
    status = Column(String, nullable=False, default="pending")  # pending|approved|rejected|edited
    edited_text = Column(Text, nullable=True)
    reviewer_note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)

    logs = relationship("ReviewLog", back_populates="item", cascade="all, delete-orphan",
                         order_by="ReviewLog.created_at")

    @property
    def source_urls(self) -> list:
        return json.loads(self.source_urls_json or "[]")

    @property
    def raw_payload(self) -> dict:
        return json.loads(self.raw_payload_json or "{}")

    def to_dict(self, include_logs: bool = False) -> dict:
        d = {
            "id": self.id,
            "item_type": self.item_type,
            "source_ref": self.source_ref,
            "title": self.title,
            "ai_summary": self.ai_summary,
            "confidence": self.confidence,
            "ai_relevant": self.ai_relevant,
            "source_urls": self.source_urls,
            "raw_payload": self.raw_payload,
            "status": self.status,
            "edited_text": self.edited_text,
            "reviewer_note": self.reviewer_note,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
        }
        if include_logs:
            d["logs"] = [log.to_dict() for log in self.logs]
        return d


class ReviewLog(Base):
    __tablename__ = "review_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    review_item_id = Column(Integer, ForeignKey("review_items.id"), nullable=False)
    action = Column(String, nullable=False)   # "created" | "approve" | "reject" | "edit"
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    item = relationship("ReviewItem", back_populates="logs")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "review_item_id": self.review_item_id,
            "action": self.action,
            "note": self.note,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


def init_db() -> None:
    Base.metadata.create_all(engine)


def create_review_item(*, item_type: str, source_ref: str, title: str, ai_summary: str,
                        confidence: str, ai_relevant: bool, source_urls: list,
                        raw_payload: dict) -> dict:
    with SessionLocal() as db:
        item = ReviewItem(
            item_type=item_type,
            source_ref=source_ref,
            title=title,
            ai_summary=ai_summary,
            confidence=confidence,
            ai_relevant=ai_relevant,
            source_urls_json=json.dumps(source_urls, ensure_ascii=False),
            raw_payload_json=json.dumps(raw_payload, ensure_ascii=False, default=str),
            status="pending",
        )
        db.add(item)
        db.flush()
        db.add(ReviewLog(review_item_id=item.id, action="created", note=None))
        db.commit()
        db.refresh(item)
        return item.to_dict()


def list_review_items(status: Optional[str] = None, item_type: Optional[str] = None) -> list:
    with SessionLocal() as db:
        q = db.query(ReviewItem)
        if status:
            q = q.filter(ReviewItem.status == status)
        if item_type:
            q = q.filter(ReviewItem.item_type == item_type)
        items = q.order_by(ReviewItem.created_at.desc()).all()
        return [i.to_dict() for i in items]


def get_review_item(item_id: int) -> Optional[dict]:
    with SessionLocal() as db:
        item = db.get(ReviewItem, item_id)
        return item.to_dict(include_logs=True) if item else None


def update_review_item(item_id: int, *, action: str, edited_text: Optional[str] = None,
                        note: Optional[str] = None) -> Optional[dict]:
    """action: 'approve' | 'reject' | 'edit'"""
    status_map = {"approve": "approved", "reject": "rejected", "edit": "edited"}
    if action not in status_map:
        raise ValueError(f"Unknown action: {action}")

    with SessionLocal() as db:
        item = db.get(ReviewItem, item_id)
        if not item:
            return None
        item.status = status_map[action]
        item.reviewed_at = _now()
        if note is not None:
            item.reviewer_note = note
        if action == "edit":
            item.edited_text = edited_text
        db.add(ReviewLog(review_item_id=item.id, action=action, note=note))
        db.commit()
        db.refresh(item)
        return item.to_dict(include_logs=True)


def review_stats() -> dict:
    with SessionLocal() as db:
        items = db.query(ReviewItem).all()
        stats = {"total": len(items), "by_status": {}, "by_type": {}}
        for i in items:
            stats["by_status"][i.status] = stats["by_status"].get(i.status, 0) + 1
            stats["by_type"][i.item_type] = stats["by_type"].get(i.item_type, 0) + 1
        return stats
