"""String vs integer status codes and no silent type coercion."""

import unittest

from tests.helpers import base_input, codes, validate


def _status_input(sample_value):
    return base_input(
        services={
            "gateway": {
                "semconv_version": "1.21.0",
                "attributes": {
                    "http.response.status_code": {"type": "int"},
                },
            },
            "legacy-web": {
                "semconv_version": "1.21.0",
                "attributes": {
                    "http.response.status_code": {"type": "string"},
                },
            },
        },
        spans=[
            {"service": "gateway", "name": "GET /api",
             "attributes": {"http.response.status_code": 200}},
            {"service": "legacy-web", "name": "GET /old",
             "attributes": {"http.response.status_code": sample_value}},
        ],
    )


class StatusCodeTypeTest(unittest.TestCase):
    def test_cross_service_string_vs_int(self):
        report = validate(_status_input("200"))
        self.assertIn("CROSS_SERVICE_TYPE_MISMATCH", codes(report))
        finding = next(f for f in report.inconsistencies
                       if f.code == "CROSS_SERVICE_TYPE_MISMATCH")
        self.assertEqual(finding.details["declared_types"], ["int", "string"])
        self.assertEqual(set(finding.services), {"gateway", "legacy-web"})
        self.assertEqual(report.compatibility, "none")

    def test_numeric_string_rejected_for_int_attribute(self):
        # "200" would pass if the validator int()-coerced it; it must not.
        data = _status_input(200)
        data["spans"][0]["attributes"]["http.response.status_code"] = "200"
        report = validate(data)
        finding = next(f for f in report.inconsistencies
                       if f.code == "TYPE_MISMATCH"
                       and f.services == ("gateway",))
        self.assertEqual(finding.details["observed_type"], "string")
        self.assertEqual(finding.details["declared_type"], "int")

    def test_bool_is_not_an_int(self):
        data = _status_input(200)
        data["spans"][0]["attributes"]["http.response.status_code"] = True
        report = validate(data)
        self.assertIn("TYPE_MISMATCH", codes(report))

    def test_consistent_types_pass(self):
        data = _status_input(200)
        data["services"]["legacy-web"]["attributes"][
            "http.response.status_code"]["type"] = "int"
        report = validate(data)
        self.assertNotIn("TYPE_MISMATCH", codes(report))
        self.assertNotIn("CROSS_SERVICE_TYPE_MISMATCH", codes(report))
        self.assertEqual(report.compatibility, "full")


if __name__ == "__main__":
    unittest.main()
