"""Repeated execution must produce identical reports."""

import json
import unittest

from tests.helpers import base_input, validate


def _rich_input():
    return base_input(
        services={
            "legacy-web": {
                "semconv_version": "1.20.0",
                "attributes": {
                    "http.status_code": {"type": "int"},
                    "rpc.duration": {"type": "double", "unit": "ms"},
                },
            },
            "gateway": {
                "semconv_version": "1.21.0",
                "attributes": {
                    "http.status_code": {
                        "type": "int", "deprecated": True,
                        "renamed_to": "http.response.status_code"},
                    "http.response.status_code": {
                        "type": "int", "required": True},
                    "rpc.duration": {"type": "double", "unit": "s"},
                    "error.kind": {
                        "type": "string",
                        "enum": ["timeout", "refused", "reset"]},
                },
                "dual_write": [{
                    "old": "http.status_code",
                    "new": "http.response.status_code",
                    "read_priority": ["http.response.status_code",
                                      "http.status_code"],
                    "retire_after": "2027-03-01",
                }],
                "dynamic_keys": {
                    "labels.": {"max_keys": 2, "max_values_per_key": 2},
                },
            },
        },
        spans=[
            {"service": "legacy-web", "name": "GET /old",
             "attributes": {"http.status_code": 200, "rpc.duration": 82.0}},
            {"service": "gateway", "name": "GET /api",
             "attributes": {
                 "http.status_code": 200,
                 "http.response.status_code": 200,
                 "rpc.duration": 0.082,
                 "error.kind": "timeout",
                 "labels.zone": "a", "labels.tier": "b", "labels.pod": "c",
             },
             "resource": {"service.name": "gateway"},
             "events": [{"name": "retry",
                         "attributes": {"retry.count": 2}}],
             "links": [{"attributes": {"link.kind": "child"}}]},
            {"service": "gateway", "name": "GET /missing",
             "attributes": {"rpc.duration": 0.01}},
        ],
    )


class IdempotencyTest(unittest.TestCase):
    def test_repeated_runs_identical(self):
        first = validate(_rich_input()).to_dict()
        second = validate(_rich_input()).to_dict()
        self.assertEqual(json.dumps(first, sort_keys=True),
                         json.dumps(second, sort_keys=True))

    def test_expected_findings_present(self):
        report = validate(_rich_input())
        found = {f.code for f in report.inconsistencies}
        self.assertIn("UNIT_MISMATCH", found)          # ms vs s
        self.assertIn("RENAMED_ATTRIBUTE", found)      # old vs new name
        self.assertIn("MISSING_REQUIRED", found)       # 3rd span lacks code
        self.assertIn("HIGH_CARDINALITY_KEYS", found)  # 3 labels.* keys > 2
        undeclared = {f.attribute for f in report.undecidable
                      if f.code == "UNDECLARED_ATTRIBUTE"}
        # resource/event/link attributes have no declared contract here.
        self.assertIn("retry.count", undeclared)
        self.assertIn("link.kind", undeclared)

    def test_no_duplicate_migration_steps(self):
        report = validate(_rich_input())
        for phase in report.migration_phases:
            serialized = [json.dumps(step, sort_keys=True)
                          for step in phase["steps"]]
            self.assertEqual(len(serialized), len(set(serialized)))


if __name__ == "__main__":
    unittest.main()
