"""High-cardinality dynamic labels across many sampled spans."""

import unittest

from tests.helpers import base_input, codes, validate


def _cardinality_input(user_ids):
    spans = [
        {"service": "api", "name": "GET /u",
         "attributes": {"enduser.id": uid}}
        for uid in user_ids
    ]
    return base_input(
        services={
            "api": {
                "semconv_version": "1.21.0",
                "attributes": {},
                "dynamic_keys": {
                    "enduser.": {"max_keys": 10, "max_values_per_key": 3},
                },
            },
        },
        spans=spans,
    )


class CardinalityTest(unittest.TestCase):
    def test_high_cardinality_values_flagged(self):
        report = validate(_cardinality_input(["u1", "u2", "u3", "u4"]))
        self.assertIn("HIGH_CARDINALITY_VALUES", codes(report))
        finding = next(f for f in report.inconsistencies
                       if f.code == "HIGH_CARDINALITY_VALUES")
        self.assertEqual(finding.attribute, "enduser.id")
        self.assertEqual(finding.details["distinct_values"], 4)
        self.assertEqual(finding.details["max_values_per_key"], 3)
        # Cardinality does not break wire compatibility.
        self.assertEqual(report.compatibility, "full")

    def test_repeated_values_within_limit_pass(self):
        report = validate(_cardinality_input(["u1", "u1", "u2", "u2", "u3"]))
        self.assertNotIn("HIGH_CARDINALITY_VALUES", codes(report))

    def test_many_distinct_keys_flagged(self):
        data = base_input(
            services={
                "api": {
                    "semconv_version": "1.21.0",
                    "attributes": {},
                    "dynamic_keys": {
                        "label.": {"max_keys": 2, "max_values_per_key": 10},
                    },
                },
            },
            spans=[{"service": "api", "name": "GET /",
                    "attributes": {"label.a": "1", "label.b": "2",
                                   "label.c": "3"}}],
        )
        report = validate(data)
        self.assertIn("HIGH_CARDINALITY_KEYS", codes(report))


if __name__ == "__main__":
    unittest.main()
