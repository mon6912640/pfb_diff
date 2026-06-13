from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

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
    score: Optional[Dict[str, Any]] = None


@dataclass
class ScorePart:
    kind: str
    reason: str
    value: int
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        t_value = {
            "kind": self.kind,
            "reason": self.reason,
            "value": self.value,
        }
        if self.details:
            t_value["details"] = self.details
        return t_value


@dataclass
class MatchScore:
    total: int
    reasons: List[str] = field(default_factory=list)
    parts: List[ScorePart] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "reasons": list(self.reasons),
            "parts": [t_part.to_dict() for t_part in self.parts],
        }


class ScoreBuilder:
    def __init__(self) -> None:
        self.total = 0
        self.reasons: List[str] = []
        self.parts: List[ScorePart] = []

    @classmethod
    def from_score(cls, p_score: MatchScore) -> "ScoreBuilder":
        t_builder = cls()
        t_builder.total = p_score.total
        t_builder.reasons = list(p_score.reasons)
        t_builder.parts = list(p_score.parts)
        return t_builder

    def add(self, p_reason: str, p_value: int, p_details: Optional[Dict[str, Any]] = None) -> None:
        self._add_part("add", p_reason, p_value, p_details)
        self.total += p_value

    def penalty(self, p_reason: str, p_value: int, p_details: Optional[Dict[str, Any]] = None) -> None:
        t_value = -abs(p_value)
        self._add_part("penalty", p_reason, t_value, p_details)
        self.total += t_value

    def overlap(self, p_left: List[str], p_right: List[str], p_weight: int, p_reason: str) -> None:
        if not p_left or not p_right:
            return
        t_left = set([str(t_item) for t_item in p_left])
        t_right = set([str(t_item) for t_item in p_right])
        t_union = t_left | t_right
        if not t_union:
            return
        t_intersection = t_left & t_right
        t_score = int(round(p_weight * (float(len(t_intersection)) / float(len(t_union)))))
        if not t_score:
            return
        self._add_part("overlap", p_reason, t_score, {
            "weight": p_weight,
            "intersection": len(t_intersection),
            "union": len(t_union),
        })
        self.total += t_score

    def cap(self, p_reason: str, p_value: int) -> None:
        t_before = self.total
        self.total = min(self.total, p_value)
        self._add_part("cap", p_reason, p_value, {"before": t_before, "after": self.total})

    def floor(self, p_reason: str, p_value: int) -> None:
        t_before = self.total
        self.total = max(self.total, p_value)
        self._add_part("floor", p_reason, p_value, {"before": t_before, "after": self.total})

    def identity(self, p_reason: str, p_value: int) -> None:
        self._add_part("identity", p_reason, p_value)
        self.total = p_value

    def info(self, p_reason: str, p_details: Optional[Dict[str, Any]] = None) -> None:
        self._add_part("info", p_reason, 0, p_details)

    def build(self) -> MatchScore:
        self.total = max(0, min(100, self.total))
        return MatchScore(self.total, list(self.reasons), list(self.parts))

    def _add_part(self, p_kind: str, p_reason: str, p_value: int, p_details: Optional[Dict[str, Any]] = None) -> None:
        self.parts.append(ScorePart(p_kind, p_reason, p_value, p_details or {}))
        if p_reason not in self.reasons:
            self.reasons.append(p_reason)


def match_documents(p_before: PrefabDocument, p_after: PrefabDocument) -> List[NodeMatch]:
    t_matches = []
    t_unmatched_before = list(p_before.nodes)
    t_unmatched_after = list(p_after.nodes)

    for t_before in list(t_unmatched_before):
        t_after, t_score = _find_same_internal_path_anchor(t_before, t_unmatched_after)
        if t_after:
            t_matches.append(_node_match(t_before, t_after, _status_from_score(t_score.total, -1), t_score))
            t_unmatched_before.remove(t_before)
            t_unmatched_after.remove(t_after)

    t_before_path_counts = _path_counts(t_unmatched_before)
    t_after_path_counts = _path_counts(t_unmatched_after)
    for t_before in list(t_unmatched_before):
        t_after, t_score = _find_same_path_anchor(t_before, t_unmatched_after, t_before_path_counts, t_after_path_counts)
        if t_after:
            t_matches.append(_node_match(t_before, t_after, _status_from_score(t_score.total, -1), t_score))
            t_unmatched_before.remove(t_before)
            t_unmatched_after.remove(t_after)

    t_before_identity_counts = _identity_counts(t_unmatched_before)
    t_after_identity_counts = _identity_counts(t_unmatched_after)
    for t_before in list(t_unmatched_before):
        t_after, t_score = _find_exact_identity(t_before, t_unmatched_after, t_before_identity_counts, t_after_identity_counts)
        if t_after:
            t_matches.append(_node_match(t_before, t_after, "confirmed", t_score))
            t_unmatched_before.remove(t_before)
            t_unmatched_after.remove(t_after)

    t_candidate_index = _build_candidate_index(t_unmatched_after)
    for t_before in list(t_unmatched_before):
        t_candidates = _candidate_nodes(t_before, t_unmatched_after, t_candidate_index)
        t_ranked = _rank_candidates(t_before, t_candidates, t_matches, t_before_identity_counts, t_after_identity_counts)
        if not t_ranked:
            continue
        t_after, t_score = t_ranked[0]
        t_second_score = t_ranked[1][1].total if len(t_ranked) > 1 else -1
        t_status = _status_from_score(t_score.total, t_second_score)
        if t_status == "unmatched":
            continue
        t_matches.append(_node_match(
            t_before,
            t_after,
            t_status,
            t_score,
            _alternatives(t_ranked[1:5]),
        ))
        t_unmatched_before.remove(t_before)
        t_unmatched_after.remove(t_after)

    for t_before in t_unmatched_before:
        t_matches.append(NodeMatch(t_before, None, "unmatched", 0, ["deleted"]))
    for t_after in t_unmatched_after:
        t_matches.append(NodeMatch(None, t_after, "unmatched", 0, ["added"]))

    return t_matches


def _node_match(
    p_before: Optional[PrefabNode],
    p_after: Optional[PrefabNode],
    p_status: str,
    p_score: MatchScore,
    p_alternatives: Optional[List[Dict[str, object]]] = None,
) -> NodeMatch:
    return NodeMatch(
        p_before,
        p_after,
        p_status,
        p_score.total,
        list(p_score.reasons),
        p_alternatives or [],
        p_score.to_dict(),
    )


def _identity_counts(p_nodes: List[PrefabNode]) -> Dict[str, int]:
    t_counts = {}
    for t_node in p_nodes:
        t_hash = t_node.fingerprint.identity_hash
        t_counts[t_hash] = t_counts.get(t_hash, 0) + 1
    return t_counts


def _path_counts(p_nodes: List[PrefabNode]) -> Dict[str, int]:
    t_counts = {}
    for t_node in p_nodes:
        t_counts[t_node.path] = t_counts.get(t_node.path, 0) + 1
    return t_counts


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


def _find_same_internal_path_anchor(p_before: PrefabNode, p_after_nodes: List[PrefabNode]) -> Tuple[Optional[PrefabNode], MatchScore]:
    for t_after in p_after_nodes:
        if p_before.internal_path != t_after.internal_path:
            continue
        t_score = _score_pair(p_before, t_after)
        if _is_safe_same_path_match(p_before, t_after):
            t_builder = ScoreBuilder.from_score(t_score)
            t_builder.info("same_internal_path_anchor")
            t_builder.floor("same_internal_path_anchor_floor", PROBABLE_SCORE)
            return t_after, t_builder.build()
    return None, MatchScore(0, [], [])


def _find_same_path_anchor(
    p_before: PrefabNode,
    p_after_nodes: List[PrefabNode],
    p_before_path_counts: Dict[str, int],
    p_after_path_counts: Dict[str, int],
) -> Tuple[Optional[PrefabNode], MatchScore]:
    if p_before_path_counts.get(p_before.path, 0) != 1 or p_after_path_counts.get(p_before.path, 0) != 1:
        return None, MatchScore(0, [], [])
    for t_after in p_after_nodes:
        if p_before.path != t_after.path:
            continue
        t_score = _score_pair(p_before, t_after)
        if _is_safe_same_path_match(p_before, t_after):
            t_builder = ScoreBuilder.from_score(t_score)
            t_builder.info("same_path_anchor")
            t_builder.floor("same_path_anchor_floor", PROBABLE_SCORE)
            return t_after, t_builder.build()
    return None, MatchScore(0, [], [])


def _is_safe_same_path_match(p_before: PrefabNode, p_after: PrefabNode) -> bool:
    if p_before.path != p_after.path or p_before.name != p_after.name:
        return False
    if p_before.fingerprint.identity_hash == p_after.fingerprint.identity_hash:
        return True
    if p_before.fingerprint.structure_hash == p_after.fingerprint.structure_hash:
        return True
    if p_before.fingerprint.visual_hash == p_after.fingerprint.visual_hash:
        return True
    if set(p_before.component_types()) & set(p_after.component_types()):
        return True
    if set(p_before.script_types()) & set(p_after.script_types()):
        return True
    if set(_resources(p_before)) & set(_resources(p_after)):
        return True
    if set(_label_texts(p_before)) & set(_label_texts(p_after)):
        return True
    if set([t_child.name for t_child in p_before.children]) & set([t_child.name for t_child in p_after.children]):
        return True
    return False


def _find_exact_identity(
    p_before: PrefabNode,
    p_after_nodes: List[PrefabNode],
    p_before_identity_counts: Dict[str, int],
    p_after_identity_counts: Dict[str, int],
) -> Tuple[Optional[PrefabNode], MatchScore]:
    t_hash = p_before.fingerprint.identity_hash
    if p_before_identity_counts.get(t_hash, 0) != 1 or p_after_identity_counts.get(t_hash, 0) != 1:
        return None, MatchScore(0, [], [])
    if not _has_strong_identity_features(p_before):
        return None, MatchScore(0, [], [])
    t_matches = [
        t_after for t_after in p_after_nodes
        if t_hash == t_after.fingerprint.identity_hash
    ]
    if not t_matches:
        return None, MatchScore(0, [], [])
    t_builder = ScoreBuilder()
    t_builder.identity("same_unique_identity_hash", 100)
    return t_matches[0], t_builder.build()


def _rank_candidates(
    p_before: PrefabNode,
    p_after_nodes: List[PrefabNode],
    p_existing_matches: List[NodeMatch],
    p_before_identity_counts: Dict[str, int],
    p_after_identity_counts: Dict[str, int],
) -> List[Tuple[PrefabNode, MatchScore]]:
    t_ranked = []
    t_parent_map = _matched_parent_map(p_existing_matches)
    for t_after in p_after_nodes:
        t_score = _score_pair(p_before, t_after, t_parent_map)
        if _is_duplicate_identity_pair(p_before, t_after, p_before_identity_counts, p_after_identity_counts):
            t_builder = ScoreBuilder.from_score(t_score)
            t_builder.cap("duplicate_identity_cap", CONFIRMED_SCORE - 1)
            t_builder.info("duplicate_identity")
            t_score = t_builder.build()
        if t_score.total >= UNCERTAIN_SCORE:
            t_ranked.append((t_after, t_score))
    return sorted(t_ranked, key=lambda p_item: p_item[1].total, reverse=True)


def _matched_parent_map(p_matches: List[NodeMatch]) -> Dict[str, str]:
    t_map = {}
    for t_match in p_matches:
        if t_match.before is not None and t_match.after is not None:
            t_map[t_match.before.path] = t_match.after.path
    return t_map


def _is_duplicate_identity_pair(
    p_before: PrefabNode,
    p_after: PrefabNode,
    p_before_identity_counts: Dict[str, int],
    p_after_identity_counts: Dict[str, int],
) -> bool:
    if p_before.fingerprint.identity_hash != p_after.fingerprint.identity_hash:
        return False
    t_hash = p_before.fingerprint.identity_hash
    return p_before_identity_counts.get(t_hash, 0) > 1 or p_after_identity_counts.get(t_hash, 0) > 1


def _has_strong_identity_features(p_node: PrefabNode) -> bool:
    return bool(p_node.script_types() or _resources(p_node) or _label_texts(p_node) or _events(p_node))


def _score_pair(p_before: PrefabNode, p_after: PrefabNode, p_parent_map: Optional[Dict[str, str]] = None) -> MatchScore:
    t_score = ScoreBuilder()
    t_same_name = p_before.name == p_after.name
    if t_same_name:
        t_score.add("same_name", 12)
    elif _is_low_info(p_before.name) or _is_low_info(p_after.name):
        t_score.penalty("low_info_name", 4)

    # same_*_hash 仅在底层特征域非空、或两节点同名时才发放：
    # 否则两个空容器的"空 == 空"会被当成相似证据（hash 匹配等价于双方特征
    # 集相同，故只需检查 before 一侧）。同名放行保留了同名节点被重构的场景
    # （如 cc.Label → cc.RichText），避免把同一节点误拆成删除+新增。
    t_has_structure = bool(p_before.component_types() or p_before.children)
    if p_before.fingerprint.structure_hash == p_after.fingerprint.structure_hash and (t_has_structure or t_same_name):
        t_score.add("same_structure_hash", 18)
    else:
        t_score.overlap(p_before.component_types(), p_after.component_types(), 18, "component_overlap")
        t_score.overlap([t_child.name for t_child in p_before.children], [t_child.name for t_child in p_after.children], 8, "child_name_overlap")

    t_has_visual = bool(_resources(p_before) or _label_texts(p_before))
    if p_before.fingerprint.visual_hash == p_after.fingerprint.visual_hash and (t_has_visual or t_same_name):
        t_score.add("same_visual_hash", 20)
    else:
        t_score.overlap(_resources(p_before), _resources(p_after), 18, "resource_overlap")
        t_score.overlap(_label_texts(p_before), _label_texts(p_after), 14, "label_overlap")

    t_has_behavior = bool(p_before.script_types() or _events(p_before))
    if p_before.fingerprint.behavior_hash == p_after.fingerprint.behavior_hash and (t_has_behavior or t_same_name):
        t_score.add("same_behavior_hash", 22)
    else:
        t_score.overlap(p_before.script_types(), p_after.script_types(), 18, "script_overlap")
        t_score.overlap(_events(p_before), _events(p_after), 18, "event_overlap")

    if p_before.parent_path == p_after.parent_path:
        t_score.add("same_parent_path", 8)
    if p_before.path == p_after.path:
        t_score.add("same_path", 8)
    if p_before.sibling_index == p_after.sibling_index:
        t_score.add("same_sibling_index", 4)

    if p_parent_map and p_before.parent_path in p_parent_map:
        t_expected_after_parent = p_parent_map[p_before.parent_path]
        if t_expected_after_parent == p_after.parent_path:
            t_score.add("matched_parent", 14)
        elif not _has_strong_content_match(p_before, p_after):
            t_score.penalty("different_matched_parent", 10)

    if not p_before.component_types() and not p_after.component_types() and _is_low_info(p_before.name) and _is_low_info(p_after.name):
        t_score.penalty("low_information_node_penalty", 18)

    return t_score.build()


def _has_strong_content_match(p_before: PrefabNode, p_after: PrefabNode) -> bool:
    t_same_hashes = 0
    for t_before_hash, t_after_hash in (
        (p_before.fingerprint.structure_hash, p_after.fingerprint.structure_hash),
        (p_before.fingerprint.visual_hash, p_after.fingerprint.visual_hash),
        (p_before.fingerprint.behavior_hash, p_after.fingerprint.behavior_hash),
    ):
        if t_before_hash == t_after_hash:
            t_same_hashes += 1
    return t_same_hashes >= 2


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


def _alternatives(p_ranked: List[Tuple[PrefabNode, MatchScore]]) -> List[Dict[str, object]]:
    return [{
        "path": t_after.path,
        "internal_path": t_after.internal_path,
        "score": t_score.total,
        "reasons": t_score.reasons,
    } for t_after, t_score in p_ranked]
