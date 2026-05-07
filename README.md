# PfbDiff

`PfbDiff` 是 Cocos Creator 2.x `.prefab` 两方语义对比工具。第一版重点识别节点移动、重命名、移动并重命名，避免简单文本 diff 把这类变化误报成删除加新增。

## 用法

### 桌面 GUI（推荐日常对比）

```bash
python3 gui.py
```

启动暗色主题桌面窗口，拖入两个 `.prefab` 文件即可生成树形对比报告，支持查看历史报告。

### CLI（脚本 / CI 集成）

```bash
python3 packages/pfb_diff/pfb_diff.py diff \
  --before old.prefab \
  --after new.prefab \
  --out report.html \
  --json report.json
```

`--out` 默认输出暗色主题树形对比报告。如需旧版表格报告：

```bash
python3 packages/pfb_diff/pfb_diff.py diff \
  --before old.prefab \
  --after new.prefab \
  --out-classic report_classic.html
```

如果不传 `--out` 和 `--json`，工具会自动生成 HTML 和 JSON 报告到：

```text
packages/pfb_diff/reports/
```

默认文件名会根据两个 prefab 的文件名生成，例如：

```text
myflCnt_diff_20260506_153012.html
myflCnt_diff_20260506_153012.json
```

默认发现差异仍返回 0。需要按风险失败时：

```bash
python3 packages/pfb_diff/pfb_diff.py diff --before old.prefab --after new.prefab --fail-on-risk high
```

## 输出

- JSON：稳定结构，供测试、后续三方 diff 和 UI 复用。
- HTML（默认）：暗色主题树形对比报告，左右双栏展示节点树，不同变化类型用颜色标识，点击节点查看带高亮的字段 diff。
- HTML（`--out-classic`）：静态表格，包含摘要、高风险列表、低置信度匹配、节点变化、字段变化、资源变化、事件变化、解析警告。

## 范围

第一版不做三方 diff、SVN 冲突自动识别、自动合并、资源 uuid 到路径映射和复杂 Web UI。脚本字段只做浅层 diff，并跳过 Cocos 内部字段和 `__id__` 引用。
