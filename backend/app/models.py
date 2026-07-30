from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SourceSnapshot(Base):
    __tablename__ = "source_snapshots"
    __table_args__ = (
        Index(
            "ix_source_snapshots_chain_collected",
            "source_chain",
            "collected_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_chain: Mapped[str] = mapped_column(String(32))
    source_url: Mapped[str] = mapped_column(Text)
    final_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope: Mapped[str | None] = mapped_column(String(64), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    snapshot_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    keyword_hits: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    json_ld_blocks: Mapped[int] = mapped_column(Integer, default=0)
    strategy_hint: Mapped[str] = mapped_column(String(64))
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class OfferCandidateRecord(Base):
    __tablename__ = "offer_candidates"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id",
            "source_offer_id",
            name="uq_offer_candidates_snapshot_offer",
        ),
        Index(
            "ix_offer_candidates_chain_valid",
            "source_chain",
            "valid_from",
            "valid_until",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_chain: Mapped[str] = mapped_column(String(32))
    source_store_external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_store_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_offer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    product_name_raw: Mapped[str] = mapped_column(Text)
    brand_raw: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    package_text_raw: Mapped[str | None] = mapped_column(String(255), nullable=True)
    price_eur: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    regular_price_eur: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    unit_price_eur: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    unit_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pricing_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    regular_unit_price_eur: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    example_weight_g: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    discount_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    app_price_eur: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    requires_app: Mapped[bool] = mapped_column(Boolean, default=False)
    coupon_required: Mapped[bool] = mapped_column(Boolean, default=False)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    app_valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    app_valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_url: Mapped[str] = mapped_column(Text)
    source_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("source_snapshots.id", ondelete="RESTRICT"))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    parser_version: Mapped[str] = mapped_column(String(32))
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class OfferNormalization(Base):
    __tablename__ = "offer_normalizations"
    __table_args__ = (
        UniqueConstraint(
            "offer_candidate_id",
            "normalizer_version",
            name="uq_offer_normalizations_offer_version",
        ),
        UniqueConstraint(
            "offer_candidate_id",
            "id",
            name="uq_offer_normalizations_offer_id_pair",
        ),
        CheckConstraint(
            "length(trim(normalized_name)) > 0",
            name="ck_offer_normalizations_name_nonempty",
        ),
        CheckConstraint(
            "item_quantity_value IS NULL OR item_quantity_value > 0",
            name="ck_offer_normalizations_quantity_positive",
        ),
        CheckConstraint(
            "pack_count IS NULL OR pack_count > 0",
            name="ck_offer_normalizations_pack_count_positive",
        ),
        CheckConstraint(
            "gtin14 IS NULL OR length(gtin14) = 14",
            name="ck_offer_normalizations_gtin14_length",
        ),
        Index("ix_offer_normalizations_normalized_name", "normalized_name"),
        Index("ix_offer_normalizations_normalized_brand", "normalized_brand"),
        Index("ix_offer_normalizations_gtin14", "gtin14"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    offer_candidate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("offer_candidates.id", ondelete="RESTRICT"),
        nullable=False,
    )
    normalizer_version: Mapped[str] = mapped_column(String(64))
    normalized_name: Mapped[str] = mapped_column(Text)
    normalized_brand: Mapped[str | None] = mapped_column(String(255), nullable=True)
    item_quantity_value: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )
    item_quantity_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pack_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gtin14: Mapped[str | None] = mapped_column(String(14), nullable=True)
    category_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class CanonicalProduct(Base):
    __tablename__ = "canonical_products"
    __table_args__ = (
        UniqueConstraint("gtin14", name="uq_canonical_products_gtin14"),
        CheckConstraint(
            "length(trim(display_name)) > 0",
            name="ck_canonical_products_display_name_nonempty",
        ),
        CheckConstraint(
            "length(trim(normalized_name)) > 0",
            name="ck_canonical_products_normalized_name_nonempty",
        ),
        CheckConstraint(
            "item_quantity_value IS NULL OR item_quantity_value > 0",
            name="ck_canonical_products_quantity_positive",
        ),
        CheckConstraint(
            "pack_count IS NULL OR pack_count > 0",
            name="ck_canonical_products_pack_count_positive",
        ),
        CheckConstraint(
            "gtin14 IS NULL OR length(gtin14) = 14",
            name="ck_canonical_products_gtin14_length",
        ),
        Index("ix_canonical_products_normalized_name", "normalized_name"),
        Index(
            "ix_canonical_products_name_brand",
            "normalized_name",
            "brand_normalized",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    display_name: Mapped[str] = mapped_column(Text)
    normalized_name: Mapped[str] = mapped_column(Text)
    brand_display: Mapped[str | None] = mapped_column(String(255), nullable=True)
    brand_normalized: Mapped[str | None] = mapped_column(String(255), nullable=True)
    item_quantity_value: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )
    item_quantity_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pack_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gtin14: Mapped[str | None] = mapped_column(String(14), nullable=True)
    category_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ProductMatchCandidate(Base):
    __tablename__ = "product_match_candidates"
    __table_args__ = (
        ForeignKeyConstraint(
            ["offer_candidate_id", "offer_normalization_id"],
            [
                "offer_normalizations.offer_candidate_id",
                "offer_normalizations.id",
            ],
            name="fk_match_candidates_offer_normalization",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "offer_normalization_id",
            "canonical_product_id",
            "matcher_version",
            name="uq_match_candidates_normalization_product_matcher",
        ),
        UniqueConstraint(
            "offer_candidate_id",
            "canonical_product_id",
            "id",
            name="uq_match_candidates_offer_product_id",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_match_candidates_confidence",
        ),
        CheckConstraint(
            "review_status IN ('pending', 'accepted', 'rejected')",
            name="ck_match_candidates_review_status",
        ),
        CheckConstraint(
            "(review_status = 'pending' AND decided_at IS NULL) "
            "OR (review_status IN ('accepted', 'rejected') AND decided_at IS NOT NULL)",
            name="ck_match_candidates_decision_timestamp",
        ),
        Index("ix_match_candidates_offer", "offer_candidate_id"),
        Index("ix_match_candidates_product", "canonical_product_id"),
        Index("ix_match_candidates_review_status", "review_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    offer_candidate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("offer_candidates.id", ondelete="RESTRICT"),
        nullable=False,
    )
    offer_normalization_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    canonical_product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("canonical_products.id", ondelete="RESTRICT"),
        nullable=False,
    )
    matcher_version: Mapped[str] = mapped_column(String(64))
    match_method: Mapped[str] = mapped_column(String(64))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    review_status: Mapped[str] = mapped_column(String(32), default="pending")
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class OfferProductLink(Base):
    __tablename__ = "offer_product_links"
    __table_args__ = (
        UniqueConstraint(
            "offer_candidate_id",
            name="uq_offer_product_links_offer_candidate",
        ),
        ForeignKeyConstraint(
            [
                "offer_candidate_id",
                "canonical_product_id",
                "source_match_candidate_id",
            ],
            [
                "product_match_candidates.offer_candidate_id",
                "product_match_candidates.canonical_product_id",
                "product_match_candidates.id",
            ],
            name="fk_offer_links_source_match_candidate",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_offer_product_links_confidence",
        ),
        Index(
            "ix_offer_product_links_canonical_product",
            "canonical_product_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    offer_candidate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("offer_candidates.id", ondelete="RESTRICT"),
        nullable=False,
    )
    canonical_product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("canonical_products.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_match_candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
    )
    link_method: Mapped[str] = mapped_column(String(64))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )




class OfferReviewItem(Base):
    """Mutable human decision layered over immutable source/parser evidence."""

    __tablename__ = "offer_review_items"
    __table_args__ = (
        UniqueConstraint(
            "source_chain",
            "source_flyer_key",
            "source_row_key",
            name="uq_offer_review_items_source_row",
        ),
        CheckConstraint(
            "status IN ('pending','draft','needs_followup','approved','rejected')",
            name="ck_offer_review_items_status",
        ),
        CheckConstraint(
            "page_number IS NULL OR page_number > 0",
            name="ck_offer_review_items_page_positive",
        ),
        CheckConstraint(
            "(status = 'approved' AND published_offer_candidate_id IS NOT NULL AND decided_at IS NOT NULL) "
            "OR (status = 'rejected' AND published_offer_candidate_id IS NULL AND decided_at IS NOT NULL) "
            "OR (status IN ('pending','draft','needs_followup') "
            "AND published_offer_candidate_id IS NULL AND decided_at IS NULL)",
            name="ck_offer_review_items_decision_state",
        ),
        Index("ix_offer_review_items_status", "status"),
        Index("ix_offer_review_items_source_chain", "source_chain"),
        Index("ix_offer_review_items_flyer_page", "source_flyer_key", "page_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_chain: Mapped[str] = mapped_column(String(32), nullable=False)
    source_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("source_snapshots.id", ondelete="RESTRICT"),
        nullable=True,
    )
    source_flyer_key: Mapped[str] = mapped_column(String(255), nullable=False)
    source_row_key: Mapped[str] = mapped_column(String(255), nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    original_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    corrected_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_offer_candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("offer_candidates.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class OfferReviewRevision(Base):
    """Append-only audit trail for Review Queue actions."""

    __tablename__ = "offer_review_revisions"
    __table_args__ = (
        UniqueConstraint(
            "review_item_id",
            "revision_no",
            name="uq_offer_review_revisions_item_revision",
        ),
        CheckConstraint(
            "revision_no > 0",
            name="ck_offer_review_revisions_revision_positive",
        ),
        CheckConstraint(
            "action IN ('seed','draft','needs_followup','approve','reject','reopen')",
            name="ck_offer_review_revisions_action",
        ),
        Index("ix_offer_review_revisions_item", "review_item_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    review_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("offer_review_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
