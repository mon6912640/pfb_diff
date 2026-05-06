from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PrefabComponent:
    local_id: int
    type_name: str
    is_script: bool
    index_in_node: int
    props: Dict[str, Any] = field(default_factory=dict)
    resources: List[Dict[str, Any]] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class NodeFingerprint:
    identity_hash: str = ""
    structure_hash: str = ""
    visual_hash: str = ""
    behavior_hash: str = ""
    context_hash: str = ""
    strong_features: Dict[str, Any] = field(default_factory=dict)
    weak_features: Dict[str, Any] = field(default_factory=dict)
    context_features: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PrefabNode:
    local_id: int
    name: str
    path: str = ""
    internal_path: str = ""
    parent_id: Optional[int] = None
    parent_path: str = ""
    sibling_index: int = 0
    children: List["PrefabNode"] = field(default_factory=list)
    components: List[PrefabComponent] = field(default_factory=list)
    props: Dict[str, Any] = field(default_factory=dict)
    resources: List[Dict[str, Any]] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)
    fingerprint: NodeFingerprint = field(default_factory=NodeFingerprint)

    def component_types(self) -> List[str]:
        return [component.type_name for component in self.components]

    def script_types(self) -> List[str]:
        return [component.type_name for component in self.components if component.is_script]

    def has_behavior(self) -> bool:
        return bool(self.events or self.script_types())


@dataclass
class PrefabDocument:
    file_path: str
    raw_data: List[Dict[str, Any]]
    id_map: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    root_nodes: List[PrefabNode] = field(default_factory=list)
    nodes: List[PrefabNode] = field(default_factory=list)
    node_by_id: Dict[int, PrefabNode] = field(default_factory=dict)
    warnings: List[Dict[str, Any]] = field(default_factory=list)
