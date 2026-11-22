"""Data model for schemas, samples and validation input.

Everything is plain dataclasses so the validator stays deterministic and
easy to serialize. Compatible with Python 3.8.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

ALLOWED_TYPES = ("string", "int", "double", "boolean", "string[]", "int[]",
                 "double[]", "boolean[]", "map")


@dataclass(frozen=True)
class AttributeSpec:
    """Declared contract for one attribute of one service."""

    name: str
    type: str
    unit: Optional[str] = None
    enum: Optional[List[Any]] = None
    required: bool = False
    semconv_version: Optional[str] = None
    deprecated: bool = False
    renamed_to: Optional[str] = None

    @staticmethod
    def from_dict(name, data):
        spec_type = data.get("type")
        if spec_type not in ALLOWED_TYPES:
            raise ValueError(
                "attribute %r has unsupported type %r (allowed: %s)"
                % (name, spec_type, ", ".join(ALLOWED_TYPES))
            )
        return AttributeSpec(
            name=name,
            type=spec_type,
            unit=data.get("unit"),
            enum=list(data["enum"]) if data.get("enum") is not None else None,
            required=bool(data.get("required", False)),
            semconv_version=data.get("semconv_version"),
            deprecated=bool(data.get("deprecated", False)),
            renamed_to=data.get("renamed_to"),
        )


@dataclass(frozen=True)
class DualWriteRule:
    """Explicit dual-field allowance during a version migration.

    Both ``old`` and ``new`` may be emitted while consumers migrate, but the
    rule must declare the read priority and a retirement window, otherwise
    the validator flags it as incomplete.
    """

    old: str
    new: str
    read_priority: List[str] = field(default_factory=list)
    retire_after: Optional[str] = None

    @staticmethod
    def from_dict(data):
        return DualWriteRule(
            old=data["old"],
            new=data["new"],
            read_priority=list(data.get("read_priority") or []),
            retire_after=data.get("retire_after"),
        )

    def is_complete(self):
        return bool(self.read_priority) and bool(self.retire_after)


@dataclass(frozen=True)
class DynamicKeyPolicy:
    """Policy for dynamic keys under a prefix or inside a map attribute."""

    prefix: str
    max_keys: int = 50
    max_values_per_key: int = 100

    @staticmethod
    def from_dict(prefix, data):
        return DynamicKeyPolicy(
            prefix=prefix,
            max_keys=int(data.get("max_keys", 50)),
            max_values_per_key=int(data.get("max_values_per_key", 100)),
        )


@dataclass(frozen=True)
class ServiceSchema:
    name: str
    semconv_version: str
    attributes: Dict[str, AttributeSpec] = field(default_factory=dict)
    dual_write: List[DualWriteRule] = field(default_factory=list)
    dynamic_keys: List[DynamicKeyPolicy] = field(default_factory=list)

    @staticmethod
    def from_dict(name, data):
        attributes = {}
        for attr_name, attr_data in (data.get("attributes") or {}).items():
            attributes[attr_name] = AttributeSpec.from_dict(attr_name, attr_data)
        dual_write = [DualWriteRule.from_dict(d)
                      for d in (data.get("dual_write") or [])]
        dynamic_keys = [DynamicKeyPolicy.from_dict(prefix, policy)
                        for prefix, policy in
                        (data.get("dynamic_keys") or {}).items()]
        return ServiceSchema(
            name=name,
            semconv_version=data.get("semconv_version", ""),
            attributes=attributes,
            dual_write=dual_write,
            dynamic_keys=dynamic_keys,
        )

    def find_dual_write(self, attribute_name):
        for rule in self.dual_write:
            if attribute_name in (rule.old, rule.new):
                return rule
        return None


@dataclass(frozen=True)
class SpanSample:
    """One sampled span with resource attributes, events and links."""

    service: str
    name: str = ""
    attributes: Dict[str, Any] = field(default_factory=dict)
    resource: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)
    links: List[Dict[str, Any]] = field(default_factory=list)

    @staticmethod
    def from_dict(data):
        return SpanSample(
            service=data["service"],
            name=data.get("name", ""),
            attributes=dict(data.get("attributes") or {}),
            resource=dict(data.get("resource") or {}),
            events=[dict(e) for e in (data.get("events") or [])],
            links=[dict(l) for l in (data.get("links") or [])],
        )

    def scoped_attributes(self):
        """Yield (scope, attributes) pairs for every telemetry section."""
        yield "span", self.attributes
        yield "resource", self.resource
        for index, event in enumerate(self.events):
            yield "event[%d]" % index, dict(event.get("attributes") or {})
        for index, link in enumerate(self.links):
            yield "link[%d]" % index, dict(link.get("attributes") or {})


@dataclass(frozen=True)
class ValidationInput:
    semconv_version: str
    services: Dict[str, ServiceSchema]
    spans: List[SpanSample]

    @staticmethod
    def from_dict(data):
        services = {
            name: ServiceSchema.from_dict(name, svc)
            for name, svc in (data.get("services") or {}).items()
        }
        spans = [SpanSample.from_dict(s) for s in (data.get("spans") or [])]
        return ValidationInput(
            semconv_version=data.get("semconv_version", ""),
            services=services,
            spans=spans,
        )
