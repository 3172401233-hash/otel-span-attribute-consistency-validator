"""Enum violations, missing required attributes, semconv versions."""

import unittest

from tests.helpers import base_input, codes, validate


def _input(attrs, span_attributes, extra_services=None):
    services = {
        "worker": {
            "semconv_version": "1.21.0",
            "attributes": attrs,
        },
    }
    services.update(extra_services or {})
    return base_input(
        services=services,
        spans=[{"service": "worker", "name": "job",
                "attributes": span_attributes}],
    )


class SchemaChecksTest(unittest.TestCase):
    def test_invalid_enum_value(self):
        report = validate(_input(
            {"error.kind": {"type": "string",
                            "enum": ["timeout", "refused"]}},
            {"error.kind": "boom"}))
        self.assertIn("INVALID_ENUM", codes(report))
        finding = next(f for f in report.inconsistencies
                       if f.code == "INVALID_ENUM")
        self.assertEqual(finding.details["value"], "boom")

    def test_valid_enum_value_passes(self):
        report = validate(_input(
            {"error.kind": {"type": "string",
                            "enum": ["timeout", "refused"]}},
            {"error.kind": "timeout"}))
        self.assertEqual(codes(report), [])

    def test_missing_required_attribute(self):
        report = validate(_input(
            {"http.response.status_code": {"type": "int", "required": True}},
            {}))
        self.assertIn("MISSING_REQUIRED", codes(report))

    def test_optional_attribute_may_be_absent(self):
        report = validate(_input(
            {"http.response.status_code": {"type": "int"}}, {}))
        self.assertEqual(codes(report), [])

    def test_semconv_version_mismatch(self):
        report = validate(_input(
            {"messaging.operation": {"type": "string",
                                     "semconv_version": "1.21.0"}},
            {"messaging.operation": "publish"},
            extra_services={
                "consumer": {
                    "semconv_version": "1.24.0",
                    "attributes": {
                        "messaging.operation": {
                            "type": "string", "semconv_version": "1.24.0"},
                    },
                },
            }))
        self.assertIn("SEMCONV_VERSION_MISMATCH", codes(report))

    def test_unknown_service_sample_is_undecidable(self):
        data = _input({}, {})
        data["spans"].append({"service": "mystery", "name": "x",
                              "attributes": {}})
        report = validate(data)
        self.assertIn("UNKNOWN_SERVICE",
                      [f.code for f in report.undecidable])


if __name__ == "__main__":
    unittest.main()
