LOW_INFO_NODE_NAMES = {
    "bg",
    "icon",
    "label",
    "title",
    "num",
    "txt",
    "text",
    "node",
    "con",
    "item",
    "btn",
}

COCOS_INTERNAL_FIELDS = {
    "__type__",
    "__id__",
    "_name",
    "_objFlags",
    "_parent",
    "_children",
    "_components",
    "_prefab",
    "_id",
    "node",
    "enabled",
    "_enabled",
    "_enabledInHierarchy",
    "_sizeProvider",
    "_sgNode",
}

NODE_PROP_FIELDS = [
    "_active",
    "_position",
    "_scale",
    "_contentSize",
    "_anchorPoint",
    "_color",
    "_opacity",
]

RESOURCE_FIELDS = {
    "cc.Sprite": ["_spriteFrame"],
    "sp.Skeleton": ["_skeletonData"],
}

LABEL_FIELDS = ["_N$string", "_string", "string"]

# 各组件的事件回调数组字段（cc.ClickEvent / cc.Component.EventHandler 列表）。
# 此处列出的字段会被提取为事件参与对比，并从浅层 props 中排除。
EVENT_FIELDS = {
    "cc.Button": ["clickEvents"],
    "cc.Toggle": ["clickEvents", "checkEvents"],
    "cc.ToggleContainer": ["checkEvents"],
    "cc.Slider": ["slideEvents"],
    "cc.ScrollView": ["scrollEvents"],
    "cc.PageView": ["scrollEvents", "pageEvents"],
    "cc.EditBox": ["editingDidBegan", "textChanged", "editingDidEnded", "editingReturn"],
}

CONFIRMED_SCORE = 92
PROBABLE_SCORE = 74
UNCERTAIN_SCORE = 58
AMBIGUOUS_DELTA = 4

RISK_LOW = "low"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"
