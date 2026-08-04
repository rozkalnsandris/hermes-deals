from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class OfferPricingNormalization(Base):
    __tablename__ = "offer_pricing_normalizations"
    __table_args__ = (
        UniqueConstraint(
            "offer_candidate_id",
            name="uq_offer_pricing_normalizations_offer",
        ),
        CheckConstraint(
            "pricing_mode IN "
            "('fixed_package','variable_weight','piece',"
            "'unit_price_only','unknown')",
            name="ck_offer_pricing_normalizations_mode",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_offer_pricing_normalizations_confidence",
        ),
        CheckConstraint(
            "advertised_price_eur > 0",
            name="ck_offer_pricing_normalizations_advertised_price",
        ),
        CheckConstraint(
            "basis_quantity_value IS NULL OR basis_quantity_value > 0",
            name="ck_offer_pricing_normalizations_basis_positive",
        ),
        CheckConstraint(
            "basis_quantity_unit IS NULL OR "
            "basis_quantity_unit IN ('kg','l','piece')",
            name="ck_offer_pricing_normalizations_basis_unit",
        ),
        CheckConstraint(
            "fixed_item_quantity_value IS NULL "
            "OR fixed_item_quantity_value > 0",
            name="ck_offer_pricing_normalizations_fixed_quantity",
        ),
        CheckConstraint(
            "review_status IN ('pending','accepted','rejected')",
            name="ck_offer_pricing_normalizations_review",
        ),
        CheckConstraint(
            "review_status <> 'accepted' OR "
            "(pricing_mode <> 'unknown' "
            "AND normalized_unit_price_eur IS NOT NULL)",
            name="ck_offer_pricing_normalizations_accepted_ready",
        ),
        CheckConstraint(
            "normalized_unit_price_eur IS NULL "
            "OR normalized_unit_price_eur > 0",
            name="ck_offer_pricing_normalizations_unit_price",
        ),
        CheckConstraint(
            "pricing_mode <> 'variable_weight' OR "
            "(basis_quantity_value IS NOT NULL "
            "AND basis_quantity_unit = 'kg' "
            "AND fixed_item_quantity_value IS NULL "
            "AND fixed_item_quantity_unit IS NULL)",
            name="ck_offer_pricing_normalizations_variable_weight",
        ),
        Index(
            "ix_offer_pricing_normalizations_mode_review",
            "pricing_mode",
            "review_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    offer_candidate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("offer_candidates.id", ondelete="RESTRICT"),
        nullable=False,
    )
    normalizer_version: Mapped[str] = mapped_column(String(64))
    pricing_mode: Mapped[str] = mapped_column(String(32))
    advertised_price_eur: Mapped[Decimal] = mapped_column(
        Numeric(12, 4)
    )
    basis_quantity_value: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )
    basis_quantity_unit: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )
    normalized_unit_price_eur: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )
    fixed_item_quantity_value: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )
    fixed_item_quantity_unit: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    review_status: Mapped[str] = mapped_column(String(32))
    evidence_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class ComparisonFamily(Base):
    __tablename__ = "comparison_families"
    __table_args__ = (
        UniqueConstraint(
            "family_key",
            name="uq_comparison_families_family_key",
        ),
        CheckConstraint(
            "length(trim(family_key)) > 0",
            name="ck_comparison_families_key_nonempty",
        ),
        CheckConstraint(
            "comparison_dimension IN ('mass','volume','count')",
            name="ck_comparison_families_dimension",
        ),
        CheckConstraint(
            "basis_quantity_value > 0",
            name="ck_comparison_families_basis_positive",
        ),
        CheckConstraint(
            "(comparison_dimension = 'mass' "
            "AND basis_quantity_unit = 'g') OR "
            "(comparison_dimension = 'volume' "
            "AND basis_quantity_unit = 'ml') OR "
            "(comparison_dimension = 'count' "
            "AND basis_quantity_unit = 'count')",
            name="ck_comparison_families_basis_compatible",
        ),
        CheckConstraint(
            "status IN ('proposed','active','retired',"
            "'blocked_until_pricing_normalization')",
            name="ck_comparison_families_status",
        ),
        Index(
            "ix_comparison_families_name_variant",
            "normalized_name",
            "variant_key",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    family_key: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(Text)
    normalized_name: Mapped[str] = mapped_column(Text)
    variant_key: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    comparison_dimension: Mapped[str] = mapped_column(String(32))
    basis_quantity_value: Mapped[Decimal] = mapped_column(
        Numeric(12, 4)
    )
    basis_quantity_unit: Mapped[str] = mapped_column(String(32))
    attributes_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
    )
    status: Mapped[str] = mapped_column(String(64))
    evidence_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ComparisonFamilyMember(Base):
    __tablename__ = "comparison_family_members"
    __table_args__ = (
        UniqueConstraint(
            "comparison_family_id",
            "canonical_product_id",
            name="uq_comparison_family_members_family_product",
        ),
        CheckConstraint(
            "relation_type IN ('direct_peer','substitute')",
            name="ck_comparison_family_members_relation",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_comparison_family_members_confidence",
        ),
        CheckConstraint(
            "membership_method IN ('human_source_review','rule')",
            name="ck_comparison_family_members_method",
        ),
        CheckConstraint(
            "review_status IN ('pending','accepted','rejected')",
            name="ck_comparison_family_members_review",
        ),
        CheckConstraint(
            "(review_status = 'pending' AND decided_at IS NULL) OR "
            "(review_status IN ('accepted','rejected') "
            "AND decided_at IS NOT NULL)",
            name="ck_comparison_family_members_decision",
        ),
        Index(
            "ix_comparison_family_members_product",
            "canonical_product_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    comparison_family_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("comparison_families.id", ondelete="RESTRICT"),
        nullable=False,
    )
    canonical_product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("canonical_products.id", ondelete="RESTRICT"),
        nullable=False,
    )
    relation_type: Mapped[str] = mapped_column(String(32))
    membership_method: Mapped[str] = mapped_column(String(64))
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    review_status: Mapped[str] = mapped_column(String(32))
    evidence_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
