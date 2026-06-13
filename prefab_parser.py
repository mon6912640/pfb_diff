from typing import Any, Dict, List, Optional

from config import COCOS_INTERNAL_FIELDS, EVENT_FIELDS, LABEL_FIELDS, NODE_PROP_FIELDS, RESOURCE_FIELDS
from prefab_loader import load_prefab_json
from prefab_model import PrefabComponent, PrefabDocument, PrefabNode


def parse_prefab(file_path: str) -> PrefabDocument:
    t_raw_data = load_prefab_json(file_path)
    t_doc = PrefabDocument(file_path=file_path, raw_data=t_raw_data)
    for t_index, t_obj in enumerate(t_raw_data):
        if isinstance(t_obj, dict):
            t_doc.id_map[t_index] = t_obj
        else:
            t_doc.warnings.append({
                "type": "invalid_object",
                "id": t_index,
                "message": "prefab item is not an object",
            })

    t_nodes = []
    for t_id, t_obj in t_doc.id_map.items():
        if t_obj.get("__type__") == "cc.Node":
            t_node = _parse_node(t_doc, t_id, t_obj)
            t_doc.node_by_id[t_id] = t_node
            t_nodes.append(t_node)

    for t_node in t_nodes:
        t_obj = t_doc.id_map.get(t_node.local_id, {})
        t_node.children = _parse_children(t_doc, t_node, t_obj)
        t_node.components = _parse_components(t_doc, t_node, t_obj)
        t_node.resources = _merge_component_lists(t_node.components, "resources")
        t_node.events = _merge_component_lists(t_node.components, "events")

    for t_node in t_nodes:
        if t_node.parent_id is None or t_node.parent_id not in t_doc.node_by_id:
            t_doc.root_nodes.append(t_node)

    for t_index, t_root in enumerate(t_doc.root_nodes):
        t_root.sibling_index = t_index
        _assign_paths(t_root, "", "")

    for t_node in t_nodes:
        # 有合法 _parent 但未被父节点 _children 列出的节点（或成环节点）
        # 不会被 _assign_paths 遍历到，路径为空。空 internal_path 会让它们
        # 在匹配第一阶段互相乱锚，这里发出警告提示数据结构异常。
        if not t_node.internal_path:
            t_doc.warnings.append({
                "type": "unreachable_node",
                "id": t_node.local_id,
                "name": t_node.name,
                "message": "node has a parent but is not reachable from any root (orphan or cycle)",
            })

    _resolve_event_targets(t_doc, t_nodes)

    t_doc.nodes = sorted(t_nodes, key=lambda p_node: p_node.internal_path or p_node.name)
    return t_doc


def _resolve_event_targets(p_doc: PrefabDocument, p_nodes: List[PrefabNode]) -> None:
    # target 的 __id__ 是对象在文件中的下标，两个版本间会整体偏移，
    # 直接对比必然误报；解析成节点路径后才是稳定的语义值。
    # 必须在 _assign_paths 之后执行，否则路径全为空串。
    for t_node in p_nodes:
        for t_event in t_node.events:
            t_target_id = t_event.get("target")
            t_target_node = p_doc.node_by_id.get(t_target_id) if t_target_id is not None else None
            t_event["target"] = t_target_node.path if t_target_node is not None else None


def _parse_node(p_doc: PrefabDocument, p_id: int, p_obj: Dict[str, Any]) -> PrefabNode:
    t_parent_id = _ref_id(p_obj.get("_parent"))
    if t_parent_id is not None and t_parent_id not in p_doc.id_map:
        p_doc.warnings.append({
            "type": "invalid_parent_ref",
            "id": p_id,
            "ref_id": t_parent_id,
            "message": "node parent reference is missing",
        })
        t_parent_id = None
    t_props = {}
    for t_field in NODE_PROP_FIELDS:
        if t_field in p_obj:
            t_props[t_field] = _stable_value(p_obj[t_field])
    return PrefabNode(
        local_id=p_id,
        name=str(p_obj.get("_name", "")),
        parent_id=t_parent_id,
        props=t_props,
    )


def _parse_children(p_doc: PrefabDocument, p_node: PrefabNode, p_obj: Dict[str, Any]) -> List[PrefabNode]:
    t_children = []
    for t_child_index, t_ref in enumerate(p_obj.get("_children") or []):
        t_child_id = _ref_id(t_ref)
        if t_child_id is None or t_child_id not in p_doc.node_by_id:
            p_doc.warnings.append({
                "type": "invalid_child_ref",
                "id": p_node.local_id,
                "ref_id": t_child_id,
                "message": "node child reference is missing",
            })
            continue
        t_child = p_doc.node_by_id[t_child_id]
        t_child.parent_id = p_node.local_id
        t_child.sibling_index = t_child_index
        t_children.append(t_child)
    return t_children


def _parse_components(p_doc: PrefabDocument, p_node: PrefabNode, p_obj: Dict[str, Any]) -> List[PrefabComponent]:
    t_components = []
    for t_index, t_ref in enumerate(p_obj.get("_components") or []):
        t_component_id = _ref_id(t_ref)
        if t_component_id is None or t_component_id not in p_doc.id_map:
            p_doc.warnings.append({
                "type": "invalid_component_ref",
                "id": p_node.local_id,
                "ref_id": t_component_id,
                "message": "node component reference is missing",
            })
            continue
        t_obj = p_doc.id_map.get(t_component_id) or {}
        t_type = str(t_obj.get("__type__", "UnknownComponent"))
        if t_type == "UnknownComponent":
            p_doc.warnings.append({
                "type": "unknown_component",
                "id": t_component_id,
                "node_id": p_node.local_id,
                "message": "component has no __type__",
            })
        t_component = PrefabComponent(
            local_id=t_component_id,
            type_name=t_type,
            is_script=_is_script_component(t_type),
            index_in_node=t_index,
            props=_extract_component_props(t_obj),
            resources=_extract_resources(t_type, t_obj),
            events=_extract_events(t_type, t_obj),
        )
        t_components.append(t_component)
    return t_components


def _assign_paths(p_node: PrefabNode, p_parent_path: str, p_parent_internal_path: str) -> None:
    p_node.path = _join_path(p_parent_path, p_node.name)
    p_node.internal_path = _join_path(p_parent_internal_path, "%s[%s]" % (p_node.name, p_node.sibling_index))
    p_node.parent_path = p_parent_path
    for t_index, t_child in enumerate(p_node.children):
        t_child.sibling_index = t_index
        _assign_paths(t_child, p_node.path, p_node.internal_path)


def _extract_component_props(p_obj: Dict[str, Any]) -> Dict[str, Any]:
    t_props = {}
    t_type = str(p_obj.get("__type__", "UnknownComponent"))
    t_resource_fields = set(RESOURCE_FIELDS.get(t_type, []))
    t_event_fields = set(EVENT_FIELDS.get(t_type, []))
    for t_key, t_value in p_obj.items():
        if t_key in COCOS_INTERNAL_FIELDS:
            continue
        if t_key in t_resource_fields or t_key in t_event_fields:
            continue
        if _contains_id_ref(t_value):
            continue
        t_props[t_key] = _stable_value(t_value)
    return t_props


def _extract_resources(p_type: str, p_obj: Dict[str, Any]) -> List[Dict[str, Any]]:
    t_resources = []
    for t_field in RESOURCE_FIELDS.get(p_type, []):
        t_uuid = _uuid(p_obj.get(t_field))
        if t_uuid:
            t_resources.append({"component": p_type, "field": t_field, "uuid": t_uuid})
    return t_resources


def _extract_events(p_type: str, p_obj: Dict[str, Any]) -> List[Dict[str, Any]]:
    t_events = []
    for t_field in EVENT_FIELDS.get(p_type, []):
        for t_event in p_obj.get(t_field) or []:
            if not isinstance(t_event, dict):
                continue
            if not t_event.get("handler") and not t_event.get("component"):
                # 编辑器里未绑定函数的空事件槽，无运行时行为，
                # 计入会误升风险等级、并让无关节点共享空事件特征
                continue
            t_events.append({
                "component": p_type,
                "field": t_field,
                "target": _ref_id(t_event.get("target")),
                "component_name": t_event.get("component"),
                "handler": t_event.get("handler"),
                "custom_event_data": t_event.get("customEventData"),
            })
    return t_events


def _merge_component_lists(p_components: List[PrefabComponent], p_attr: str) -> List[Dict[str, Any]]:
    t_values = []
    for t_component in p_components:
        t_values.extend(getattr(t_component, p_attr))
    return t_values


def _is_script_component(p_type: str) -> bool:
    return not (p_type.startswith("cc.") or p_type.startswith("sp."))


def _ref_id(p_value: Any) -> Optional[int]:
    if isinstance(p_value, dict) and "__id__" in p_value:
        t_value = p_value.get("__id__")
        if isinstance(t_value, int):
            return t_value
    return None


def _uuid(p_value: Any) -> Optional[str]:
    if isinstance(p_value, dict):
        t_uuid = p_value.get("__uuid__") or p_value.get("uuid")
        if t_uuid:
            return str(t_uuid)
    return None


def _stable_value(p_value: Any) -> Any:
    if isinstance(p_value, dict):
        if "__uuid__" in p_value:
            return {"__uuid__": p_value.get("__uuid__")}
        return {str(t_key): _stable_value(p_value[t_key]) for t_key in sorted(p_value.keys()) if t_key != "__id__"}
    if isinstance(p_value, list):
        return [_stable_value(t_item) for t_item in p_value if not _contains_id_ref(t_item)]
    return p_value


def _contains_id_ref(p_value: Any) -> bool:
    if isinstance(p_value, dict):
        if "__id__" in p_value:
            return True
        return any(_contains_id_ref(t_value) for t_value in p_value.values())
    if isinstance(p_value, list):
        return any(_contains_id_ref(t_item) for t_item in p_value)
    return False


def _join_path(p_parent: str, p_name: str) -> str:
    if p_parent:
        return p_parent + "/" + p_name
    return p_name
