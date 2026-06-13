from config import RISK_HIGH, RISK_LOW, RISK_MEDIUM


def classify_node_add_delete(p_node, p_match_status):
    if p_node and p_node.has_behavior():
        return RISK_HIGH
    if p_match_status in ("uncertain", "ambiguous"):
        return RISK_MEDIUM
    return RISK_LOW


def classify_match(p_match):
    if p_match.status in ("uncertain", "ambiguous") and (p_match.before and p_match.before.has_behavior() or p_match.after and p_match.after.has_behavior()):
        return RISK_HIGH
    if p_match.status in ("uncertain", "ambiguous"):
        return RISK_MEDIUM
    return RISK_LOW


def classify_field_change(p_field, p_before_value, p_after_value):
    if str(p_field) == "events" or "clickEvents" in str(p_field) or ".events" in str(p_field):
        return RISK_HIGH
    if "uuid" in str(p_field) or "resources" in str(p_field) or "_spriteFrame" in str(p_field) or "_skeletonData" in str(p_field):
        return RISK_MEDIUM
    return RISK_LOW


def classify_warning(p_warning):
    if p_warning.get("type", "").startswith("invalid_"):
        return RISK_HIGH
    return RISK_MEDIUM
