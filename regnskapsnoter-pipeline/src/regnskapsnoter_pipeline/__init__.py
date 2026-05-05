"""regnskapsnoter-pipeline — end-to-end Norwegian årsregnskap document AI."""
from .pipeline import PipelineOutput, RegnskapsnoterPipeline
from .enrichment import EnrichmentResult, enrich
from .configs import (
    REGISTRY,
    auditor_report,
    brreg_template,
    get_config,
    konsernregnskap,
    tx_log,
)

__version__ = "0.1.0"

__all__ = [
    "PipelineOutput",
    "RegnskapsnoterPipeline",
    "EnrichmentResult",
    "enrich",
    "REGISTRY",
    "auditor_report",
    "brreg_template",
    "get_config",
    "konsernregnskap",
    "tx_log",
]
