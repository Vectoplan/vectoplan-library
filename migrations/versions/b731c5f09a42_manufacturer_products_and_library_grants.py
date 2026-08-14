"""manufacturer products, distribution coverage and library grants

Revision ID: b731c5f09a42
Revises: 3d4a936a7185
Create Date: 2026-08-12
"""

from alembic import op
import sqlalchemy as sa


revision = "b731c5f09a42"
down_revision = "3d4a936a7185"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "creative_library_product_variants",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("uid", sa.String(length=80), nullable=False),
        sa.Column("family_db_id", sa.BigInteger(), nullable=False),
        sa.Column("base_variant_db_id", sa.BigInteger(), nullable=True),
        sa.Column("vplib_uid", sa.String(length=128), nullable=True),
        sa.Column("family_id", sa.String(length=255), nullable=True),
        sa.Column("base_variant_id", sa.String(length=160), nullable=True),
        sa.Column("manufacturer_org_id", sa.String(length=120), nullable=False),
        sa.Column("brand", sa.String(length=255), nullable=True),
        sa.Column("product_name", sa.String(length=255), nullable=False),
        sa.Column("sku", sa.String(length=255), nullable=False),
        sa.Column("gtin", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("product_url", sa.String(length=1024), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="draft"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("visible", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("submitted_by_subject", sa.String(length=120), nullable=True),
        sa.Column("approved_by_subject", sa.String(length=120), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("properties_json", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["base_variant_db_id"], ["creative_library_variants.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["family_db_id"], ["creative_library_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("family_db_id", "manufacturer_org_id", "sku", name="uq_creative_library_product_family_org_sku"),
        sa.UniqueConstraint("uid"),
    )
    op.create_index("ix_creative_library_product_variants_uid", "creative_library_product_variants", ["uid"])
    op.create_index("ix_creative_library_product_variants_family_db_id", "creative_library_product_variants", ["family_db_id"])
    op.create_index("ix_creative_library_product_variants_base_variant_db_id", "creative_library_product_variants", ["base_variant_db_id"])
    op.create_index("ix_creative_library_product_variants_vplib_uid", "creative_library_product_variants", ["vplib_uid"])
    op.create_index("ix_creative_library_product_variants_family_id", "creative_library_product_variants", ["family_id"])
    op.create_index("ix_creative_library_product_variants_base_variant_id", "creative_library_product_variants", ["base_variant_id"])
    op.create_index("ix_creative_library_product_variants_manufacturer_org_id", "creative_library_product_variants", ["manufacturer_org_id"])
    op.create_index("ix_creative_library_product_variants_brand", "creative_library_product_variants", ["brand"])
    op.create_index("ix_creative_library_product_variants_product_name", "creative_library_product_variants", ["product_name"])
    op.create_index("ix_creative_library_product_variants_sku", "creative_library_product_variants", ["sku"])
    op.create_index("ix_creative_library_product_variants_gtin", "creative_library_product_variants", ["gtin"])
    op.create_index("ix_creative_library_product_variants_status", "creative_library_product_variants", ["status"])
    op.create_index("ix_creative_library_product_variants_active", "creative_library_product_variants", ["active"])
    op.create_index("ix_creative_library_product_variants_visible", "creative_library_product_variants", ["visible"])
    op.create_index("ix_creative_library_product_variants_submitted_by_subject", "creative_library_product_variants", ["submitted_by_subject"])
    op.create_index("ix_creative_library_product_variants_approved_by_subject", "creative_library_product_variants", ["approved_by_subject"])
    op.create_index("ix_creative_library_products_family_status", "creative_library_product_variants", ["family_db_id", "status", "active"])
    op.create_index("ix_creative_library_products_org_status", "creative_library_product_variants", ["manufacturer_org_id", "status", "active"])

    op.create_table(
        "creative_library_product_availability",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("uid", sa.String(length=80), nullable=False),
        sa.Column("product_variant_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("channel", sa.String(length=40), nullable=False, server_default="factory"),
        sa.Column("address", sa.String(length=1024), nullable=True),
        sa.Column("postal_code", sa.String(length=255), nullable=True),
        sa.Column("city", sa.String(length=255), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=False, server_default="DE"),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("radius_km", sa.Float(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_variant_id"], ["creative_library_product_variants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("uid"),
    )
    for column in ("uid", "product_variant_id", "channel", "postal_code", "city", "country_code", "latitude", "longitude", "radius_km", "active"):
        op.create_index(f"ix_creative_library_product_availability_{column}", "creative_library_product_availability", [column])
    op.create_index("ix_creative_library_availability_country_postal", "creative_library_product_availability", ["country_code", "postal_code"])
    op.create_index("ix_creative_library_availability_geo", "creative_library_product_availability", ["latitude", "longitude", "radius_km"])

    op.create_table(
        "creative_library_permission_grants",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("uid", sa.String(length=80), nullable=False),
        sa.Column("family_db_id", sa.BigInteger(), nullable=True),
        sa.Column("subject_type", sa.String(length=40), nullable=False),
        sa.Column("subject_id", sa.String(length=120), nullable=False),
        sa.Column("permission", sa.String(length=120), nullable=False),
        sa.Column("effect", sa.String(length=40), nullable=False, server_default="allow"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_subject", sa.String(length=120), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["family_db_id"], ["creative_library_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("family_db_id", "subject_type", "subject_id", "permission", name="uq_creative_library_permission_grant"),
        sa.UniqueConstraint("uid"),
    )
    for column in ("uid", "family_db_id", "subject_type", "subject_id", "permission", "effect", "active"):
        op.create_index(f"ix_creative_library_permission_grants_{column}", "creative_library_permission_grants", [column])
    op.create_index("ix_creative_library_grants_subject", "creative_library_permission_grants", ["subject_type", "subject_id", "active"])
    op.create_index("ix_creative_library_grants_family_permission", "creative_library_permission_grants", ["family_db_id", "permission", "active"])


def downgrade():
    op.drop_table("creative_library_permission_grants")
    op.drop_table("creative_library_product_availability")
    op.drop_table("creative_library_product_variants")
