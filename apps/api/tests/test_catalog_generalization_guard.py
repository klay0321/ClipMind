"""PR-A1 通用化防回归护栏（架构模式检查，非"只测当前四个产品名"的虚假安全测试）。

检查的是架构模式（非只测当前四个名）：
- 生产运行时代码零 seed 产品名硬编码（任何产品名都会 fail）；
- 生产模块不 import scripts.discovery（审计工具须隔离在 seed/评测层）；
- 产品目录以动态数据表承载：CatalogStatus 是生命周期枚举、不含产品名；产品是数据行、非枚举/CHECK。

不需要数据库；纯静态扫描。
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

# 生产运行时代码目录（排除测试/文档/discovery 审计工具/.local）
PROD_DIRS = [
    REPO_ROOT / "apps" / "api" / "app",
    REPO_ROOT / "packages" / "shared" / "clipmind_shared",
    REPO_ROOT / "services",
    REPO_ROOT / "apps" / "web" / "app",
    REPO_ROOT / "apps" / "web" / "components",
    REPO_ROOT / "apps" / "web" / "lib",
]
PROD_SUFFIXES = {".py", ".ts", ".tsx", ".sql"}
# seed 产品名（仅允许出现在 scripts/discovery 与 tests/docs；生产运行时代码须为 0）
SEED_PRODUCT_NAMES = [
    "恶魔之眼", "软屏", "硬屏", "十字架档把", "mini键盘", "车换挡握把",
]


def _prod_files() -> list[Path]:
    files: list[Path] = []
    for base in PROD_DIRS:
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or p.suffix not in PROD_SUFFIXES:
                continue
            parts = set(p.parts)
            if "tests" in parts or "__tests__" in parts or "node_modules" in parts:
                continue
            files.append(p)
    return files


def test_no_seed_product_name_hardcoded_in_production():
    """生产运行时代码中不得硬编码任何 seed 产品名（架构模式：产品是数据、非代码）。"""
    offenders: list[str] = []
    for p in _prod_files():
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for name in SEED_PRODUCT_NAMES:
            if name in text:
                offenders.append(f"{p.relative_to(REPO_ROOT)} 含 seed 产品名 '{name}'")
    assert not offenders, "生产代码硬编码 seed 产品名（应为动态数据）:\n" + "\n".join(offenders)


def test_production_does_not_import_discovery_tooling():
    """生产模块不得 import scripts.discovery（只读审计工具须隔离在 seed/评测层）。"""
    offenders: list[str] = []
    needles = ("scripts.discovery", "scripts/discovery", "audit_material_library")
    for p in _prod_files():
        if p.suffix != ".py":
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for n in needles:
            if n in text:
                offenders.append(f"{p.relative_to(REPO_ROOT)} 引用 '{n}'")
    assert not offenders, "生产模块引用 discovery 工具:\n" + "\n".join(offenders)


def test_catalog_status_enum_is_lifecycle_not_products():
    """CatalogStatus 是生命周期状态枚举，不含任何产品名（产品用动态表而非枚举）。"""
    from clipmind_shared.models.enums import CatalogStatus

    values = {s.value for s in CatalogStatus}
    assert values == {"draft", "active", "paused", "archived", "merged"}
    for name in SEED_PRODUCT_NAMES:
        assert not any(name in v for v in values)


def test_product_hierarchy_is_dynamic_tables():
    """产品层级是数据库表（动态数据行），新增产品 = 插入数据、不需枚举/CHECK/迁移。"""
    from clipmind_shared.models import (
        ProductCategory,
        ProductFamily,
        ProductSKU,
        ProductVariant,
    )

    for model in (ProductCategory, ProductFamily, ProductVariant, ProductSKU):
        # 每层是独立表，产品身份靠 name_zh/code 数据列而非枚举
        cols = {c.name for c in model.__table__.columns}
        assert "name_zh" in cols and "code" in cols
        # 不存在把产品名做成枚举/受限值的列
        assert "product_name_enum" not in cols


@pytest.mark.parametrize("model_name", ["Product", "ProductFamily"])
def test_no_product_name_check_constraint(model_name):
    """产品名不得写入 SQL CHECK（架构模式：产品名是自由数据）。"""
    import clipmind_shared.models as m

    model = getattr(m, model_name)
    for constraint in model.__table__.constraints:
        text = str(getattr(constraint, "sqltext", "")) or ""
        for name in SEED_PRODUCT_NAMES:
            assert name not in text, f"{model_name} 的 CHECK 含产品名 {name}"
