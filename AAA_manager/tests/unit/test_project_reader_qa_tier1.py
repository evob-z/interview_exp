"""Tests for QA-only project interview pack search."""

from pathlib import Path


def test_search_qa_tier1_only_reads_configured_files(tmp_path, monkeypatch):
    from knowledge import project_reader as pr_mod
    from knowledge.project_reader import ProjectReader

    monkeypatch.setattr(pr_mod, "_get_embedding_model", lambda: None)

    project_dir = tmp_path / "sample_project"
    interview_dir = project_dir / "面试"
    docs_dir = project_dir / "docs"
    interview_dir.mkdir(parents=True)
    docs_dir.mkdir()

    qa_file = interview_dir / "03_评估体系与量化指标.md"
    qa_file.write_text(
        "# 评估体系与量化指标\n\n工具调用准确率 = 正确工具调用次数 / 总工具调用次数。\n",
        encoding="utf-8",
    )
    (docs_dir / "architecture.md").write_text(
        "这个普通 docs 文件包含 不应命中 的内容。",
        encoding="utf-8",
    )
    (project_dir / "README.md").write_text(
        "README 包含 不应命中 的内容。",
        encoding="utf-8",
    )

    reader = ProjectReader(projects=[{
        "name": "sample",
        "path": str(project_dir),
        "qa_tier1": {
            "base_dir": "面试",
            "files": ["03_评估体系与量化指标.md"],
        },
    }])

    qa_results = reader.search_qa_tier1("工具调用准确率")
    assert len(qa_results) == 1
    assert qa_results[0]["project_name"] == "sample"
    assert qa_results[0]["file"] == "面试/03_评估体系与量化指标.md"

    non_qa_results = reader.search_qa_tier1("不应命中")
    assert non_qa_results == []
