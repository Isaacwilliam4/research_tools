"""
Scaffold a new Python project with a standard src-layout package structure.

Usage:  create-python-project /path/to/new_project_name

Creates the target directory (including any missing parents) containing a
src/<package_name>/__init__.py package, a pyproject.toml (hatchling
build-backend), a .gitignore, and a README.md.
"""

import argparse
import re
from pathlib import Path

GITIGNORE = """\
__pycache__/
*.pyc
.venv/
*.egg-info/
dist/
build/
"""

PYPROJECT_TEMPLATE = """\
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "{dist_name}"
version = "0.1.0"
description = ""
requires-python = ">=3.10"
dependencies = []

[tool.hatch.build.targets.wheel]
packages = ["src/{package_name}"]
"""


def to_dist_name(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower()
    return slug or "project"


def to_package_name(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").lower()
    if not slug:
        slug = "project"
    if slug[0].isdigit():
        slug = f"_{slug}"
    return slug


def create_project(project_dir: Path) -> Path:
    project_dir = project_dir.resolve()
    if project_dir.exists() and any(project_dir.iterdir()):
        raise FileExistsError(f"{project_dir} already exists and is not empty")

    dist_name = to_dist_name(project_dir.name)
    package_name = to_package_name(project_dir.name)

    src_dir = project_dir / "src" / package_name
    src_dir.mkdir(parents=True, exist_ok=True)

    (src_dir / "__init__.py").write_text("")
    (project_dir / "pyproject.toml").write_text(
        PYPROJECT_TEMPLATE.format(dist_name=dist_name, package_name=package_name)
    )
    (project_dir / ".gitignore").write_text(GITIGNORE)
    (project_dir / "README.md").write_text(f"# {dist_name}\n")

    return project_dir


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scaffold a new Python project with a src-layout package structure."
    )
    parser.add_argument("path", type=Path, help="path to the new project directory, e.g. ./my_project")
    args = parser.parse_args()

    created = create_project(args.path)
    print(f"Created project at {created}")


if __name__ == "__main__":
    main()
