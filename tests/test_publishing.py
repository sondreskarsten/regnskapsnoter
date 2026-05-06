"""Publishing-readiness tests for the 4 PyPI-target packages (audit C14).

The audit said: 'pip install regnskap-no from PyPI, pinned by version.
Reality: only sondreskarsten.r-universe.dev for the R package; no Python
wheels published.'

These tests pin the publishing contract so it stops drifting:

  - Each publish-target pyproject.toml has the required PyPI metadata
    (classifiers, license, keywords, URLs)
  - Each has a README.md the wheel will ship
  - Versions follow semver-ish (digits + dots)
  - The release.sh script names exactly these 4 packages
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[no-redef]


REPO_ROOT = Path(__file__).resolve().parents[1]
PUBLISH_TARGETS = [
    "regnskap-no",
    "noter-canonicalizer",
    "regnskapsnoter-xbrl",
    "regnskapsnoter-migration",
]


def _pyproject(pkg: str) -> dict:
    path = REPO_ROOT / pkg / "pyproject.toml"
    return tomllib.loads(path.read_text())


# ---- Per-package required metadata ----

@pytest.mark.parametrize("pkg", PUBLISH_TARGETS)
def test_pyproject_exists_and_parses(pkg):
    cfg = _pyproject(pkg)
    assert "project" in cfg
    proj = cfg["project"]
    assert proj["name"] == pkg
    # Version must look semver-ish
    assert re.match(r"^\d+\.\d+\.\d+", proj["version"]), (
        f"{pkg} version {proj['version']!r} is not semver"
    )


@pytest.mark.parametrize("pkg", PUBLISH_TARGETS)
def test_pyproject_has_readme(pkg):
    cfg = _pyproject(pkg)
    proj = cfg["project"]
    assert proj.get("readme") == "README.md"
    readme = REPO_ROOT / pkg / "README.md"
    assert readme.exists(), f"{pkg}/README.md missing"
    # README must be non-trivial
    assert len(readme.read_text()) > 200


@pytest.mark.parametrize("pkg", PUBLISH_TARGETS)
def test_pyproject_has_license(pkg):
    cfg = _pyproject(pkg)
    proj = cfg["project"]
    license_ = proj.get("license", {})
    if isinstance(license_, dict):
        assert license_.get("text"), f"{pkg} missing license.text"
    else:
        assert license_, f"{pkg} missing license"


@pytest.mark.parametrize("pkg", PUBLISH_TARGETS)
def test_pyproject_has_classifiers(pkg):
    cfg = _pyproject(pkg)
    classifiers = cfg["project"].get("classifiers", [])
    assert classifiers, f"{pkg} has no PyPI classifiers"
    # Must declare Python version support
    py_classifiers = [c for c in classifiers if "Python" in c]
    assert py_classifiers, f"{pkg} has no Python version classifiers"
    # Must declare an audience
    audiences = [c for c in classifiers if "Intended Audience" in c]
    assert audiences, f"{pkg} has no Intended Audience classifier"


@pytest.mark.parametrize("pkg", PUBLISH_TARGETS)
def test_pyproject_has_keywords(pkg):
    cfg = _pyproject(pkg)
    kw = cfg["project"].get("keywords", [])
    assert len(kw) >= 3, (
        f"{pkg} has only {len(kw)} keywords; PyPI search needs ≥ 3"
    )


@pytest.mark.parametrize("pkg", PUBLISH_TARGETS)
def test_pyproject_has_issues_url(pkg):
    cfg = _pyproject(pkg)
    urls = cfg["project"].get("urls", {})
    assert "Issues" in urls, f"{pkg} missing Issues URL"


@pytest.mark.parametrize("pkg", PUBLISH_TARGETS)
def test_pyproject_authors_set(pkg):
    cfg = _pyproject(pkg)
    authors = cfg["project"].get("authors", [])
    assert authors and authors[0].get("name") == "Sondre Skarsten"


# ---- Release script contract ----

def test_release_script_exists_and_executable():
    script = REPO_ROOT / "scripts" / "release.sh"
    assert script.exists()
    # Executable bit set
    import os
    assert os.access(script, os.X_OK)


def test_release_script_lists_all_publish_targets():
    """The release script must mention every publish-target package."""
    script = REPO_ROOT / "scripts" / "release.sh"
    content = script.read_text()
    for pkg in PUBLISH_TARGETS:
        assert pkg in content, (
            f"release.sh does not mention {pkg} — won't ship to PyPI"
        )


# ---- GitHub Actions workflow ----

def test_publish_workflow_exists():
    wf = REPO_ROOT / ".github" / "workflows" / "publish.yml"
    assert wf.exists()
    content = wf.read_text()
    # Triggered by tags
    assert "tags:" in content
    # Calls release.sh build
    assert "release.sh" in content
    # Has both testpypi + pypi publish jobs
    assert "publish-test" in content
    assert "publish-pypi" in content
