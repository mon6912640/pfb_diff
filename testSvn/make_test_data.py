#!/usr/bin/env python3
"""生成 testSvn/ 下的模拟 SVN 冲突组（测试 svn_conflict_helper.py 用）

组 A 03_contentLv1：受控冲突
  - point1: 仅 ours 改 y          → only_ours
  - point2: ours 改 x、theirs 改 y → both_modified（真冲突）
  - point3: 双方都改 x 为同一个值   → both_convergent（假冲突）
  - point4: 仅 theirs 重命名       → only_theirs
组 B 01_TowBat：压力组，ours 零修改，theirs 为另一皮肤版本（全量单边差异）
组 C 03_treeConflict：树级冲突
  - base 在 contentLv1 下挂了 PanelExtra/LabelInfo 子树
  - ours 删除整个 PanelExtra 子树
  - theirs 修改 LabelInfo 的坐标
"""
import copy
import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "testPfb")


def load(name):
    with open(os.path.join(SRC, name), encoding="utf-8") as f:
        return json.load(f)


def save(data, name):
    with open(os.path.join(HERE, name), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def find_node(data, name):
    for o in data:
        if isinstance(o, dict) and o.get("__type__") == "cc.Node" and o.get("_name") == name:
            return o
    raise KeyError(name)


# ── 组 A：受控冲突 ──
base_a = load("03_contentLv1_红包.prefab")
save(base_a, "03_contentLv1.prefab.merge-left.r100")

ours_a = copy.deepcopy(base_a)
find_node(ours_a, "point1")["_position"]["y"] = 200      # 仅 ours
find_node(ours_a, "point2")["_position"]["x"] = -300     # 真冲突（ours 侧）
find_node(ours_a, "point3")["_position"]["x"] = 260      # 收敛修改（ours 侧）
save(ours_a, "03_contentLv1.prefab.working")

theirs_a = copy.deepcopy(base_a)
find_node(theirs_a, "point2")["_position"]["y"] = -100   # 真冲突（theirs 侧，改不同字段）
find_node(theirs_a, "point3")["_position"]["x"] = 260    # 收敛修改（theirs 侧，同值）
find_node(theirs_a, "point4")["_name"] = "point4_renamed"  # 仅 theirs
save(theirs_a, "03_contentLv1.prefab.merge-right.r105")

# ── 组 B：压力组 ──
shutil.copy(os.path.join(SRC, "01_TowBat_鬼服.prefab"), os.path.join(HERE, "01_TowBat.prefab.merge-left.r100"))
shutil.copy(os.path.join(SRC, "01_TowBat_鬼服.prefab"), os.path.join(HERE, "01_TowBat.prefab.working"))
shutil.copy(os.path.join(SRC, "01_TowBat_红包.prefab"), os.path.join(HERE, "01_TowBat.prefab.merge-right.r105"))

# ── 组 C：树级冲突 ──
plain = load("03_contentLv1_红包.prefab")          # 不含 PanelExtra 的版本
base_c = copy.deepcopy(plain)

# 以 point1 节点为模板造两个新节点，追加到数组末尾（避免 __id__ 重排）
root_idx = next(i for i, o in enumerate(base_c)
                if isinstance(o, dict) and o.get("__type__") == "cc.Node" and o.get("_name") == "contentLv1")
tpl_idx = next(i for i, o in enumerate(base_c)
               if isinstance(o, dict) and o.get("__type__") == "cc.Node" and o.get("_name") == "point1")

panel_idx = len(base_c)
label_idx = panel_idx + 1

panel = copy.deepcopy(base_c[tpl_idx])
panel["_name"] = "PanelExtra"
panel["_parent"] = {"__id__": root_idx}
panel["_children"] = [{"__id__": label_idx}]
panel["_components"] = []
panel["_prefab"] = None

label = copy.deepcopy(base_c[tpl_idx])
label["_name"] = "LabelInfo"
label["_parent"] = {"__id__": panel_idx}
label["_children"] = []
label["_components"] = []
label["_prefab"] = None
label["_position"]["x"] = 10
label["_position"]["y"] = 20

base_c.append(panel)
base_c.append(label)
base_c[root_idx]["_children"].append({"__id__": panel_idx})

save(base_c, "03_treeConflict.prefab.merge-left.r100")

# ours = 删除整个 PanelExtra 子树（即不含该子树的原始版本）
save(plain, "03_treeConflict.prefab.working")

# theirs = base 基础上修改子树内部的 LabelInfo
theirs_c = copy.deepcopy(base_c)
find_node(theirs_c, "LabelInfo")["_position"]["x"] = 99
save(theirs_c, "03_treeConflict.prefab.merge-right.r105")

print("done:", sorted(f for f in os.listdir(HERE) if ".prefab." in f))
