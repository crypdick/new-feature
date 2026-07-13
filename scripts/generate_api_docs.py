"""Generate the documentation homepage and API-reference pages during a MkDocs build."""

from __future__ import annotations

from pathlib import Path

import mkdocs_gen_files

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
PACKAGE_ROOT = SOURCE_ROOT / "new_feature"


def _module_parts(path: Path) -> tuple[str, ...] | None:
    """Return the import path represented by a Python source file."""
    relative_path = path.relative_to(SOURCE_ROOT).with_suffix("")
    if relative_path.name in {"__init__", "__main__"}:
        return None
    if any(part.startswith("_") for part in relative_path.parts):
        return None
    return relative_path.parts


def _write_homepage() -> None:
    """Make the repository README the generated site's homepage."""
    # NOTE: README.md documents that it is the source for the documentation homepage.
    homepage = PROJECT_ROOT / "README.md"
    with mkdocs_gen_files.open("index.md", "w") as document:
        document.write(homepage.read_text(encoding="utf-8"))
    mkdocs_gen_files.set_edit_path("index.md", "README.md")


def _write_reference_pages() -> None:
    """Generate one API-reference page for each public package module."""
    index_path = Path("reference/index.md")
    with mkdocs_gen_files.open(index_path, "w") as document:
        document.write("# API reference\n")

    for source_path in sorted(PACKAGE_ROOT.rglob("*.py")):
        module_parts = _module_parts(source_path)
        if module_parts is None:
            continue
        module_name = ".".join(module_parts)
        reference_path = Path("reference", *module_parts).with_suffix(".md")
        with mkdocs_gen_files.open(reference_path, "w") as document:
            document.write(f"# `{module_name}`\n\n::: {module_name}\n")
        mkdocs_gen_files.set_edit_path(reference_path, source_path.relative_to(PROJECT_ROOT))


def main() -> None:
    """Generate all virtual Markdown files consumed by MkDocs."""
    _write_homepage()
    _write_reference_pages()


main()
