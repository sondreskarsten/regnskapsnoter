#!/usr/bin/env bash
# scripts/release.sh — build + verify all publish-target Python wheels.
#
# Usage:
#   ./scripts/release.sh              # build to ./dist, verify with twine
#   ./scripts/release.sh upload-test  # also upload to test.pypi.org
#   ./scripts/release.sh upload       # upload to PyPI (requires TWINE_PASSWORD)
#
# Closes audit C14: standardised release workflow for the four packages
# the audit identified as PyPI-publish targets:
#   - regnskap-no                   (taxonomy wheel)
#   - noter-canonicalizer           (label resolver)
#   - regnskapsnoter-xbrl           (iXBRL emitter)
#   - regnskapsnoter-migration      (v1->v2 drift tools)
#
# Each package's pyproject.toml carries:
#   - PyPI classifiers (Topic, License, Audience, Python versions)
#   - Issues + Source URLs
#   - readme = "README.md" so the package page renders properly

set -euo pipefail

PACKAGES=(
    regnskap-no
    noter-canonicalizer
    regnskapsnoter-xbrl
    regnskapsnoter-migration
)

DIST_DIR="${DIST_DIR:-dist}"
ACTION="${1:-build}"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

rm -rf "$DIST_DIR"
mkdir -p "$DIST_DIR"

echo "::: Building wheels for ${#PACKAGES[@]} packages → $DIST_DIR"
for pkg in "${PACKAGES[@]}"; do
    echo
    echo "::: $pkg"
    (cd "$pkg" && python3 -m build --outdir "$REPO_ROOT/$DIST_DIR")
done

echo
echo "::: twine check"
twine check "$DIST_DIR"/*.whl "$DIST_DIR"/*.tar.gz

case "$ACTION" in
    build)
        echo
        echo "::: BUILD COMPLETE. Distributions in $DIST_DIR/."
        echo "    To upload to test.pypi.org: $0 upload-test"
        echo "    To upload to PyPI:           $0 upload"
        ;;
    upload-test)
        echo
        echo "::: Uploading to test.pypi.org"
        twine upload --repository testpypi "$DIST_DIR"/*
        ;;
    upload)
        echo
        echo "::: Uploading to PyPI"
        twine upload "$DIST_DIR"/*
        ;;
    *)
        echo "Unknown action: $ACTION" >&2
        echo "Usage: $0 [build|upload-test|upload]" >&2
        exit 1
        ;;
esac
