from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from wdcode.context import RepoMap, build_repo_map, format_repo_map


@contextmanager
def temp_project():
    project_root = Path(__file__).resolve().parents[1]
    temp_root = project_root / "test_tmp"
    temp_root.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=temp_root) as temp_dir:
        yield Path(temp_dir)
    try:
        temp_root.rmdir()
    except OSError:
        pass


def write_file(path, content="content"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_build_repo_map_scans_basic_project_structure():
    with temp_project() as project:
        write_file(project / "src/pkg/module.py")
        write_file(project / "tests/test_module.py")
        write_file(project / "docs/README.md")
        write_file(project / "pyproject.toml")

        repo_map = build_repo_map(project)

    paths = [entry.path for entry in repo_map.entries]
    assert isinstance(repo_map, RepoMap)
    assert paths == sorted(paths)
    assert paths == [
        "docs/README.md",
        "pyproject.toml",
        "src/pkg/module.py",
        "tests/test_module.py",
    ]


def test_build_repo_map_ignores_cache_environment_and_build_outputs():
    with temp_project() as project:
        write_file(project / "src/pkg/module.py")
        write_file(project / ".git/config")
        write_file(project / "__pycache__/x.pyc")
        write_file(project / ".venv/lib/site.py")
        write_file(project / "dist/app.whl")
        write_file(project / "build/temp.txt")
        write_file(project / "pkg.egg-info/PKG-INFO")
        write_file(project / ".DS_Store")
        write_file(project / ".env")

        repo_map = build_repo_map(project)

    assert [entry.path for entry in repo_map.entries] == ["src/pkg/module.py"]


def test_build_repo_map_identifies_file_roles_and_kinds():
    with temp_project() as project:
        write_file(project / "src/pkg/module.py")
        write_file(project / "tests/test_module.py")
        write_file(project / "docs/README.md")
        write_file(project / "pyproject.toml")

        repo_map = build_repo_map(project)

    entries = {entry.path: entry for entry in repo_map.entries}
    assert entries["src/pkg/module.py"].is_source is True
    assert entries["src/pkg/module.py"].summary == "Python source file"
    assert entries["tests/test_module.py"].is_test is True
    assert entries["tests/test_module.py"].summary == "Python test file"
    assert entries["docs/README.md"].is_doc is True
    assert entries["docs/README.md"].kind == "markdown"
    assert entries["pyproject.toml"].kind == "config"
    assert entries["pyproject.toml"].summary == "Configuration file"


def test_format_repo_map_outputs_stable_summary():
    with temp_project() as project:
        write_file(project / "src/pkg/module.py")
        write_file(project / "tests/test_module.py")
        write_file(project / "docs/README.md")
        repo_map = build_repo_map(project)

    output = format_repo_map(repo_map)

    assert output.startswith("# Repo Map")
    assert "Root:" in output
    assert "- src/pkg/module.py [python, source] Python source file" in output
    assert "- tests/test_module.py [python, test] Python test file" in output
    assert "- docs/README.md [markdown, doc] Markdown document" in output


def test_build_repo_map_rejects_missing_project_root():
    with temp_project() as project:
        missing = project / "missing"

        with pytest.raises(ValueError, match="does not exist"):
            build_repo_map(missing)


def test_build_repo_map_rejects_file_project_root():
    with temp_project() as project:
        file_path = project / "README.md"
        write_file(file_path)

        with pytest.raises(ValueError, match="not a directory"):
            build_repo_map(file_path)
