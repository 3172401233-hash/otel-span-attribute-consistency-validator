"""Validation report: findings, affected services, compatibility level."""

from dataclasses import dataclass, field
from typing import Any, Dict, Tuple

COMPAT_FULL = "full"
COMPAT_BACKWARD = "backward"
COMPAT_FORWARD = "forward"
COMPAT_NONE = "none"

# Lower rank wins when aggregating: the weakest link decides.
_COMPAT_RANK = {COMPAT_NONE: 0, COMPAT_FORWARD: 1, COMPAT_BACKWARD: 2,
                COMPAT_FULL: 3}

# Suggested compatibility level per finding code.
_CODE_COMPAT = {
    "CROSS_SERVICE_TYPE_MISMATCH": COMPAT_NONE,
    "TYPE_MISMATCH": COMPAT_NONE,
    "UNIT_MISMATCH": COMPAT_NONE,
    "ENUM_MISMATCH": COMPAT_BACKWARD,
    "INVALID_ENUM": COMPAT_NONE,
    "SEMCONV_VERSION_MISMATCH": COMPAT_BACKWARD,
    "RENAMED_ATTRIBUTE": COMPAT_BACKWARD,
    "DEPRECATED_ATTRIBUTE": COMPAT_BACKWARD,
    "DUAL_WRITE_INCOMPLETE": COMPAT_NONE,
    "DUAL_WRITE_CONFLICT": COMPAT_NONE,
    "DUAL_WRITE_OLD_ONLY": COMPAT_BACKWARD,
    "MISSING_REQUIRED": COMPAT_NONE,
    "HIGH_CARDINALITY_KEYS": COMPAT_FULL,
    "HIGH_CARDINALITY_VALUES": COMPAT_FULL,
}


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str  # "error" | "warning" | "unknown"
    attribute: str
    services: Tuple[str, ...]
    message: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return {
            "code": self.code,
            "severity": self.severity,
            "attribute": self.attribute,
            "services": list(self.services),
            "message": self.message,
            "details": self.details,
        }


@dataclass(frozen=True)
class ValidationReport:
    """Aggregated, deterministic validation output."""

    inconsistencies: Tuple[Finding, ...]
    undecidable: Tuple[Finding, ...]
    affected_services: Tuple[str, ...]
    compatibility: str
    migration_phases: Tuple[Dict[str, Any], ...]

    @staticmethod
    def build(findings, migration_phases):
        inconsistencies = tuple(f for f in findings if f.severity != "unknown")
        undecidable = tuple(f for f in findings if f.severity == "unknown")
        affected = sorted({svc for f in inconsistencies for svc in f.services})
        compatibility = COMPAT_FULL
        for finding in inconsistencies:
            level = _CODE_COMPAT.get(finding.code, COMPAT_NONE)
            if _COMPAT_RANK[level] < _COMPAT_RANK[compatibility]:
                compatibility = level
        return ValidationReport(
            inconsistencies=inconsistencies,
            undecidable=undecidable,
            affected_services=tuple(affected),
            compatibility=compatibility,
            migration_phases=tuple(migration_phases),
        )

    def to_dict(self):
        return {
            "compatibility": self.compatibility,
            "affected_services": list(self.affected_services),
            "inconsistencies": [f.to_dict() for f in self.inconsistencies],
            "undecidable": [f.to_dict() for f in self.undecidable],
            "migration_phases": [dict(p) for p in self.migration_phases],
        }
