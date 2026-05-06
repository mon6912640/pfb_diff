# PfbDiff 开发计划

## 一、工具定位

`PfbDiff` 是一个用于对比 Cocos Creator 2.x `.prefab` 文件的结构语义 diff 工具。

它不是普通文本 diff 工具，也不以节点 `path` 作为主要判断依据。工具核心目标是：

```text
通过节点指纹识别“是不是同一个节点”
通过节点路径描述“节点现在在哪里”
通过字段级 diff 说明“节点具体改了什么”
通过风险分级判断“是否适合人工合并”
```

第一版只做两方 prefab 对比，不自动合并 prefab。架构需要为后续三方 diff、SVN 冲突分析、资源路径映射、半自动合并建议预留扩展空间。

---

## 二、核心原则

### 2.1 path 不是节点身份

`path` 只能说明节点当前位置，不能说明节点身份。

例如：

```text
before: Root/PanelLeft/BtnReward
after:  Root/PanelRight/BtnReward
```

这个节点可能只是移动了，不应该简单报告为：

```text
删除 Root/PanelLeft/BtnReward
新增 Root/PanelRight/BtnReward
```

### 2.2 节点指纹是核心

节点身份应该通过多维指纹判断：

```text
节点名
组件类型
业务脚本类型
主要资源 uuid
Label 文本
Button 事件
子节点结构
视觉属性
上下文信息
```

### 2.3 低置信度不能静默处理

当工具无法确认两个节点是否为同一个节点时，必须把候选匹配、分数和原因输出到报告中，由人工判断。

---

## 三、第一版范围

第一版目标：

```text
实现一个具备节点指纹匹配能力的两方 prefab diff 工具
```

命令示例：

```bash
python pfb_diff.py diff --before old.prefab --after new.prefab --out report.html --json report.json
```

第一版必须支持：

```text
prefab JSON 读取
__id__ 引用解析
节点树构建
节点 path 生成
节点指纹提取
节点匹配
节点移动识别
节点重命名识别
节点移动并重命名识别
组件增删改
基础属性变化
Label 文本变化
Sprite 资源 uuid 变化
Button 事件变化
脚本字段变化
低置信度匹配报告
基础 HTML 报告
JSON 结果导出
```

第一版暂不实现：

```text
三方 diff
SVN 冲突文件自动识别
自动合并
uuid 到资源路径映射
Cocos Creator 编辑器插件
复杂交互式 Web UI
```

---

## 四、建议目录结构

工具开发目录：

```text
packages/pfb_diff/
  pfb_diff.py              # CLI 入口
  prefab_loader.py         # 文件读取和 JSON 加载
  prefab_parser.py         # prefab 解析和节点树构建
  prefab_model.py          # 内部数据模型
  fingerprint.py           # 节点指纹提取
  matcher.py               # 节点匹配算法
  diff_engine.py           # 两方 diff 主逻辑
  change_model.py          # diff 结果数据结构
  risk_classifier.py       # 风险分级
  report_json.py           # JSON 报告生成
  report_html.py           # HTML 报告生成
  config.py                # 权重、忽略字段、低信息节点等配置
  README.md                # 使用说明
  PfbDiff开发计划.md        # 本文档
  tests/
    fixtures/              # prefab 测试样例
```

模块职责需要保持清晰，避免把解析、匹配、diff、报告生成写到一个大文件里。

---

## 五、数据模型

### 5.1 PrefabDocument

```python
class PrefabDocument:
    file_path: str
    raw_data: list
    id_map: dict
    root_nodes: list
    nodes: list
    node_by_id: dict
    warnings: list
```

### 5.2 PrefabNode

```python
class PrefabNode:
    local_id: int
    name: str
    path: str                # 展示路径，便于人工阅读
    internal_path: str       # 内部路径，必须可区分同名兄弟节点
    parent_id: int
    parent_path: str
    sibling_index: int

    children: list
    components: list

    props: dict
    resources: list
    events: list

    fingerprint: NodeFingerprint
```

`path` 和 `internal_path` 需要分开：

```text
path:
  Root/Panel/Item/Label
  用于报告展示，保持简洁。

internal_path:
  Root[0]/Panel[0]/Item[2]/Label[1]
  用于内部索引和消歧，必须包含 sibling_index。
```

同一个父节点下存在多个同名节点时，不能只依赖展示 `path`。否则 `Item/Label` 这类节点会发生路径冲突。

### 5.3 PrefabComponent

```python
class PrefabComponent:
    local_id: int
    type_name: str
    is_script: bool
    index_in_node: int
    props: dict
    resources: list
    events: list
```

脚本组件第一版判断规则：

```text
__type__ 不以 cc. 开头
__type__ 不以 sp. 开头
先视为业务脚本组件
```

后续可扩展脚本 uuid 到类名映射。

组件不能依赖数组下标跨版本匹配。组件匹配规则：

```text
1. 优先按 type_name 匹配
2. 业务脚本组件优先按脚本类型匹配
3. 同一节点下多个同类型组件时，按资源、事件、字段相似度匹配
4. cc.Sprite、cc.Label、cc.Button 等内置组件可结合关键字段匹配
5. 无法确认时输出 component_match_uncertain
```

组件数组顺序变化应单独记录，不应直接当作组件删除和新增。

### 5.4 NodeFingerprint

```python
class NodeFingerprint:
    identity_hash: str
    structure_hash: str
    visual_hash: str
    behavior_hash: str
    context_hash: str

    strong_features: dict
    weak_features: dict
    context_features: dict
```

### 5.5 Change

```python
class Change:
    change_type: str
    risk: str

    before_node_id: int
    after_node_id: int

    before_path: str
    after_path: str

    field_path: str
    before_value: any
    after_value: any

    confidence: int
    reasons: list
```

---

## 六、Prefab 解析规则

Cocos Creator 2.x prefab 通常是 JSON 数组，对象之间通过 `__id__` 引用。

解析流程：

```text
1. json.load 读取 prefab 数组
2. 建立 id_map: 数组下标 -> 对象
3. 找到 cc.Node 对象
4. 解析 _children、_components、_parent 引用
5. 构建节点树
6. 为每个节点生成 path
7. 为每个节点生成 internal_path
8. 解析组件、资源、事件和基础属性
9. 为每个节点生成指纹
```

必须容错：

```text
__id__ 指向不存在对象时不能崩溃
未知组件类型不能崩溃
缺失字段不能崩溃
JSON 格式错误要给出明确错误
```

解析层只负责把 prefab 转成稳定的内部模型，不做 diff 判断。所有匹配、风险分级和报告展示都应放在后续模块，避免解析层承担过多业务逻辑。

---

## 七、字段提取规则

### 7.1 节点基础字段

从 `cc.Node` 提取：

```text
_name
_children
_components
_parent
_contentSize
_anchorPoint
_position
_scale
_color
_opacity
_active
```

### 7.2 组件类型

从组件对象的 `__type__` 提取：

```text
cc.Sprite
cc.Label
cc.Button
sp.Skeleton
cc.Layout
业务脚本组件类型
```

### 7.3 资源引用

第一版优先提取：

```text
cc.Sprite._spriteFrame.__uuid__
cc.Button.normalSprite.__uuid__
cc.Button.pressedSprite.__uuid__
cc.Button.hoverSprite.__uuid__
cc.Button.disabledSprite.__uuid__
sp.Skeleton.skeletonData.__uuid__
cc.AnimationClip.__uuid__
cc.SpriteAtlas.__uuid__
```

第一版只展示 uuid。资源路径映射放到后续阶段。

### 7.4 Label 文本

兼容字段：

```text
_N$string
_string
string
```

### 7.5 Button 事件

提取：

```text
clickEvents.target
clickEvents.component
clickEvents.handler
clickEvents.customEventData
```

事件绑定变化必须单独标记，因为它通常影响交互逻辑。

### 7.6 脚本字段

脚本字段需要按字段路径保存：

```text
Root/Panel/BtnReward.RewardBtn.rewardId
```

第一版可以先跳过 Cocos 内部字段和明显引用字段，保留业务字段。

脚本字段第一版只做浅层字段 diff。复杂对象、数组和 `__id__` 引用字段先保留原始路径和摘要，不做深度语义合并。

字段忽略规则必须可配置，默认忽略：

```text
__type__
node
_id
_name
_objFlags
_enabled
_enabledInHierarchy
_parent
_children
_components
```

引用字段处理规则：

```text
__id__:
  不直接按数字 diff，因为 __id__ 只在单个 prefab 文件内部有效。

__uuid__:
  按资源引用处理，进入 resource_changed。

事件 target.__id__:
  应解析到目标节点后，用目标节点匹配结果辅助判断事件是否变化。
```

---

## 八、节点指纹设计

指纹分层生成，不使用单一总 hash。

### 8.1 identity_hash

用于高置信身份判断：

```text
name
componentTypes
scriptTypes
mainResourceUuids
```

`identity_hash` 只用于快速确认同一节点。没有命中 `identity_hash` 时，不能直接判定为不同节点，必须继续进入结构、视觉、行为相似度评分。

事件绑定不放入 `identity_hash`，避免同一个 Button 只改了 handler 后被误判为完全不同节点。

### 8.2 structure_hash

用于结构相似判断：

```text
componentTypes
childNameSet
childComponentShape
descendantShape 简化版
```

### 8.3 visual_hash

用于视觉元素判断：

```text
spriteUuid
labelText
contentSize
anchorPoint
color
opacity
```

### 8.4 behavior_hash

用于交互和业务行为判断：

```text
button clickEvents
toggle checkEvents
script component types
```

第一版不把脚本字段值放入 `behavior_hash`。脚本字段容易频繁变化，放入指纹会降低同一节点识别能力。第一版只使用脚本组件类型和事件绑定参与行为指纹。

### 8.5 context_hash

用于低信息节点消歧：

```text
parentName
siblingNames
siblingIndex
ancestorNames
```

注意：节点移动时上下文会变化，所以 context 只能辅助评分，不能作为主身份依据。

---

## 九、节点匹配算法

匹配流程必须以指纹为主，path 为辅。

```text
1. 收集 before / after 所有节点
2. 为每个节点生成指纹
3. 第一轮：identity_hash 高置信匹配
4. 第二轮：结构、视觉、行为相似度匹配
5. 第三轮：低置信候选收集
6. 应用一对一匹配约束
7. 输出 matched / added / deleted / uncertain
```

path 的作用：

```text
展示移动 from -> to
辅助相似度评分
帮助低信息节点消歧
```

path 不应该直接决定节点身份。

`path` 不单独作为一轮匹配流程，只作为评分特征之一参与相似度计算。这样可以避免实现时重新退化成 path diff。

匹配结果需要区分：

```text
confirmed:
  高置信匹配，可直接进入 diff。

probable:
  大概率是同一节点，可进入 diff，但报告中展示置信度。

uncertain:
  不直接作为稳定匹配，进入低置信度列表。

ambiguous:
  多个候选分数接近，必须由人工判断。

unmatched:
  before 独有视为 deleted，after 独有视为 added。
```

---

## 十、相似度评分

评分权重放在 `config.py`，不能硬编码在算法里。

初始权重建议：

```text
identity_hash 相同              +80
componentTypes 相同             +20
scriptTypes 相同                +25
mainResourceUuids 相同          +30
button handler 相同             +25
labelText 相同                  +15
childNameSet 相似               +15
contentSize 接近                +8
anchorPoint 相同                +5
name 相同                       +10
path 相同                       +10
parentName 相同                 +5
siblingNames 相似               +8
```

匹配等级：

```text
score >= 85   confirmed
score 70-84   probable
score 55-69   uncertain
score < 55    unmatched
```

如果最高分和第二名差距小于 10：

```text
标记为 ambiguous
进入低置信度列表
不静默当作准确匹配
```

候选评分不能对所有节点无条件 O(n²) 暴力比较。第一版需要建立候选索引：

```text
scriptTypes -> nodes
componentTypes -> nodes
mainResourceUuids -> nodes
labelText -> nodes
name -> nodes
```

评分流程：

```text
1. 先通过索引取候选集合
2. 对候选集合计算详细分数
3. 只有剩余 unmatched 数量较小时，才允许兜底 O(n²)
```

这样大 prefab 下仍能保持可用性能。

---

## 十一、低信息节点处理

低信息节点名单需要可配置：

```text
bg
icon
label
title
num
txt
text
node
con
item
btn
```

这些节点匹配时：

```text
降低 name 权重
提高资源 uuid 权重
提高组件结构权重
提高父子关系权重
提高兄弟集合权重
```

避免把多个普通 `Icon`、`Label`、`Bg` 错配为同一个节点。

---

## 十二、Diff 类型

第一版至少输出：

```text
node_added
node_deleted
node_moved
node_renamed
node_moved_and_renamed
node_reordered

component_added
component_deleted
component_changed
component_reordered
component_match_uncertain

property_changed
resource_changed
event_changed
script_field_changed

match_uncertain
parse_warning
```

子节点顺序变化需要单独处理：

```text
node_reordered:
  同一父节点下，匹配后的子节点集合基本相同，但 sibling_index 顺序变化。
```

子节点顺序变化不应参与节点身份强判断，但会影响 UI 层级，应按中风险展示。

移动示例：

```text
BtnReward
from: Root/PanelLeft/BtnReward
to:   Root/PanelRight/BtnReward
confidence: 92
reason: scriptTypes same, button handler same, child structure similar
```

字段变化示例：

```text
Root/Panel/BtnReward.cc.Label.string
before: "奖励"
after:  "活动奖励"
```

---

## 十三、风险分级

### 13.1 低风险

```text
Label 文本变化
position / scale / color / opacity / active 变化
简单 number/string/boolean 脚本字段变化
新增不带脚本、不带事件、不遮挡交互的独立叶子节点
```

### 13.2 中风险

```text
节点移动
节点重命名
资源 uuid 变化
Button 事件变化
子节点顺序变化
组件新增或删除
新增带资源但无脚本、无事件的 UI 展示节点
```

### 13.3 高风险

```text
低置信度匹配但节点包含脚本或事件
组件类型变化
脚本组件类型变化
事件 handler 变化
资源引用大量变化
__id__ 引用无法解析
疑似同一节点但多个候选分数接近
新增带脚本或事件的节点
新增可能遮挡交互区域的大尺寸节点
```

---

## 十四、HTML 报告

第一版 HTML 报告优先保证信息清楚，不追求复杂交互。

页面结构：

```text
顶部：
  before 文件
  after 文件
  节点数统计
  差异统计
  风险统计

主体：
  高风险列表
  低置信度匹配列表
  节点结构变化
  字段变化
  资源变化
  事件变化
  解析警告
```

每条变化显示：

```text
类型
风险
before path
after path
字段路径
before value
after value
confidence
reasons
```

颜色建议：

```text
绿色：新增
红色：删除
蓝色：普通修改
黄色：低置信度或中风险
深红：高风险
灰色：未变化或辅助信息
```

---

## 十五、JSON 报告

JSON 是后续扩展基础，第一版必须输出。

JSON 是事实结果，HTML 只是 JSON 的展示层。后续三方 diff、测试断言、Web UI 和半自动合并建议都应优先消费 JSON，而不是反向解析 HTML。

用途：

```text
后续三方 diff 复用
后续 Web UI 复用
后续半自动合并建议复用
方便写测试
```

结构示意：

```json
{
  "before": {
    "path": "old.prefab",
    "nodeCount": 0,
    "warnings": []
  },
  "after": {
    "path": "new.prefab",
    "nodeCount": 0,
    "warnings": []
  },
  "summary": {
    "changes": 0,
    "highRisk": 0,
    "mediumRisk": 0,
    "lowRisk": 0,
    "uncertainMatches": 0
  },
  "matches": [],
  "changes": [],
  "uncertainMatches": [],
  "warnings": []
}
```

JSON 字段需要尽量稳定。新增字段应保持向后兼容，避免后续工具依赖频繁失效。

---

## 十六、MVP 验收边界

第一版可以拆成一个最小可运行版本，避免一次性实现过大。

MVP 必须完成：

```text
读取 before / after prefab
解析 __id__ 和 cc.Node 树
生成 path 和 internal_path
提取组件类型、脚本类型、Sprite uuid、Label 文本、Button clickEvents
生成基础节点指纹
完成节点匹配
识别 node_added / node_deleted / node_moved / node_renamed / node_moved_and_renamed
输出 JSON 报告
输出简单 HTML 表格报告
```

MVP 可以延后：

```text
复杂脚本字段深度 diff
复杂组件数组语义 diff
完整 descendantShape
复杂 HTML 交互
自动打开浏览器
资源 uuid 到路径映射
```

MVP 验收标准：

```text
移动节点不能被报告为删除 + 新增
重命名节点不能被报告为删除 + 新增
同名兄弟节点 path 不冲突
Button 事件变化能单独显示
Sprite uuid 变化能单独显示
低置信度匹配能进入报告
解析异常能进入 warnings
```

---

## 十七、测试计划

第一版需要准备小型 prefab fixtures：

```text
same.prefab
label_changed_before.prefab
label_changed_after.prefab
node_moved_before.prefab
node_moved_after.prefab
node_renamed_before.prefab
node_renamed_after.prefab
button_event_changed_before.prefab
button_event_changed_after.prefab
sprite_changed_before.prefab
sprite_changed_after.prefab
low_info_icon_case_before.prefab
low_info_icon_case_after.prefab
same_name_siblings_before.prefab
same_name_siblings_after.prefab
component_reordered_before.prefab
component_reordered_after.prefab
invalid_reference.prefab
```

验收标准：

```text
节点移动不能误报为删除 + 新增
节点重命名能识别为 node_renamed
移动并重命名能识别为 node_moved_and_renamed
Bg/Icon/Label 不应大量误匹配
Button 事件变化必须单独列出
Sprite uuid 变化必须单独列出
低置信度匹配必须出现在报告中
解析异常必须进入 warnings 而不是直接崩溃
同名兄弟节点必须通过 internal_path 区分
组件顺序变化不能误报为组件删除 + 新增
```

---

## 十八、开发顺序

建议按以下顺序实现：

```text
1. prefab_loader.py
2. prefab_model.py
3. prefab_parser.py
4. 基础节点树和 path 生成
5. 组件、资源、事件、字段提取
6. fingerprint.py
7. matcher.py
8. diff_engine.py
9. change_model.py
10. risk_classifier.py
11. report_json.py
12. report_html.py
13. tests/fixtures
14. README.md
```

每一步都应保持可单独测试。

开发优先级：

```text
JSON 报告优先于 HTML 报告
节点匹配优先于字段 diff 完整性
低置信度可见优先于强行给出结论
可配置规则优先于硬编码特殊 case
```

---

## 十九、CLI 和退出码

命令行参数：

```bash
python pfb_diff.py diff --before old.prefab --after new.prefab --out report.html --json report.json
```

建议支持：

```text
--before       旧版本 prefab
--after        新版本 prefab
--out          HTML 报告路径，可选
--json         JSON 报告路径，可选
--config       自定义配置路径，可选
--fail-on-risk high|medium|none
--quiet        减少控制台输出
```

退出码：

```text
0 正常完成
1 正常完成，但命中 fail-on-risk 指定风险
2 参数错误
3 prefab 读取或 JSON 解析失败
4 内部异常
```

默认不因为发现差异返回非 0，避免影响人工查看流程。只有显式设置 `--fail-on-risk` 时，才按风险返回失败码。

---

## 二十、后续扩展方向

第一版稳定后再扩展：

```text
三方 diff：base / mine / theirs
SVN 冲突文件自动识别
uuid -> asset path 映射
更完整的 Cocos 组件字段支持
HTML 节点树交互浏览
半自动合并建议
Cocos Creator 编辑器插件
```

扩展时应复用第一版的核心链路：

```text
parse -> fingerprint -> match -> diff -> risk -> report
```

不要让三方 diff、HTML UI 或自动合并逻辑反向污染基础解析和节点匹配模块。
