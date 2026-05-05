"""SHACL validation against the regnskap-no shape graph.

Validates either:
- The taxonomy itself (smoke check; should always pass in a published wheel)
- A graph of EXTRACTED FACTS produced by regnskapsnoter-pipeline

Usage:

    from regnskap_no.shacl import validate_taxonomy, validate_facts
    ok, msgs = validate_taxonomy()
    assert ok

    # For facts: pass an rdflib.Graph with SKOS/WADM-encoded annotations
    ok, report = validate_facts(my_graph)
"""
from __future__ import annotations

from pathlib import Path
from typing import Tuple

from .api import DATA_DIR


def _load_shapes():
    try:
        from rdflib import Graph
    except ImportError as e:
        raise ImportError(
            "regnskap-no SHACL features require rdflib + pyshacl. Install with "
            "`pip install regnskap-no[shacl]`."
        ) from e
    g = Graph()
    g.parse(str(DATA_DIR / "shapes.ttl"), format="turtle")
    return g


def validate_taxonomy() -> Tuple[bool, str]:
    """Validate the bundled taxonomy against the bundled SHACL shapes.

    Returns ``(conforms, report_text)``.
    """
    try:
        from rdflib import Graph
        from pyshacl import validate
    except ImportError as e:
        raise ImportError(
            "Install with `pip install regnskap-no[shacl]`."
        ) from e
    data = Graph()
    data.parse(str(DATA_DIR / "taxonomy.ttl"), format="turtle")
    shapes = _load_shapes()
    conforms, _, report_text = validate(
        data,
        shacl_graph=shapes,
        inference="rdfs",
        debug=False,
    )
    return conforms, report_text


def validate_facts(graph) -> Tuple[bool, str]:
    """Validate an externally-supplied graph of facts.

    The graph is expected to merge in the taxonomy's RDF (via owl:imports or
    direct concatenation) so that SHACL closed-shape rules can resolve.
    """
    try:
        from pyshacl import validate
    except ImportError as e:
        raise ImportError(
            "Install with `pip install regnskap-no[shacl]`."
        ) from e
    shapes = _load_shapes()
    conforms, _, report_text = validate(
        graph,
        shacl_graph=shapes,
        inference="rdfs",
        debug=False,
    )
    return conforms, report_text
