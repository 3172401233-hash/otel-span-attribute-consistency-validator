"""Consistency checks between service schemas and sampled spans.

The validator never coerces sample values to make a check pass: a string
``"200"`` where the schema declares ``int`` is reported as a type mismatch,
not converted. The single exception is JSON's numeric representation, where
an integral number is accepted for a ``double`` attribute.
"""

from collections import defaultdict
from typing import Any, Dict, List, Tuple

from .models import ValidationInput
from .report import Finding

# Multiplicative factor to convert a value FROM the key unit TO each target.
_TIME_IN_NS = {"ns": 1, "us": 1_000, "ms": 1_000_000, "s": 1_000_000_000}

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_UNKNOWN = "unknown"


def unit_conversion_factor(from_unit, to_unit):
    """Return the explicit factor from_unit -> to_unit, or None if unknown."""
    if from_unit == to_unit:
        return 1
    if from_unit in _TIME_IN_NS and to_unit in _TIME_IN_NS:
        return _TIME_IN_NS[from_unit] / _TIME_IN_NS[to_unit]
    return None


def _matches_type(spec_type, value):
    if spec_type == "string":
        return isinstance(value, str)
    if spec_type == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if spec_type == "double":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if spec_type == "boolean":
        return isinstance(value, bool)
    if spec_type == "map":
        return isinstance(value, dict)
    if spec_type.endswith("[]"):
        if not isinstance(value, list):
            return False
        element_type = spec_type[:-2]
        return all(_matches_type(element_type, item) for item in value)
    return False


def _observed_type(value):
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "double"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return "map"
    if isinstance(value, list):
        return "array"
    return type(value).__name__


class ConsistencyValidator:
    """Runs all consistency checks and returns a flat list of findings."""

    def validate(self, data: ValidationInput) -> List[Finding]:
        findings = []  # type: List[Finding]
        findings.extend(self._check_cross_service(data))
        findings.extend(self._check_spans(data))
        findings.sort(key=lambda f: (f.code, f.attribute, f.services))
        return findings

    # ------------------------------------------------------------------
    # Schema-level checks across services
    # ------------------------------------------------------------------
    def _check_cross_service(self, data: ValidationInput) -> List[Finding]:
        findings = []
        by_name = defaultdict(list)  # type: Dict[str, List[Tuple[str, Any]]]
        for service_name, schema in sorted(data.services.items()):
            for attr_name, spec in sorted(schema.attributes.items()):
                by_name[attr_name].append((service_name, spec))

        for attr_name in sorted(by_name):
            entries = by_name[attr_name]
            services = tuple(sorted(name for name, _ in entries))

            types = {spec.type for _, spec in entries}
            if len(types) > 1:
                findings.append(Finding(
                    code="CROSS_SERVICE_TYPE_MISMATCH",
                    severity=SEVERITY_ERROR,
                    attribute=attr_name,
                    services=services,
                    message="attribute declared with different types across "
                            "services: %s" % self._format_declarations(
                                entries, "type"),
                    details={"declared_types": sorted(types)},
                ))

            units = {spec.unit for _, spec in entries}
            if len(units) > 1:
                declared = sorted(u for u in units if u)
                factor = None
                if len(declared) == 2:
                    factor = unit_conversion_factor(declared[0], declared[1])
                if None in units:
                    findings.append(Finding(
                        code="UNIT_UNDECIDABLE",
                        severity=SEVERITY_UNKNOWN,
                        attribute=attr_name,
                        services=services,
                        message="unit declared only by some services (%s); "
                                "cannot safely compare values"
                                % ", ".join(declared) or "none",
                        details={"declared_units": declared},
                    ))
                elif factor is None:
                    findings.append(Finding(
                        code="UNIT_UNDECIDABLE",
                        severity=SEVERITY_UNKNOWN,
                        attribute=attr_name,
                        services=services,
                        message="units %s differ and no known conversion "
                                "exists" % ", ".join(declared),
                        details={"declared_units": declared},
                    ))
                else:
                    findings.append(Finding(
                        code="UNIT_MISMATCH",
                        severity=SEVERITY_ERROR,
                        attribute=attr_name,
                        services=services,
                        message="attribute declared with different units: "
                                "%s" % self._format_declarations(
                                    entries, "unit"),
                        details={
                            "declared_units": declared,
                            "conversion": {
                                "from": declared[0],
                                "to": declared[1],
                                "factor": factor,
                            },
                        },
                    ))

            enums = {tuple(spec.enum) for _, spec in entries
                     if spec.enum is not None}
            if len(enums) > 1:
                sets = [set(e) for e in enums]
                subset = any(a < b for a in sets for b in sets if a is not b)
                findings.append(Finding(
                    code="ENUM_MISMATCH",
                    severity=SEVERITY_WARNING if subset else SEVERITY_ERROR,
                    attribute=attr_name,
                    services=services,
                    message="enum domains differ across services",
                    details={"enum_domains": [sorted(e) for e in enums]},
                ))

            versions = {spec.semconv_version for _, spec in entries
                        if spec.semconv_version}
            if len(versions) > 1:
                findings.append(Finding(
                    code="SEMCONV_VERSION_MISMATCH",
                    severity=SEVERITY_WARNING,
                    attribute=attr_name,
                    services=services,
                    message="attribute pinned to different semantic "
                            "convention versions: %s"
                            % ", ".join(sorted(versions)),
                    details={"semconv_versions": sorted(versions)},
                ))

        # Detect old/new field confusion: one service emits the old name,
        # another the new name declared via renamed_to.
        renamed = defaultdict(list)  # old -> [(service, new_name)]
        for service_name, schema in sorted(data.services.items()):
            for attr_name, spec in sorted(schema.attributes.items()):
                if spec.renamed_to:
                    renamed[attr_name].append((service_name, spec.renamed_to))
        for old_name in sorted(renamed):
            for service_name, new_name in renamed[old_name]:
                old_users = sorted(
                    name for name, schema in data.services.items()
                    if old_name in schema.attributes
                    and not schema.attributes[old_name].deprecated
                    and name != service_name
                )
                if old_users:
                    findings.append(Finding(
                        code="RENAMED_ATTRIBUTE",
                        severity=SEVERITY_WARNING,
                        attribute=old_name,
                        services=tuple(sorted([service_name] + old_users)),
                        message="%r renamed to %r in %s but still declared "
                                "as current by %s"
                                % (old_name, new_name, service_name,
                                   ", ".join(old_users)),
                        details={"old": old_name, "new": new_name},
                    ))
        return findings

    @staticmethod
    def _format_declarations(entries, field_name):
        return ", ".join(
            "%s=%r" % (name, getattr(spec, field_name))
            for name, spec in entries
        )

    # ------------------------------------------------------------------
    # Sample-level checks
    # ------------------------------------------------------------------
    def _check_spans(self, data: ValidationInput) -> List[Finding]:
        findings = []
        dynamic_seen = defaultdict(
            lambda: defaultdict(set)
        )  # type: Dict[Tuple[str, str], Dict[str, set]]

        for span in data.spans:
            schema = data.services.get(span.service)
            if schema is None:
                findings.append(Finding(
                    code="UNKNOWN_SERVICE",
                    severity=SEVERITY_UNKNOWN,
                    attribute="",
                    services=(span.service,),
                    message="span sampled from service %r which has no "
                            "schema" % span.service,
                    details={"span": span.name},
                ))
                continue

            for scope, attrs in span.scoped_attributes():
                findings.extend(
                    self._check_attributes(schema, span, scope, attrs,
                                           dynamic_seen)
                )

        findings.extend(self._check_cardinality(data, dynamic_seen))
        return findings

    def _check_attributes(self, schema, span, scope, attrs, dynamic_seen):
        findings = []
        where = "%s span %r (%s)" % (span.service, span.name, scope)

        for name in sorted(attrs):
            value = attrs[name]
            spec = schema.attributes.get(name)

            if spec is None:
                policy = self._match_dynamic_policy(schema, name)
                if policy is not None:
                    dynamic_seen[(schema.name, policy.prefix)][name].add(
                        repr(value))
                    continue
                findings.append(Finding(
                    code="UNDECLARED_ATTRIBUTE",
                    severity=SEVERITY_UNKNOWN,
                    attribute=name,
                    services=(schema.name,),
                    message="attribute %r present in %s but not declared in "
                            "the service schema; cannot safely judge it"
                            % (name, where),
                    details={"observed_type": _observed_type(value)},
                ))
                continue

            if not _matches_type(spec.type, value):
                findings.append(Finding(
                    code="TYPE_MISMATCH",
                    severity=SEVERITY_ERROR,
                    attribute=name,
                    services=(schema.name,),
                    message="attribute %r declared as %s but observed %s in "
                            "%s; value is NOT coerced"
                            % (name, spec.type, _observed_type(value), where),
                    details={
                        "declared_type": spec.type,
                        "observed_type": _observed_type(value),
                    },
                ))
                # Skip enum check on wrongly typed values: comparing across
                # types would itself be a silent coercion.
                continue

            if spec.enum is not None and value not in spec.enum:
                findings.append(Finding(
                    code="INVALID_ENUM",
                    severity=SEVERITY_ERROR,
                    attribute=name,
                    services=(schema.name,),
                    message="attribute %r has value %r in %s which is "
                            "outside the declared enum"
                            % (name, value, where),
                    details={"value": value, "enum": list(spec.enum)},
                ))

            if spec.deprecated:
                rule = schema.find_dual_write(name)
                if rule is None:
                    findings.append(Finding(
                        code="DEPRECATED_ATTRIBUTE",
                        severity=SEVERITY_WARNING,
                        attribute=name,
                        services=(schema.name,),
                        message="deprecated attribute %r still emitted in "
                                "%s with no dual-write migration rule"
                                % (name, where),
                        details={"renamed_to": spec.renamed_to},
                    ))

            if spec.type == "map" and isinstance(value, dict):
                policy = self._match_dynamic_policy(schema, name)
                for key in sorted(value):
                    dynamic_seen[(schema.name, name)][key].add(
                        repr(value[key]))
                if policy is None:
                    findings.append(Finding(
                        code="MAP_WITHOUT_POLICY",
                        severity=SEVERITY_UNKNOWN,
                        attribute=name,
                        services=(schema.name,),
                        message="map attribute %r in %s has %d dynamic "
                                "keys but no cardinality policy; cannot "
                                "safely judge it"
                                % (name, where, len(value)),
                        details={"keys": sorted(value)},
                    ))

        # Required attributes (span scope only: resource/events/links have
        # their own contracts in this tool's input model).
        if scope == "span":
            for name, spec in sorted(schema.attributes.items()):
                if spec.required and name not in attrs:
                    rule = schema.find_dual_write(name)
                    if rule and (rule.old in attrs or rule.new in attrs):
                        continue  # covered by the dual-field allowance
                    findings.append(Finding(
                        code="MISSING_REQUIRED",
                        severity=SEVERITY_ERROR,
                        attribute=name,
                        services=(schema.name,),
                        message="required attribute %r missing from %s"
                                % (name, where),
                        details={},
                    ))

        findings.extend(self._check_dual_write(schema, span, scope, attrs))
        return findings

    def _check_dual_write(self, schema, span, scope, attrs):
        findings = []
        where = "%s span %r (%s)" % (span.service, span.name, scope)
        for rule in schema.dual_write:
            if not rule.is_complete():
                findings.append(Finding(
                    code="DUAL_WRITE_INCOMPLETE",
                    severity=SEVERITY_ERROR,
                    attribute=rule.new,
                    services=(schema.name,),
                    message="dual-write rule %r -> %r must declare "
                            "read_priority and retire_after"
                            % (rule.old, rule.new),
                    details={
                        "read_priority": list(rule.read_priority),
                        "retire_after": rule.retire_after,
                    },
                ))
            old_present = rule.old in attrs
            new_present = rule.new in attrs
            if old_present and new_present:
                if attrs[rule.old] != attrs[rule.new]:
                    findings.append(Finding(
                        code="DUAL_WRITE_CONFLICT",
                        severity=SEVERITY_ERROR,
                        attribute=rule.new,
                        services=(schema.name,),
                        message="dual-written fields %r and %r disagree in "
                                "%s" % (rule.old, rule.new, where),
                        details={
                            "old_value": attrs[rule.old],
                            "new_value": attrs[rule.new],
                        },
                    ))
            elif old_present and not new_present:
                findings.append(Finding(
                    code="DUAL_WRITE_OLD_ONLY",
                    severity=SEVERITY_WARNING,
                    attribute=rule.old,
                    services=(schema.name,),
                    message="only legacy field %r emitted in %s; new field "
                            "%r not yet dual-written"
                            % (rule.old, where, rule.new),
                    details={"new": rule.new},
                ))
        return findings

    @staticmethod
    def _match_dynamic_policy(schema, name):
        for policy in schema.dynamic_keys:
            if name == policy.prefix or name.startswith(policy.prefix):
                return policy
        return None

    def _check_cardinality(self, data, dynamic_seen):
        findings = []
        for (service_name, prefix) in sorted(dynamic_seen):
            schema = data.services.get(service_name)
            if schema is None:
                continue
            keys = dynamic_seen[(service_name, prefix)]
            policy = self._match_dynamic_policy(schema, prefix)
            max_keys = policy.max_keys if policy else 0
            max_values = policy.max_values_per_key if policy else 0
            if policy is None:
                continue  # already reported as MAP_WITHOUT_POLICY
            if len(keys) > max_keys:
                findings.append(Finding(
                    code="HIGH_CARDINALITY_KEYS",
                    severity=SEVERITY_WARNING,
                    attribute=prefix,
                    services=(service_name,),
                    message="dynamic keys under %r reached %d distinct "
                            "keys (policy max %d)"
                            % (prefix, len(keys), max_keys),
                    details={
                        "distinct_keys": len(keys),
                        "max_keys": max_keys,
                    },
                ))
            for key in sorted(keys):
                if len(keys[key]) > max_values:
                    findings.append(Finding(
                        code="HIGH_CARDINALITY_VALUES",
                        severity=SEVERITY_WARNING,
                        attribute=key,
                        services=(service_name,),
                        message="dynamic key %r observed with %d distinct "
                                "values (policy max %d)"
                                % (key, len(keys[key]), max_values),
                        details={
                            "distinct_values": len(keys[key]),
                            "max_values_per_key": max_values,
                        },
                    ))
        return findings
