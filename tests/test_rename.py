"""Renamed fields, dual-write rules and migration phases."""

import unittest

from tests.helpers import base_input, codes, validate

OLD = "http.status_code"
NEW = "http.response.status_code"


def _rename_input(dual_write=None, spans=None):
    services = {
        "legacy-web": {
            "semconv_version": "1.20.0",
            "attributes": {OLD: {"type": "int"}},
        },
        "gateway": {
            "semconv_version": "1.21.0",
            "attributes": {
                OLD: {"type": "int", "deprecated": True, "renamed_to": NEW},
                NEW: {"type": "int"},
            },
        },
    }
    if dual_write is not None:
        services["gateway"]["dual_write"] = dual_write
    if spans is None:
        spans = [
            {"service": "legacy-web", "name": "GET /old",
             "attributes": {OLD: 200}},
            {"service": "gateway", "name": "GET /api",
             "attributes": {OLD: 200, NEW: 200}},
        ]
    return base_input(services=services, spans=spans)


class RenameTest(unittest.TestCase):
    def test_renamed_attribute_detected(self):
        report = validate(_rename_input())
        self.assertIn("RENAMED_ATTRIBUTE", codes(report))
        finding = next(f for f in report.inconsistencies
                       if f.code == "RENAMED_ATTRIBUTE")
        self.assertEqual(finding.details["old"], OLD)
        self.assertEqual(finding.details["new"], NEW)
        self.assertEqual(set(finding.services), {"gateway", "legacy-web"})

    def test_deprecated_without_dual_write_flagged(self):
        report = validate(_rename_input())
        self.assertIn("DEPRECATED_ATTRIBUTE", codes(report))

    def test_complete_dual_write_suppresses_deprecated_warning(self):
        report = validate(_rename_input(dual_write=[{
            "old": OLD, "new": NEW,
            "read_priority": [NEW, OLD],
            "retire_after": "2027-03-01",
        }]))
        self.assertNotIn("DEPRECATED_ATTRIBUTE", codes(report))
        self.assertNotIn("DUAL_WRITE_INCOMPLETE", codes(report))

    def test_incomplete_dual_write_flagged(self):
        report = validate(_rename_input(dual_write=[{"old": OLD, "new": NEW}]))
        self.assertIn("DUAL_WRITE_INCOMPLETE", codes(report))

    def test_conflicting_dual_values_flagged(self):
        spans = [{"service": "gateway", "name": "GET /api",
                  "attributes": {OLD: 200, NEW: 500}}]
        report = validate(_rename_input(
            dual_write=[{"old": OLD, "new": NEW,
                         "read_priority": [NEW, OLD],
                         "retire_after": "2027-03-01"}],
            spans=spans))
        self.assertIn("DUAL_WRITE_CONFLICT", codes(report))

    def test_migration_plan_phases(self):
        report = validate(_rename_input(dual_write=[{
            "old": OLD, "new": NEW,
            "read_priority": [NEW, OLD],
            "retire_after": "2027-03-01",
        }]))
        names = [p["name"] for p in report.migration_phases]
        self.assertEqual(names, ["dual-write", "consumer-switch", "retire"])
        dual = report.migration_phases[0]["steps"][0]
        self.assertEqual(dual["read_priority"], [NEW, OLD])
        self.assertEqual(dual["retire_after"], "2027-03-01")
        retire = report.migration_phases[2]["steps"][0]
        self.assertEqual(retire["attribute"], OLD)
        self.assertEqual(retire["after"], "2027-03-01")


if __name__ == "__main__":
    unittest.main()
