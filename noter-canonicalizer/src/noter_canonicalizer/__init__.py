"""noter-canonicalizer — exact → fuzzy → embedding cascade for label → concept ID resolution."""
from .resolver import (
    resolve,
    resolve_many,
    normalise,
    get_index,
    ResolutionMatch,
    ResolutionResult,
)

__version__ = "0.1.0"

__all__ = [
    "resolve", "resolve_many", "normalise", "get_index",
    "ResolutionMatch", "ResolutionResult",
]
