"""Seconds vs milliseconds mixing across services."""

import unittest

from tests.helpers import base_input, codes, undecidable_codes, validate


def _unit_input():
    return base_input(
        services={
            "frontend": {
                "semconv_version": "1.21.0",
                "attributes": {
                    "http.server.request.duration": {
                        "type": "double", "unit": "s"},
                },
            },
            "payments": {
                "semconv_version": "1.21.0",
                "attributes": {
                    "http.server.request.duration": {
                        "type": "double", "unit": "ms"},
                },
            },
        },
        spans=[
            {"service": "frontend", "name": "GET /",
             "attributes": {"http.server.request.duration": 0.082}},
            {"service": "payments", "name": "POST /pay",
             "attributes": {"http.server.request.duration": 82.0}},
        ],
    )


class UnitMismatchTest(unittest.TestCase):
    def test_seconds_vs_milliseconds_flagged(self):
        report = validate(_unit_input())
        self.assertIn("UNIT_MISMATCH", codes(report))
        finding = next(f for f in report.inconsistencies
                       if f.code == "UNIT_MISMATCH")
        self.assertEqual(finding.attribute, "http.server.request.duration")
        self.assertEqual(set(finding.services), {"frontend", "payments"})
        conversion = finding.details["conversion"]
        self.assertEqual({conversion["from"], conversion["to"]}, {"s", "ms"})
        self.assertIn(conversion["factor"], (0.001, 1000.0))

    def test_migration_plan_has_explicit_conversion(self):
        report = validate(_unit_input())
        dual = next(p for p in report.migration_phases
                    if p["name"] == "dual-write")
        step = next(s for s in dual["steps"]
                    if s["action"] == "convert_unit")
        self.assertEqual(step["attribute"], "http.server.request.duration")
        self.assertIn(step["factor"], (0.001, 1000.0))
        # A unit change is breaking until the conversion is rolled out.
        self.assertEqual(report.compatibility, "none")

    def test_consistent_units_pass(self):
        data = _unit_input()
        data["services"]["payments"]["attributes"][
            "http.server.request.duration"]["unit"] = "s"
        data["spans"][1]["attributes"][
            "http.server.request.duration"] = 0.082
        report = validate(data)
        self.assertNotIn("UNIT_MISMATCH", codes(report))
        self.assertEqual(report.compatibility, "full")

    def test_unit_declared_on_one_side_only_is_undecidable(self):
        data = _unit_input()
        del data["services"]["payments"]["attributes"][
            "http.server.request.duration"]["unit"]
        report = validate(data)
        self.assertIn("UNIT_UNDECIDABLE", undecidable_codes(report))
        self.assertNotIn("UNIT_MISMATCH", codes(report))


if __name__ == "__main__":
    unittest.main()
