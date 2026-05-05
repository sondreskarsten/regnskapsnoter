"""regnskapsnoter-shacl — fact-level validation for regnskap extractions."""
from .validator import (
    FactFailure,
    FactValidationReport,
    validate_calc_arc_consistency,
    validate_dimension_members,
    validate_facts,
    validate_period_attributes,
)

__version__ = "0.1.0"

__all__ = [
    "FactFailure",
    "FactValidationReport",
    "validate_calc_arc_consistency",
    "validate_dimension_members",
    "validate_facts",
    "validate_period_attributes",
]
