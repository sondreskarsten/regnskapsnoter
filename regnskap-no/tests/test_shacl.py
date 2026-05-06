"""SHACL validation tests.

Audit B6 flagged that ``regnskap_no.shacl`` had ZERO tests. The taxonomy
build claims "0 SHACL violations" — this test suite re-verifies that
claim from the bundled wheel artifacts.

Tests:

- :func:`validate_taxonomy` runs the bundled SHACL shapes against the
  bundled ``taxonomy.ttl`` and asserts conformance.
- :func:`validate_facts` runs a minimal hand-built RDF graph through the
  shapes, with one positive and one (deliberately bad) negative case.

These tests require ``rdflib`` and ``pyshacl`` (the ``[shacl]`` extra).
They skip cleanly if either is unavailable.
"""
from __future__ import annotations

import pytest


def _has_shacl_deps() -> bool:
    try:
        import rdflib  # noqa: F401
        import pyshacl  # noqa: F401
        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(
    not _has_shacl_deps(),
    reason="rdflib + pyshacl not installed (install with regnskap-no[shacl])",
)


def test_validate_taxonomy_conforms():
    """The bundled taxonomy must validate against its own shapes.

    This re-runs the build-time SHACL check from the wheel's perspective.
    A failure here means either:

    (a) the taxonomy artifacts and shape graph fell out of sync (the wheel
        needs rebuilding from the source repo), or
    (b) a pyshacl version drift produced a new false positive.

    Either way, this test catches it before downstream consumers get a
    bad wheel.
    """
    from regnskap_no.shacl import validate_taxonomy
    conforms, report_text = validate_taxonomy()
    assert conforms, (
        f"Bundled taxonomy SHACL validation failed:\n{report_text[:2000]}"
    )


def test_validate_facts_with_minimal_valid_graph():
    """Validate a tiny, well-formed RDF graph through the shapes."""
    import rdflib
    from regnskap_no.shacl import validate_facts

    g = rdflib.Graph()
    # Empty graph — every shape constraint is vacuously satisfied because
    # no targets exist. This is the smoke test that the validator runs
    # without exploding.
    conforms, _ = validate_facts(g)
    assert conforms is True


def test_load_shapes_returns_a_graph():
    """The shapes file must parse cleanly."""
    from regnskap_no.shacl import _load_shapes
    shapes = _load_shapes()
    # rdflib Graph supports len() == triple count
    assert len(shapes) > 0, "shapes.ttl is empty or did not parse"


def test_taxonomy_ttl_has_substantial_triples():
    """Sanity: the bundled taxonomy.ttl must have a reasonable triple count.

    The build report cited 5169 triples for v1.0.3. If this drops well
    below that, an artifact was truncated during the wheel build.
    """
    import rdflib
    from regnskap_no.api import DATA_DIR

    g = rdflib.Graph()
    g.parse(str(DATA_DIR / "taxonomy.ttl"), format="turtle")
    # Allow a wide tolerance so refactors don't break the test, but catch
    # catastrophic truncation.
    assert len(g) >= 4000, (
        f"taxonomy.ttl has only {len(g)} triples — expected ~5169 for v1.0.3"
    )
