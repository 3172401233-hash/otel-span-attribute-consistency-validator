"""CLI entry point: python -m otel_attr_validator input.json

Reads a single JSON document with semconv_version, services and spans
keys, validates it offline and prints the report as JSON.
"""

import json
import sys

from .migration import MigrationPlanner
from .models import ValidationInput
from .report import ValidationReport
from .validator import ConsistencyValidator


def run(data):
    """Validate a parsed input document and return the report dict."""
    validation_input = ValidationInput.from_dict(data)
    findings = ConsistencyValidator().validate(validation_input)
    phases = MigrationPlanner().plan(validation_input, findings)
    return ValidationReport.build(findings, phases).to_dict()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1:
        sys.stderr.write("usage: python -m otel_attr_validator <input.json>\n")
        return 2
    with open(argv[0], "r", encoding="utf-8") as handle:
        data = json.load(handle)
    report = run(data)
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    has_errors = any(item["severity"] == "error"
                     for item in report["inconsistencies"])
    return 1 if has_errors else 0


if __name__ == "__main__":
    sys.exit(main())
