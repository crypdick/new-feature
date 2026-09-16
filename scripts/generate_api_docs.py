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


def _write_root_pages() -> None:
    """Publish root Markdown documents without maintaining duplicate source files."""
    # NOTE: docs/CONTRIBUTING.md documents README.md as the documentation homepage source.
    for source, destination in (("README.md", "index.md"), ("CONVENTIONS.md", "CONVENTIONS.md")):
        with mkdocs_gen_files.open(destination, "w") as document:
            document.write((PROJECT_ROOT / source).read_text(encoding="utf-8"))
        mkdocs_gen_files.set_edit_path(destination, f"../{source}")


def _write_reference_pages() -> list[dict[str, str]]:
    """Generate module pages and return their navigation entries."""
    index_path = Path("reference/index.md")
    navigation = [{"Overview": str(index_path)}]
    index = [
        "# Python module reference\n",
        (
            "Implementation reference for contributors changing `new-feature` itself. "
            "These symbols are not documented as a stable external Python API.\n"
        ),
    ]

    for source_path in sorted(PACKAGE_ROOT.rglob("*.py")):
        module_parts = _module_parts(source_path)
        if module_parts is None:
            continue
        module_name = ".".join(module_parts)
        reference_path = Path("reference", *module_parts).with_suffix(".md")
        with mkdocs_gen_files.open(reference_path, "w") as document:
            document.write(f"# `{module_name}`\n\n::: {module_name}\n")
        mkdocs_gen_files.set_edit_path(reference_path, Path("..") / source_path.relative_to(PROJECT_ROOT))
        navigation.append({module_name: str(reference_path)})
        index.append(f"- [`{module_name}`]({reference_path.relative_to('reference').as_posix()})")

    with mkdocs_gen_files.open(index_path, "w") as document:
        document.write("\n".join(index) + "\n")
    mkdocs_gen_files.set_edit_path(index_path, "../scripts/generate_api_docs.py")
    return navigation


def main() -> None:
    """Generate all virtual Markdown files consumed by MkDocs."""
    _write_root_pages()
    reference = _write_reference_pages()
    # NOTE: docs/CONTRIBUTING.md describes this audience-specific navigation.
    mkdocs_gen_files.config["nav"] = [
        {"Using new-feature": "index.md"},
        {
            "Contributing": [
                {"Contributor guide": "CONTRIBUTING.md"},
                {"Quality checks": "QUALITY.md"},
                {"Design conventions": "CONVENTIONS.md"},
            ]
        },
        {
            "Internals": [
                {"Architecture": "ARCHITECTURE.md"},
                {"Python module reference": reference},
            ]
        },
    ]


main()
