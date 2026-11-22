"""OpenTelemetry span attribute consistency validator.

Offline analysis of service schemas and sampled spans. This package never
connects to a Collector or any live telemetry backend.
"""

from .models import (
    AttributeSpec,
    DualWriteRule,
    ServiceSchema,
    SpanSample,
    ValidationInput,
)
from .validator import ConsistencyValidator
from .migration import MigrationPlanner
from .report import ValidationReport, Finding

__all__ = [
    "AttributeSpec",
    "DualWriteRule",
    "ServiceSchema",
    "SpanSample",
    "ValidationInput",
    "ConsistencyValidator",
    "MigrationPlanner",
    "ValidationReport",
    "Finding",
]

__version__ = "0.1.0"
