"""Shared helpers for building validation inputs in tests."""

from otel_attr_validator.migration import MigrationPlanner
from otel_attr_validator.models import ValidationInput
from otel_attr_validator.report import ValidationReport
from otel_attr_validator.validator import ConsistencyValidator


def validate(data):
    """Run the full pipeline and return the report."""
    validation_input = ValidationInput.from_dict(data)
    findings = ConsistencyValidator().validate(validation_input)
    phases = MigrationPlanner().plan(validation_input, findings)
    return ValidationReport.build(findings, phases)


def codes(report):
    return [finding.code for finding in report.inconsistencies]


def undecidable_codes(report):
    return [finding.code for finding in report.undecidable]


def base_input(services, spans):
    return {
        "semconv_version": "1.21.0",
        "services": services,
        "spans": spans,
    }
