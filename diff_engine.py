from typing import Any, Dict, List, Tuple

from change_model import Change, DiffResult
from fingerprint import apply_fingerprints
from matcher import NodeMatch, match_documents
from prefab_parser import parse_prefab
from risk_classifier import classify_field_change, classify_match, classify_node_add_delete, classify_warning


def diff_prefabs(p_before_file: str, p_after_file: str) -> DiffResult:
    t_before = parse_prefab(p_before_file)
    t_after = parse_prefab(p_after_file)
    apply_fingerprints(t_before)
    apply_fingerprints(t_after)
    t_matches = match_documents(t_before, t_after)
    t_result = DiffResult(before_file=p_before_file, after_file=p_after_file, before_path=p_before_file, after_path=p_after_file)
    t_result.warnings = _warnings_with_side("before", t_before.warnings) + _warnings_with_side("after", t_after.warnings)
    for t_warning in t_result.warnings:
        t_result.changes.append(Change(
            category="warning",
            type=t_warning.get("type", "warning"),
            risk=classify_warning(t_warning),
            details=t_warning,
        ))

    for t_match in t_matches:
        t_result.matches.append(_match_to_dict(t_match))
        _diff_match(t_result, t_match)

    t_result.summary = _summary(t_result, t_matches)
    return t_result


def _diff_match(p_result: DiffResult, p_match: NodeMatch) -> None:
    if p_match.before is None and p_match.after is not None:
        p_result.changes.append(Change(
            category="node",
            type="added",
            risk=classify_node_add_delete(p_match.after, p_match.status),
            after_path=p_match.after.path,
            after_internal_path=p_match.after.internal_path,
            details={"node": _node_brief(p_match.after)},
        ))
        return
    if p_match.before is not None and p_match.after is None:
        p_result.changes.append(Change(
            category="node",
            type="deleted",
            risk=classify_node_add_delete(p_match.before, p_match.status),
            before_path=p_match.before.path,
            before_internal_path=p_match.before.internal_path,
            details={"node": _node_brief(p_match.before)},
        ))
        return

    t_before = p_match.before
    t_after = p_match.after
    t_match_risk = classify_match(p_match)
    if p_match.status in ("uncertain", "ambiguous"):
        p_result.changes.append(Change(
            category="match",
            type=p_match.status,
            risk=t_match_risk,
            before_path=t_before.path,
            after_path=t_after.path,
            before_internal_path=t_before.internal_path,
            after_internal_path=t_after.internal_path,
            confidence=p_match.confidence,
            details={"reasons": p_match.reasons, "alternatives": p_match.alternatives, "score": p_match.score},
        ))

    if t_before.path != t_after.path or t_before.name != t_after.name:
        t_parent_moved = t_before.parent_path != t_after.parent_path
        if t_parent_moved and t_before.name != t_after.name:
            t_type = "moved_and_renamed"
        elif t_parent_moved:
            t_type = "moved"
        else:
            t_type = "renamed"
        p_result.changes.append(Change(
            category="node",
            type=t_type,
            risk=t_match_risk,
            before_path=t_before.path,
            after_path=t_after.path,
            before_internal_path=t_before.internal_path,
            after_internal_path=t_after.internal_path,
            confidence=p_match.confidence,
            details={"before_name": t_before.name, "after_name": t_after.name, "reasons": p_match.reasons, "score": p_match.score},
        ))

    _diff_props(p_result, t_before, t_after, "node.props", t_before.props, t_after.props, p_match.confidence)
    _diff_resources(p_result, t_before, t_after, p_match.confidence)
    _diff_events(p_result, t_before, t_after, p_match.confidence)
    _diff_components(p_result, t_before, t_after, p_match.confidence)
    _diff_child_order(p_result, t_before, t_after, p_match.confidence)


def _diff_props(p_result: DiffResult, p_before_node, p_after_node, p_prefix: str, p_before: Dict[str, Any], p_after: Dict[str, Any], p_confidence: int) -> None:
    for t_key in sorted(set(p_before.keys()) | set(p_after.keys())):
        t_before_value = p_before.get(t_key)
        t_after_value = p_after.get(t_key)
        if t_before_value == t_after_value:
            continue
        t_field = p_prefix + "." + t_key
        p_result.changes.append(Change(
            category="field",
            type="changed",
            risk=classify_field_change(t_field, t_before_value, t_after_value),
            before_path=p_before_node.path,
            after_path=p_after_node.path,
            before_internal_path=p_before_node.internal_path,
            after_internal_path=p_after_node.internal_path,
            field=t_field,
            before=t_before_value,
            after=t_after_value,
            confidence=p_confidence,
        ))


def _diff_resources(p_result: DiffResult, p_before_node, p_after_node, p_confidence: int) -> None:
    t_before = _resource_map(p_before_node)
    t_after = _resource_map(p_after_node)
    for t_key in sorted(set(t_before.keys()) | set(t_after.keys())):
        if t_before.get(t_key) == t_after.get(t_key):
            continue
        p_result.changes.append(Change(
            category="resource",
            type="changed",
            risk=classify_field_change(t_key, t_before.get(t_key), t_after.get(t_key)),
            before_path=p_before_node.path,
            after_path=p_after_node.path,
            before_internal_path=p_before_node.internal_path,
            after_internal_path=p_after_node.internal_path,
            field=t_key,
            before=t_before.get(t_key),
            after=t_after.get(t_key),
            confidence=p_confidence,
        ))


def _diff_events(p_result: DiffResult, p_before_node, p_after_node, p_confidence: int) -> None:
    t_before = p_before_node.events
    t_after = p_after_node.events
    if t_before == t_after:
        return
    p_result.changes.append(Change(
        category="event",
        type="changed",
        risk=classify_field_change("clickEvents", t_before, t_after),
        before_path=p_before_node.path,
        after_path=p_after_node.path,
        before_internal_path=p_before_node.internal_path,
        after_internal_path=p_after_node.internal_path,
        field="clickEvents",
        before=t_before,
        after=t_after,
        confidence=p_confidence,
    ))


def _diff_components(p_result: DiffResult, p_before_node, p_after_node, p_confidence: int) -> None:
    t_before_types = p_before_node.component_types()
    t_after_types = p_after_node.component_types()
    if t_before_types != t_after_types and sorted(t_before_types) == sorted(t_after_types):
        p_result.changes.append(Change(
            category="component",
            type="order_changed",
            risk="low",
            before_path=p_before_node.path,
            after_path=p_after_node.path,
            before_internal_path=p_before_node.internal_path,
            after_internal_path=p_after_node.internal_path,
            before=t_before_types,
            after=t_after_types,
            confidence=p_confidence,
        ))
    for t_key, t_before_component, t_after_component in _pair_components(p_before_node, p_after_node):
        if t_before_component is None:
            p_result.changes.append(Change(
                category="component",
                type="added",
                risk="high" if t_after_component.is_script or t_after_component.events else "medium",
                after_path=p_after_node.path,
                after_internal_path=p_after_node.internal_path,
                field=t_key,
                after=t_after_component.type_name,
                confidence=p_confidence,
            ))
        elif t_after_component is None:
            p_result.changes.append(Change(
                category="component",
                type="deleted",
                risk="high" if t_before_component.is_script or t_before_component.events else "medium",
                before_path=p_before_node.path,
                before_internal_path=p_before_node.internal_path,
                field=t_key,
                before=t_before_component.type_name,
                confidence=p_confidence,
            ))
        else:
            _diff_props(p_result, p_before_node, p_after_node, "component.%s.props" % t_key, t_before_component.props, t_after_component.props, p_confidence)


def _diff_child_order(p_result: DiffResult, p_before_node, p_after_node, p_confidence: int) -> None:
    t_before = [t_child.name for t_child in p_before_node.children]
    t_after = [t_child.name for t_child in p_after_node.children]
    if t_before != t_after and sorted(t_before) == sorted(t_after):
        p_result.changes.append(Change(
            category="node",
            type="child_order_changed",
            risk="low",
            before_path=p_before_node.path,
            after_path=p_after_node.path,
            before_internal_path=p_before_node.internal_path,
            after_internal_path=p_after_node.internal_path,
            before=t_before,
            after=t_after,
            confidence=p_confidence,
        ))


def _pair_components(p_before_node, p_after_node) -> List[Tuple[str, Any, Any]]:
    t_before = {}
    t_after = {}
    for t_component in p_before_node.components:
        t_before.setdefault(t_component.type_name, []).append(t_component)
    for t_component in p_after_node.components:
        t_after.setdefault(t_component.type_name, []).append(t_component)
    t_pairs = []
    for t_type in sorted(set(t_before.keys()) | set(t_after.keys())):
        t_before_list = t_before.get(t_type, [])
        t_after_list = t_after.get(t_type, [])
        t_count = max(len(t_before_list), len(t_after_list))
        for t_index in range(t_count):
            t_pairs.append(("%s#%s" % (t_type, t_index), t_before_list[t_index] if t_index < len(t_before_list) else None, t_after_list[t_index] if t_index < len(t_after_list) else None))
    return t_pairs


def _resource_map(p_node) -> Dict[str, str]:
    t_map = {}
    for t_item in p_node.resources:
        t_key = "%s.%s" % (t_item.get("component"), t_item.get("field"))
        t_map[t_key] = t_item.get("uuid")
    return t_map


def _match_to_dict(p_match: NodeMatch) -> Dict[str, Any]:
    t_value = {
        "status": p_match.status,
        "confidence": p_match.confidence,
        "before_path": p_match.before.path if p_match.before else None,
        "after_path": p_match.after.path if p_match.after else None,
        "before_internal_path": p_match.before.internal_path if p_match.before else None,
        "after_internal_path": p_match.after.internal_path if p_match.after else None,
        "reasons": p_match.reasons,
        "alternatives": p_match.alternatives,
    }
    if p_match.score is not None:
        t_value["score"] = p_match.score
    return t_value


def _node_brief(p_node) -> Dict[str, Any]:
    return {
        "name": p_node.name,
        "path": p_node.path,
        "internal_path": p_node.internal_path,
        "components": p_node.component_types(),
        "scripts": p_node.script_types(),
        "resources": p_node.resources,
        "events": p_node.events,
    }


def _warnings_with_side(p_side: str, p_warnings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    t_values = []
    for t_warning in p_warnings:
        t_value = dict(t_warning)
        t_value["side"] = p_side
        t_values.append(t_value)
    return t_values


def _summary(p_result: DiffResult, p_matches: List[NodeMatch]) -> Dict[str, Any]:
    t_by_risk = {}
    t_by_category = {}
    t_by_type = {}
    for t_change in p_result.changes:
        t_by_risk[t_change.risk] = t_by_risk.get(t_change.risk, 0) + 1
        t_by_category[t_change.category] = t_by_category.get(t_change.category, 0) + 1
        t_by_type[t_change.type] = t_by_type.get(t_change.type, 0) + 1
    return {
        "change_count": len(p_result.changes),
        "match_count": len(p_matches),
        "by_risk": t_by_risk,
        "by_category": t_by_category,
        "by_type": t_by_type,
    }
