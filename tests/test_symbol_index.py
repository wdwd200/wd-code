from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from wdcode.context.repo_map import RepoMap, RepoMapEntry
from wdcode.context.symbol_index import build_symbol_index, format_symbol_index


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


def write_file(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def make_entry(path, *, kind="python"):
    return RepoMapEntry(
        path=path,
        kind=kind,
        size=100,
        is_source=path.startswith("src/"),
        is_test=path.startswith("tests/"),
        is_doc=path.endswith(".md"),
        summary=None,
    )


def make_repo_map(project, entries):
    return RepoMap(root=str(project), entries=tuple(entries))


def test_build_symbol_index_extracts_top_level_symbols_and_imports():
    with temp_project() as project:
        write_file(
            project / "src/pkg/module.py",
            "\n".join(
                [
                    "import os",
                    "import pathlib as p",
                    "from pathlib import Path",
                    "",
                    "class Service:",
                    "    def method(self):",
                    "        return 'METHOD_BODY_SHOULD_NOT_APPEAR'",
                    "",
                    "def run():",
                    "    return 'FUNCTION_BODY_SHOULD_NOT_APPEAR'",
                    "",
                    "async def arun():",
                    "    return 'ASYNC_BODY_SHOULD_NOT_APPEAR'",
                ]
            ),
        )
        repo_map = make_repo_map(project, [make_entry("src/pkg/module.py")])

        index = build_symbol_index(project, repo_map)

    assert len(index) == 1
    assert index[0].path == "src/pkg/module.py"
    assert index[0].imports == ("os", "pathlib", "pathlib.Path")
    assert [(symbol.name, symbol.kind) for symbol in index[0].symbols] == [
        ("Service", "class"),
        ("run", "function"),
        ("arun", "async_function"),
    ]

    output = format_symbol_index(index)
    assert "Service(class)" in output
    assert "run(function)" in output
    assert "arun(async_function)" in output
    assert "FUNCTION_BODY_SHOULD_NOT_APPEAR" not in output
    assert "METHOD_BODY_SHOULD_NOT_APPEAR" not in output
    assert "ASYNC_BODY_SHOULD_NOT_APPEAR" not in output


def test_build_symbol_index_ignores_non_python_entries():
    with temp_project() as project:
        write_file(project / "src/pkg/module.py", "def run():\n    return 'indexed'\n")
        write_file(project / "README.md", "def not_python(): pass")
        repo_map = make_repo_map(
            project,
            [
                make_entry("README.md", kind="markdown"),
                make_entry("src/pkg/module.py"),
            ],
        )

        index = build_symbol_index(project, repo_map)

    assert [file_symbols.path for file_symbols in index] == ["src/pkg/module.py"]


def test_build_symbol_index_skips_syntax_error_files():
    with temp_project() as project:
        write_file(project / "src/bad.py", "def broken(:\n")
        write_file(project / "src/good.py", "def good():\n    return 'ok'\n")
        repo_map = make_repo_map(
            project,
            [
                make_entry("src/bad.py"),
                make_entry("src/good.py"),
            ],
        )

        index = build_symbol_index(project, repo_map)

    assert [file_symbols.path for file_symbols in index] == ["src/good.py"]


def test_build_symbol_index_respects_max_files_after_path_sorting():
    with temp_project() as project:
        write_file(project / "src/b.py", "def b():\n    pass\n")
        write_file(project / "src/a.py", "def a():\n    pass\n")
        repo_map = make_repo_map(
            project,
            [
                make_entry("src/b.py"),
                make_entry("src/a.py"),
            ],
        )

        index = build_symbol_index(project, repo_map, max_files=1)

    assert [file_symbols.path for file_symbols in index] == ["src/a.py"]


def test_build_symbol_index_rejects_non_positive_max_files():
    with temp_project() as project:
        repo_map = make_repo_map(project, [])

        with pytest.raises(ValueError, match="max_files"):
            build_symbol_index(project, repo_map, max_files=0)


def test_build_symbol_index_skips_paths_outside_project_root():
    with temp_project() as project:
        outside = project.parent / "outside_symbol_index.py"
        write_file(outside, "def outside():\n    pass\n")
        try:
            repo_map = make_repo_map(project, [make_entry("../outside_symbol_index.py")])

            index = build_symbol_index(project, repo_map)
        finally:
            outside.unlink(missing_ok=True)

    assert index == ()


def test_build_symbol_index_rejects_invalid_project_root():
    with temp_project() as project:
        repo_map = make_repo_map(project, [])

        with pytest.raises(ValueError, match="does not exist"):
            build_symbol_index(project / "missing", repo_map)

        file_path = project / "file.py"
        write_file(file_path, "def run():\n    pass\n")
        with pytest.raises(ValueError, match="not a directory"):
            build_symbol_index(file_path, repo_map)


def test_format_symbol_index_handles_empty_index():
    assert format_symbol_index(()) == "# Symbol Index\n\nNo Python symbols indexed."


def test_format_symbol_index_does_not_include_absolute_paths():
    with temp_project() as project:
        write_file(project / "src/pkg/module.py", "def run():\n    pass\n")
        repo_map = make_repo_map(project, [make_entry("src/pkg/module.py")])

        output = format_symbol_index(build_symbol_index(project, repo_map))

    assert str(project) not in output
    assert "- src/pkg/module.py" in output
