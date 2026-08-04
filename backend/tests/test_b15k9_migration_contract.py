import ast
from pathlib import Path
import re


REVISION = "0007_comparison_family_pricing"
DOWN_REVISION = "0006_unit_basis_pricing"


def migration_path() -> Path:
    root = Path(__file__).resolve().parents[1]
    matches = list(root.rglob(f"{REVISION}.py"))
    assert len(matches) == 1
    return matches[0]


def test_revision_identifier_is_safe_and_exact():
    assert len(REVISION) <= 32
    source = migration_path().read_text(encoding="utf-8")
    tree = ast.parse(source)
    assignments = {
        node.target.id: ast.literal_eval(node.value)
        for node in tree.body
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id in {"revision", "down_revision"}
        )
    }
    assert assignments["revision"] == REVISION
    assert assignments["down_revision"] == DOWN_REVISION


def test_migration_creates_only_three_expected_tables():
    source = migration_path().read_text(encoding="utf-8")
    created = re.findall(r'op\.create_table\(\s*"([^"]+)"', source)
    assert created == [
        "offer_pricing_normalizations",
        "comparison_families",
        "comparison_family_members",
    ]
    assert "op.bulk_insert" not in source
    assert "op.execute" not in source
    assert "INSERT INTO" not in source.upper()


def test_migration_downgrade_drops_reverse_order():
    source = migration_path().read_text(encoding="utf-8")
    dropped = re.findall(r'op\.drop_table\(\s*"([^"]+)"', source)
    assert dropped == [
        "comparison_family_members",
        "comparison_families",
        "offer_pricing_normalizations",
    ]



def test_migration_contains_all_hardening_constraints():
    source = migration_path().read_text(encoding="utf-8")
    for name in (
        "ck_offer_pricing_normalizations_advertised_price",
        "ck_offer_pricing_normalizations_basis_positive",
        "ck_offer_pricing_normalizations_basis_unit",
        "ck_offer_pricing_normalizations_fixed_quantity",
        "ck_offer_pricing_normalizations_review",
        "ck_offer_pricing_normalizations_accepted_ready",
        "ck_comparison_families_basis_compatible",
        "ck_comparison_family_members_method",
        "ck_comparison_family_members_decision",
    ):
        assert name in source
