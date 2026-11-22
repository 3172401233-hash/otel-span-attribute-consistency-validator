"""Dynamic maps and prefixed dynamic keys."""

import unittest

from tests.helpers import base_input, codes, undecidable_codes, validate


def _map_input(with_policy=True, bag=None):
    service = {
        "semconv_version": "1.21.0",
        "attributes": {
            "request.baggage": {"type": "map"},
        },
    }
    if with_policy:
        service["dynamic_keys"] = {
            "request.baggage": {"max_keys": 3, "max_values_per_key": 5},
        }
    if bag is None:
        bag = {"tenant": "t1", "region": "eu"}
    return base_input(
        services={"checkout": service},
        spans=[{"service": "checkout", "name": "POST /order",
                "attributes": {"request.baggage": bag}}],
    )


def _prefix_input():
    return base_input(
        services={
            "edge": {
                "semconv_version": "1.21.0",
                "attributes": {},
                "dynamic_keys": {
                    "http.request.header.": {
                        "max_keys": 2, "max_values_per_key": 3},
                },
            },
        },
        spans=[
            {"service": "edge", "name": "GET /",
             "attributes": {
                 "http.request.header.user_agent": "curl/8",
                 "http.request.header.accept": "*/*",
             }},
        ],
    )


class DynamicMapTest(unittest.TestCase):
    def test_map_with_policy_within_limits_passes(self):
        report = validate(_map_input())
        self.assertEqual(codes(report), [])
        self.assertEqual(undecidable_codes(report), [])
        self.assertEqual(report.compatibility, "full")

    def test_map_without_policy_is_undecidable(self):
        report = validate(_map_input(with_policy=False))
        self.assertIn("MAP_WITHOUT_POLICY", undecidable_codes(report))
        self.assertNotIn("MAP_WITHOUT_POLICY", codes(report))

    def test_map_exceeding_key_limit_flagged(self):
        bag = {"k%d" % i: "v" for i in range(5)}
        report = validate(_map_input(bag=bag))
        self.assertIn("HIGH_CARDINALITY_KEYS", codes(report))
        finding = next(f for f in report.inconsistencies
                       if f.code == "HIGH_CARDINALITY_KEYS")
        self.assertEqual(finding.details["distinct_keys"], 5)
        self.assertEqual(finding.details["max_keys"], 3)

    def test_prefixed_dynamic_keys_accepted(self):
        report = validate(_prefix_input())
        self.assertEqual(codes(report), [])
        self.assertEqual(undecidable_codes(report), [])

    def test_undeclared_attribute_is_undecidable_not_coerced(self):
        data = _prefix_input()
        data["spans"][0]["attributes"]["x.custom"] = "1"
        report = validate(data)
        self.assertIn("UNDECLARED_ATTRIBUTE", undecidable_codes(report))


if __name__ == "__main__":
    unittest.main()
