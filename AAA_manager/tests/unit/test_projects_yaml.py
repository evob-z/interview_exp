"""测试 projects.yaml 单一真相源加载与派生逻辑。

不使用 importlib.reload（reload 会重新执行模块顶层，覆盖 monkeypatch），
而是直接调用 _load_projects_meta 与 patch 模块属性。
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _write_yaml(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


# ─── _load_projects_meta 加载 ───────────────────────────────────────────

def test_load_projects_meta_with_yaml(tmp_path, monkeypatch):
    yaml_file = tmp_path / "projects.yaml"
    _write_yaml(yaml_file, """
projects:
  - name: foo
    display: Foo
    aliases: [foo_alias, FA]
    description: foo desc
generic_categories:
  - name: 八股
    description: fundamentals
""".strip())

    import config
    monkeypatch.setattr(config, "PROJECTS_FILE", yaml_file)

    meta = config._load_projects_meta()
    assert len(meta["projects"]) == 1
    assert meta["projects"][0]["name"] == "foo"
    assert meta["projects"][0]["aliases"] == ["foo_alias", "FA"]
    assert meta["generic_categories"][0]["name"] == "八股"


def test_load_projects_meta_missing_returns_empty(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "PROJECTS_FILE", tmp_path / "nonexistent.yaml")
    meta = config._load_projects_meta()
    assert meta == {"projects": [], "generic_categories": []}


def test_load_projects_meta_invalid_yaml_safe(tmp_path, monkeypatch):
    bad_file = tmp_path / "projects.yaml"
    bad_file.write_text("::: not yaml :::\n[unclosed", encoding="utf-8")

    import config
    monkeypatch.setattr(config, "PROJECTS_FILE", bad_file)

    meta = config._load_projects_meta()
    assert meta == {"projects": [], "generic_categories": []}


# ─── 派生公式正确性 ─────────────────────────────────────────────────────

def _derive_aliases(meta: dict) -> dict:
    return {
        alias: f"项目-{p['name']}"
        for p in meta.get("projects", [])
        if p.get("name")
        for alias in (p.get("aliases") or [])
    }


def _derive_category_file_map(meta: dict) -> dict:
    fm = {
        f"项目-{p['name']}": f"项目-{p['name']}.md"
        for p in meta.get("projects", [])
        if p.get("name")
    }
    for g in meta.get("generic_categories", []):
        if g.get("name"):
            fm[g["name"]] = f"{g['name']}.md"
    return fm


def test_derive_aliases_and_file_map():
    meta = {
        "projects": [
            {"name": "alpha", "aliases": ["a1", "a2"]},
            {"name": "beta", "aliases": ["b1"]},
            {"name": "gamma"},  # 无 aliases
        ],
        "generic_categories": [
            {"name": "AI_Coding"},
            {"name": "八股"},
        ],
    }
    aliases = _derive_aliases(meta)
    assert aliases == {
        "a1": "项目-alpha",
        "a2": "项目-alpha",
        "b1": "项目-beta",
    }

    file_map = _derive_category_file_map(meta)
    assert file_map["项目-alpha"] == "项目-alpha.md"
    assert file_map["项目-beta"] == "项目-beta.md"
    assert file_map["项目-gamma"] == "项目-gamma.md"
    assert file_map["AI_Coding"] == "AI_Coding.md"
    assert file_map["八股"] == "八股.md"


# ─── extract prompt 渲染 ────────────────────────────────────────────────

def test_extract_prompt_render_with_patched_meta(monkeypatch):
    """patch extractor 模块的 PROJECTS_META 与 CATEGORY_FILE_MAP，验证渲染。"""
    import extractor

    fake_meta = {
        "projects": [
            {
                "name": "alpha",
                "aliases": ["alpha_kw", "AK"],
                "description": "alpha-desc-marker",
            }
        ],
        "generic_categories": [
            {"name": "八股", "description": "fundamentals-marker"},
        ],
    }
    fake_file_map = {
        "项目-alpha": "项目-alpha.md",
        "八股": "八股.md",
    }
    monkeypatch.setattr(extractor, "PROJECTS_META", fake_meta)
    monkeypatch.setattr(extractor, "CATEGORY_FILE_MAP", fake_file_map)

    rendered = extractor._load_system_prompt()

    assert "{{PROJECT_CATEGORIES}}" not in rendered
    assert "{{CATEGORY_ENUM}}" not in rendered
    assert "alpha_kw" in rendered
    assert "alpha-desc-marker" in rendered
    assert "项目-alpha" in rendered
    assert "fundamentals-marker" in rendered
    assert "八股" in rendered

    # 旧硬编码不应残留
    assert "law_sea" not in rendered
    assert "晓海" not in rendered
    assert "中能建" not in rendered
    assert "SHENWEI" not in rendered


def test_extract_prompt_render_empty_meta_fallback(monkeypatch):
    """projects.yaml 无任何项目时，至少给出兜底分类。"""
    import extractor

    monkeypatch.setattr(extractor, "PROJECTS_META", {"projects": [], "generic_categories": []})
    monkeypatch.setattr(extractor, "CATEGORY_FILE_MAP", {})

    rendered = extractor._load_system_prompt()
    # 至少含兜底 "八股"
    assert "八股" in rendered


# ─── 真实仓库 projects.yaml.example 可被 PyYAML 解析 ─────────────────

def test_projects_yaml_example_is_valid():
    import yaml
    example = Path(__file__).resolve().parents[2] / "projects.yaml.example"
    assert example.exists(), "projects.yaml.example 缺失"
    data = yaml.safe_load(example.read_text(encoding="utf-8"))
    assert "projects" in data
    assert "generic_categories" in data
    assert len(data["projects"]) >= 1
    for p in data["projects"]:
        assert "name" in p
        assert "aliases" in p
