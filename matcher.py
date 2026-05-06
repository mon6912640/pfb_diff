from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from config import AMBIGUOUS_DELTA, CONFIRMED_SCORE, LOW_INFO_NODE_NAMES, PROBABLE_SCORE, UNCERTAIN_SCORE
from prefab_model import PrefabDocument, PrefabNode


@dataclass
class NodeMatch:
    before: Optional[PrefabNode]
    after: Optional[PrefabNode]
    status: str
    confidence: int = 0
    reasons: List[str] = field(default_factory=list)
    alternatives: List[Dict[str, object]] = field(default_factory=list)


def match_documents(p_before: PrefabDocument, p_after: PrefabDocument) -> List[NodeMatch]:
    t_matches = []
    t_unmatched_before = list(p_before.nodes)
    t_unmatched_after = list(p_after.nodes)
    t_candidate_index = _build_candidate_index(t_unmatched_after)

    for t_before in list(t_unmatched_before):
        t_after = _find_exact_identity(t_before, t_unmatched_after)
        if t_after:
            t_matches.append(NodeMatch(t_before, t_after, "confirmed", 100, ["same_identity_hash"]))
            t_unmatched_before.remove(t_before)
            t_unmatched_after.remove(t_after)

    for t_before in list(t_unmatched_before):
        t_candidates = _candidate_nodes(t_before, t_unmatched_after, t_candidate_index)
        t_ranked = _rank_candidates(t_before, t_candidates)
        if not t_ranked:
            continue
        t_after, t_score, t_reasons = t_ranked[0]
        t_second_score = t_ranked[1][1] if len(t_ranked) > 1 else -1
        t_status = _status_from_score(t_score, t_second_score)
        if t_status == "unmatched":
            continue
        t_matches.append(NodeMatch(
            t_before,
            t_after,
            t_status,
            t_score,
            t_reasons,
            _alternatives(t_ranked[1:5]),
        ))
        t_unmatched_before.remove(t_before)
        t_unmatched_after.remove(t_after)

    for t_before in t_unmatched_before:
        t_matches.append(NodeMatch(t_before, None, "unmatched", 0, ["deleted"]))
    for t_after in t_unmatched_after:
        t_matches.append(NodeMatch(None, t_after, "unmatched", 0, ["added"]))

    return t_matches


def _build_candidate_index(p_after_nodes: List[PrefabNode]) -> Dict[str, Dict[str, List[PrefabNode]]]:
    t_index = {
        "script": {},
        "component": {},
        "resource": {},
        "label": {},
        "name": {},
    }
    for t_node in p_after_nodes:
        _index_add(t_index["name"], t_node.name, t_node)
        for t_value in t_node.script_types():
            _index_add(t_index["script"], t_value, t_node)
        for t_value in t_node.component_types():
            _index_add(t_index["component"], t_value, t_node)
        for t_value in _resources(t_node):
            _index_add(t_index["resource"], t_value, t_node)
        for t_value in _label_texts(t_node):
            _index_add(t_index["label"], t_value, t_node)
    return t_index


def _candidate_nodes(p_before: PrefabNode, p_all_after: List[PrefabNode], p_index: Dict[str, Dict[str, List[PrefabNode]]]) -> List[PrefabNode]:
    t_candidates = []
    t_seen = set()
    t_features = [
        ("name", [p_before.name]),
        ("script", p_before.script_types()),
        ("component", p_before.component_types()),
        ("resource", _resources(p_before)),
        ("label", _label_texts(p_before)),
    ]
    for t_bucket, t_values in t_features:
        for t_value in t_values:
            for t_node in p_index.get(t_bucket, {}).get(t_value, []):
                if id(t_node) in t_seen:
                    continue
                t_seen.add(id(t_node))
                t_candidates.append(t_node)
    if not t_candidates:
        return p_all_after
    return [t_node for t_node in t_candidates if t_node in p_all_after]


def _index_add(p_bucket: Dict[str, List[PrefabNode]], p_key: str, p_node: PrefabNode) -> None:
    p_bucket.setdefault(str(p_key), []).append(p_node)


def _find_exact_identity(p_before: PrefabNode, p_after_nodes: List[PrefabNode]) -> Optional[PrefabNode]:
    for t_after in p_after_nodes:
        if p_before.fingerprint.identity_hash == t_after.fingerprint.identity_hash:
            return t_after
    return None


def _rank_candidates(p_before: PrefabNode, p_after_nodes: List[PrefabNode]) -> List[Tuple[PrefabNode, int, List[str]]]:
    t_ranked = []
    for t_after in p_after_nodes:
        t_score, t_reasons = _score_pair(p_before, t_after)
        if t_score >= UNCERTAIN_SCORE:
            t_ranked.append((t_after, t_score, t_reasons))
    return sorted(t_ranked, key=lambda p_item: p_item[1], reverse=True)


def _score_pair(p_before: PrefabNode, p_after: PrefabNode) -> Tuple[int, List[str]]:
    t_score = 0
    t_reasons = []
    if p_before.name == p_after.name:
        t_score += 12
        t_reasons.append("same_name")
    elif _is_low_info(p_before.name) or _is_low_info(p_after.name):
        t_score -= 4
        t_reasons.append("low_info_name")

    if p_before.fingerprint.structure_hash == p_after.fingerprint.structure_hash:
        t_score += 18
        t_reasons.append("same_structure_hash")
    else:
        t_score += _overlap_score(p_before.component_types(), p_after.component_types(), 18, "component_overlap", t_reasons)
        t_score += _overlap_score([t_child.name for t_child in p_before.children], [t_child.name for t_child in p_after.children], 8, "child_name_overlap", t_reasons)

    if p_before.fingerprint.visual_hash == p_after.fingerprint.visual_hash:
        t_score += 20
        t_reasons.append("same_visual_hash")
    else:
        t_score += _overlap_score(_resources(p_before), _resources(p_after), 18, "resource_overlap", t_reasons)
        t_score += _overlap_score(_label_texts(p_before), _label_texts(p_after), 14, "label_overlap", t_reasons)

    if p_before.fingerprint.behavior_hash == p_after.fingerprint.behavior_hash:
        t_score += 22
        t_reasons.append("same_behavior_hash")
    else:
        t_score += _overlap_score(p_before.script_types(), p_after.script_types(), 18, "script_overlap", t_reasons)
        t_score += _overlap_score(_events(p_before), _events(p_after), 18, "event_overlap", t_reasons)

    if p_before.parent_path == p_after.parent_path:
        t_score += 8
        t_reasons.append("same_parent_path")
    if p_before.path == p_after.path:
        t_score += 8
        t_reasons.append("same_path")
    if p_before.sibling_index == p_after.sibling_index:
        t_score += 4
        t_reasons.append("same_sibling_index")

    if not p_before.component_types() and not p_after.component_types() and _is_low_info(p_before.name) and _is_low_info(p_after.name):
        t_score -= 18
        t_reasons.append("low_information_node_penalty")

    return max(0, min(100, t_score)), t_reasons


def _status_from_score(p_score: int, p_second_score: int) -> str:
    if p_second_score >= 0 and p_score - p_second_score <= AMBIGUOUS_DELTA:
        return "ambiguous"
    if p_score >= CONFIRMED_SCORE:
        return "confirmed"
    if p_score >= PROBABLE_SCORE:
        return "probable"
    if p_score >= UNCERTAIN_SCORE:
        return "uncertain"
    return "unmatched"


def _overlap_score(p_left: List[str], p_right: List[str], p_weight: int, p_reason: str, p_reasons: List[str]) -> int:
    if not p_left or not p_right:
        return 0
    t_left = set([str(t_item) for t_item in p_left])
    t_right = set([str(t_item) for t_item in p_right])
    t_union = t_left | t_right
    if not t_union:
        return 0
    t_score = int(round(p_weight * (float(len(t_left & t_right)) / float(len(t_union)))))
    if t_score:
        p_reasons.append(p_reason)
    return t_score


def _resources(p_node: PrefabNode) -> List[str]:
    return [str(t_item.get("uuid")) for t_item in p_node.resources if t_item.get("uuid")]


def _label_texts(p_node: PrefabNode) -> List[str]:
    t_values = []
    for t_component in p_node.components:
        if t_component.type_name == "cc.Label":
            for t_key in ["_N$string", "_string", "string"]:
                if t_key in t_component.props:
                    t_values.append(str(t_component.props.get(t_key)))
    return t_values


def _events(p_node: PrefabNode) -> List[str]:
    return ["%s.%s" % (t_item.get("component_name") or "", t_item.get("handler") or "") for t_item in p_node.events]


def _is_low_info(p_name: str) -> bool:
    return str(p_name).lower() in LOW_INFO_NODE_NAMES


def _alternatives(p_ranked: List[Tuple[PrefabNode, int, List[str]]]) -> List[Dict[str, object]]:
    return [{
        "path": t_after.path,
        "internal_path": t_after.internal_path,
        "score": t_score,
        "reasons": t_reasons,
    } for t_after, t_score, t_reasons in p_ranked]
