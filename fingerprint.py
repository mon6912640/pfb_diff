import hashlib
import json
from typing import Any, Dict, List

from prefab_model import NodeFingerprint, PrefabDocument, PrefabNode


def apply_fingerprints(p_doc: PrefabDocument) -> None:
    for t_node in p_doc.nodes:
        t_node.fingerprint = build_fingerprint(t_node)


def build_fingerprint(p_node: PrefabNode) -> NodeFingerprint:
    t_component_types = sorted(p_node.component_types())
    t_script_types = sorted(p_node.script_types())
    t_resource_uuids = sorted([t_item.get("uuid") for t_item in p_node.resources if t_item.get("uuid")])
    t_label_texts = sorted(_label_texts(p_node))
    t_events = _event_keys(p_node)
    t_child_names = [t_child.name for t_child in p_node.children]
    t_strong = {
        "script_types": t_script_types,
        "resource_uuids": t_resource_uuids,
        "label_texts": t_label_texts,
        "events": t_events,
    }
    t_weak = {
        "name": p_node.name,
        "component_types": t_component_types,
        "props": p_node.props,
        "child_names": t_child_names,
    }
    t_context = {
        "parent_path": p_node.parent_path,
        "path": p_node.path,
        "depth": len([t_part for t_part in p_node.path.split("/") if t_part]),
        "sibling_index": p_node.sibling_index,
    }
    return NodeFingerprint(
        identity_hash=_hash({
            "name": p_node.name,
            "components": t_component_types,
            "scripts": t_script_types,
            "resources": t_resource_uuids,
            "labels": t_label_texts,
            "events": t_events,
        }),
        structure_hash=_hash({"children": t_child_names, "components": t_component_types}),
        visual_hash=_hash({"props": p_node.props, "resources": t_resource_uuids, "labels": t_label_texts}),
        behavior_hash=_hash({"scripts": t_script_types, "events": t_events}),
        context_hash=_hash(t_context),
        strong_features=t_strong,
        weak_features=t_weak,
        context_features=t_context,
    )


def _label_texts(p_node: PrefabNode) -> List[Any]:
    t_texts = []
    for t_component in p_node.components:
        if t_component.type_name != "cc.Label":
            continue
        for t_key in ["_N$string", "_string", "string"]:
            if t_key in t_component.props:
                # 与 matcher._label_texts 对齐：包 str() 后再排序，否则
                # 同节点混有 null 文本时 sorted 会因 str 与 None 不可比而崩溃。
                t_texts.append(str(t_component.props.get(t_key)))
    return t_texts


def _event_keys(p_node: PrefabNode) -> List[str]:
    t_keys = []
    for t_event in p_node.events:
        t_keys.append("%s.%s:%s" % (
            t_event.get("component_name") or "",
            t_event.get("handler") or "",
            t_event.get("custom_event_data") or "",
        ))
    return sorted(t_keys)


def _hash(p_value: Dict[str, Any]) -> str:
    t_text = json.dumps(p_value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(t_text.encode("utf-8")).hexdigest()
