import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SymbolInfo:
    name: str
    kind: str
    line: int


@dataclass(frozen=True)
class FileSymbols:
    path: str
    symbols: tuple[SymbolInfo, ...]
    imports: tuple[str, ...]


def build_symbol_index(
    project_root,
    repo_map,
    *,
    max_files: int = 40,
) -> tuple[FileSymbols, ...]:
    if max_files <= 0:
        raise ValueError("max_files must be greater than zero.")

    root = Path(project_root).resolve()
    if not root.exists():
        raise ValueError(f"Project root does not exist: {project_root}")
    if not root.is_dir():
        raise ValueError(f"Project root is not a directory: {project_root}")

    results = []
    for entry in sorted(repo_map.entries, key=lambda item: item.path):
        if len(results) >= max_files:
            break
        if entry.kind != "python":
            continue

        file_path = (root / entry.path).resolve()
        if not _is_inside_root(file_path, root):
            continue
        if not file_path.is_file():
            continue

        file_symbols = _extract_file_symbols(file_path, entry.path)
        if file_symbols is not None:
            results.append(file_symbols)

    return tuple(results)


def format_symbol_index(index: tuple[FileSymbols, ...]) -> str:
    lines = ["# Symbol Index", ""]
    if not index:
        lines.append("No Python symbols indexed.")
        return "\n".join(lines)

    for file_symbols in index:
        lines.append(f"- {file_symbols.path}")
        lines.append(f"  imports: {', '.join(file_symbols.imports) or 'none'}")
        lines.append(f"  symbols: {_format_symbols(file_symbols.symbols)}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _extract_file_symbols(file_path: Path, relative_path: str) -> FileSymbols | None:
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=relative_path)
    except (OSError, UnicodeDecodeError, SyntaxError):
        return None

    imports = []
    symbols = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.extend(_format_from_import(node, alias.name) for alias in node.names)
        elif isinstance(node, ast.ClassDef):
            symbols.append(SymbolInfo(name=node.name, kind="class", line=node.lineno))
        elif isinstance(node, ast.AsyncFunctionDef):
            symbols.append(SymbolInfo(name=node.name, kind="async_function", line=node.lineno))
        elif isinstance(node, ast.FunctionDef):
            symbols.append(SymbolInfo(name=node.name, kind="function", line=node.lineno))

    if not imports and not symbols:
        return None
    return FileSymbols(
        path=relative_path,
        symbols=tuple(symbols),
        imports=tuple(imports),
    )


def _format_from_import(node: ast.ImportFrom, name: str) -> str:
    module = node.module or ""
    if node.level:
        module = "." * node.level + module
    if module:
        return f"{module}.{name}"
    return name


def _format_symbols(symbols: tuple[SymbolInfo, ...]) -> str:
    if not symbols:
        return "none"
    return ", ".join(f"{symbol.name}({symbol.kind})" for symbol in symbols)


def _is_inside_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
