"""Migration plan generation from validation findings.

The planner turns renames, unit changes and type conflicts into an explicit
three-phase plan. Dual fields are only allowed during the migration window
and every dual-write step carries a read priority and a retirement window.
Planning is deterministic and idempotent: the same findings always produce
the same phases with no duplicated steps.
"""

from typing import Any, Dict, List

DEFAULT_RETIRE_AFTER = "2 releases"

PHASE_DUAL_WRITE = "dual-write"
PHASE_CONSUMER_SWITCH = "consumer-switch"
PHASE_RETIRE = "retire"


class MigrationPlanner:
    def plan(self, data, findings) -> List[Dict[str, Any]]:
        renames = self._collect_renames(data, findings)
        unit_changes = self._collect_unit_changes(findings)

        phases = []  # type: List[Dict[str, Any]]
        dual_steps = []
        switch_steps = []
        retire_steps = []

        for item in renames:
            dual_steps.append({
                "action": "emit_both",
                "old": item["old"],
                "new": item["new"],
                "services": item["services"],
                "read_priority": item["read_priority"],
                "retire_after": item["retire_after"],
            })
            switch_steps.append({
                "action": "read_from",
                "attribute": item["new"],
                "fallback": item["old"],
                "services": item["services"],
            })
            retire_steps.append({
                "action": "drop_attribute",
                "attribute": item["old"],
                "after": item["retire_after"],
                "services": item["services"],
            })

        for item in unit_changes:
            dual_steps.append({
                "action": "convert_unit",
                "attribute": item["attribute"],
                "from_unit": item["from_unit"],
                "to_unit": item["to_unit"],
                "factor": item["factor"],
                "services": item["services"],
                "note": "conversion must be applied explicitly by the "
                        "producer; consumers must not assume a unit",
            })
            retire_steps.append({
                "action": "enforce_unit",
                "attribute": item["attribute"],
                "unit": item["to_unit"],
                "after": DEFAULT_RETIRE_AFTER,
                "services": item["services"],
            })

        if dual_steps:
            phases.append({"phase": 1, "name": PHASE_DUAL_WRITE,
                           "steps": dual_steps})
        if switch_steps:
            phases.append({"phase": 2, "name": PHASE_CONSUMER_SWITCH,
                           "steps": switch_steps})
        if retire_steps:
            phases.append({"phase": 3, "name": PHASE_RETIRE,
                           "steps": retire_steps})
        return phases

    def _collect_renames(self, data, findings):
        """One rename entry per (old, new) pair, deduplicated."""
        entries = {}
        for service_name, schema in sorted(data.services.items()):
            for rule in schema.dual_write:
                key = (rule.old, rule.new)
                entry = entries.setdefault(key, {
                    "old": rule.old,
                    "new": rule.new,
                    "services": [],
                    "read_priority": list(rule.read_priority) or [
                        rule.new, rule.old],
                    "retire_after": rule.retire_after or DEFAULT_RETIRE_AFTER,
                })
                if service_name not in entry["services"]:
                    entry["services"].append(service_name)
            for attr_name, spec in sorted(schema.attributes.items()):
                if spec.renamed_to:
                    key = (attr_name, spec.renamed_to)
                    entry = entries.setdefault(key, {
                        "old": attr_name,
                        "new": spec.renamed_to,
                        "services": [],
                        "read_priority": [spec.renamed_to, attr_name],
                        "retire_after": DEFAULT_RETIRE_AFTER,
                    })
                    if service_name not in entry["services"]:
                        entry["services"].append(service_name)
        for finding in findings:
            if finding.code == "RENAMED_ATTRIBUTE":
                old = finding.details.get("old")
                new = finding.details.get("new")
                if old and new and (old, new) not in entries:
                    entries[(old, new)] = {
                        "old": old,
                        "new": new,
                        "services": list(finding.services),
                        "read_priority": [new, old],
                        "retire_after": DEFAULT_RETIRE_AFTER,
                    }
        result = [entries[key] for key in sorted(entries)]
        for entry in result:
            entry["services"] = sorted(entry["services"])
        return result

    def _collect_unit_changes(self, findings):
        changes = {}
        for finding in findings:
            if finding.code != "UNIT_MISMATCH":
                continue
            conversion = finding.details.get("conversion") or {}
            key = (finding.attribute, conversion.get("to"))
            if key in changes:
                continue
            changes[key] = {
                "attribute": finding.attribute,
                "from_unit": conversion.get("from"),
                "to_unit": conversion.get("to"),
                "factor": conversion.get("factor"),
                "services": list(finding.services),
            }
        return [changes[key] for key in sorted(changes)]
