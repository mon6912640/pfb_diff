# PfbDiff

`PfbDiff` 是 Cocos Creator 2.x `.prefab` 两方语义对比工具。重点识别节点移动、重命名、移动并重命名，避免简单文本 diff 把这类变化误报成删除加新增。

## 用法

### 方式一：桌面 GUI（推荐日常对比）

```bash
python gui.py
```

启动原生桌面窗口，包含四个页签：

- **📊 两方对比**：拖入两个 `.prefab` 文件即可生成树形对比报告
- **🌲 SVN 冲突分析**：拖入 `.prefab.working` 冲突文件（自动定位同组 merge-left/merge-right，分析完直接打开冲突概览），或拖入整个目录批量扫描所有冲突组，逐组分析后行内直接显示结论（真冲突 / 树级冲突 / 改动一致数量）
- **📜 版本对比**：拖入 SVN 工作副本内的 `.prefab`，从其历史里选两个端点对比；每个端点可以是某个 revision，或「当前工作副本（含未提交改动）」。覆盖历史考古与提交/合并前自检
- **🌿 分支对比**：左右两侧各拖入一个 SVN 工作副本内的 `.prefab`（可来自不同分支/路径），分别列出各自的 SVN 提交历史，各选一个端点（某个 revision 或「当前工作副本」）进行对比

支持查看历史报告（每个页签对应各自的报告子目录；冲突分析的子报告不在列表里重复展示，从概览页内链接进入）。

> **📜 版本对比 / 🌿 分支对比** 依赖系统已安装 `svn` 命令行客户端，且被比较的 `.prefab` 位于一个 SVN 工作副本（WC）内（即 `svn checkout` 下来、能正常提交的工程目录）。鉴权沿用系统已缓存的 svn 凭据；失败时请先在命令行 `svn` 登录一次。

**特点**：使用 `tkinterdnd2` 实现原生拖放，**拖放可直接获取文件完整路径**（如 `C:\work\...\xxx.prefab`），报告中会显示原始路径方便区分。

**额外依赖**：
```bash
pip install tkinterdnd2
```

### 方式二：CLI（脚本 / CI 集成）

```bash
python pfb_diff.py diff \
  --before old.prefab \
  --after new.prefab \
  --out report.html \
  --json report.json
```

`--out` 默认输出暗色主题树形对比报告。如需旧版表格报告：

```bash
python pfb_diff.py diff \
  --before old.prefab \
  --after new.prefab \
  --out-classic report_classic.html
```

如果不传 `--out` 和 `--json`，工具会自动生成 HTML 和 JSON 报告到：

```text
reports/compare/
```

默认文件名会根据两个 prefab 的文件名生成，例如：

```text
myflCnt_diff_20260506_153012.html
myflCnt_diff_20260506_153012.json
```

默认发现差异仍返回 0。需要按风险失败时：

```bash
python pfb_diff.py diff --before old.prefab --after new.prefab --fail-on-risk high
```

### SVN 冲突分析（CLI）

```bash
# 指定 working 文件，自动寻找同组的 merge-left / merge-right
python svn_conflict_helper.py ZdlsMapScene.prefab.working

# 扫描目录内所有冲突组
python svn_conflict_helper.py --scan <目录>
```

每组生成 4 份报告：冲突概览（交叉分类：真冲突 / 树级冲突 / 双方改动一致 / 仅单边修改）+ base→ours、base→theirs、ours↔theirs 三份树形报告。

报告按功能分子目录存放：两方对比 → `reports/compare/`，冲突分析 → `reports/svn_conflict/`。GUI 的最近报告列表随页签切换展示对应目录；后续新增页签功能时按此约定新增子目录。

### 方式三：打包成 exe（无 Python 环境可用）

```bash
compile.bat
```

双击执行后会在项目根目录生成 `PfbDiff.exe`。

**exe 特点**：
- **双击运行** → 启动 GUI 窗口
- **命令行调用** → 支持所有 CLI 参数，例如：
  ```bash
  PfbDiff.exe diff --before old.prefab --after new.prefab --out report.html
  ```

报告统一生成到 `PfbDiff.exe` 同级目录的 `reports/` 文件夹下。

## 输出

- **JSON**：稳定结构，供测试、后续三方 diff 和 UI 复用。
- **HTML（默认）**：暗色主题树形对比报告，左右双栏展示节点树，不同变化类型用颜色标识，点击节点查看带高亮的字段 diff。标题栏显示两个 prefab 的绝对路径，方便区分。
- **HTML（`--out-classic`）**：静态表格，包含摘要、高风险列表、低置信度匹配、节点变化、字段变化、资源变化、事件变化、解析警告。

## 项目结构

```
pfb_diff/
├── main.py               # 统一入口（有参数走 CLI，无参数启动 GUI）
├── gui.py                # GUI 编排入口（建窗口、挂页签、装配各模块）
├── gui_theme.py          #   GUI 配色 / 字体常量
├── gui_shell.py          #   框架层 AppShell（状态栏、最近报告、页签切换、滚轮）+ 路径工具
├── gui_compare_tab.py    #   CompareTab：两方对比页签
├── gui_conflict_tab.py   #   ConflictTab：SVN 冲突分析页签
├── gui_revision_tab.py   #   RevisionTab：同分支版本对比页签
├── gui_branch_tab.py     #   BranchTab：跨分支对比页签
├── svn_revision_helper.py # svn 命令薄封装（info/log/cat/list_branches），版本/分支对比共用
├── pfb_diff.py           # CLI 入口
├── svn_conflict_helper.py # SVN 冲突分析（CLI + GUI 共用的分析与概览报告）
├── compile.bat           # PyInstaller 打包脚本
├── diff_engine.py        # 核心 diff 引擎
├── matcher.py            # 节点匹配引擎
├── report_html_tree.py   # 树形 HTML 报告生成器
├── report_json.py        # JSON 报告生成器
├── tests/                # 单元测试（test_gui_smoke.py 无头 GUI 冒烟、test_svn_revision.py svn 集成）
└── reports/              # 自动生成的报告目录（按功能分子目录）
    ├── compare/          #   两方对比报告
    ├── svn_conflict/     #   SVN 冲突分析报告
    ├── revision/         #   同分支版本对比报告
    └── branch/           #   跨分支对比报告
```

## 范围

不做三方 diff、SVN 冲突自动识别、自动合并、资源 uuid 到路径映射。脚本字段只做浅层 diff，并跳过 Cocos 内部字段和 `__id__` 引用。

「版本对比 / 分支对比」会主动调用系统 `svn` 命令行（其余功能均为离线文件对比）：要求已安装 svn 客户端、被比较的 `.prefab` 在 SVN 工作副本内；不内置鉴权界面（沿用系统缓存凭据），不直接对非 WC 的纯仓库 URL 拖放操作。

事件回调对比覆盖 Button / Toggle / ToggleContainer / Slider / ScrollView / PageView / EditBox（见 `config.py` 的 `EVENT_FIELDS`）；事件 target 会解析成节点路径再对比，不受 `__id__` 布局偏移影响；编辑器中未绑定函数的空事件槽不参与对比。
