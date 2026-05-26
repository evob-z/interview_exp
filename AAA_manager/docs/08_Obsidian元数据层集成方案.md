# Obsidian 元数据层集成方案（SPEC）

> 版本：v1.2 | 编写日期：2026-05-26 | 状态：有条件通过（design-reviewer 复审通过，实现时修复 1 处代码缺口）

## 1. 背景与目标

### 1.1 问题陈述

interview_exp 当前缺少三个维度的元数据能力：

| 维度 | 现状 | 痛点 |
|---|---|---|
| **知识图谱** | 问题库内引用为纯文本（如 `阿里_大厂_260509 #23`） | AI 无法查询"哪些知识点相互关联"、"某公司高频问什么" |
| **掌握度标记** | 无结构化标记，仅靠人工记忆 | 复盘后无法结构化追踪"哪些题答得差，需要重点复习" |
| **复习时间追踪** | 无时间维度 | 无法实现间隔复习调度，依赖人工回忆上次复习时间 |

### 1.2 目标

1. **知识图谱**：通过 Obsidian wikilink + Graph View 建立知识点可视化关联
2. **掌握度标记**：复盘后自动打 `mastery: weak/medium/mastered` 到问题库文件
3. **复习时间追踪**：自动记录 `last_reviewed` / `next_review` 时间戳

### 1.3 核心原则

> - **主路径零依赖**：所有核心模块不依赖 Obsidian，写入全部走 Python 纯本地 IO
> - **Obsidian 为可选增强**：CLI 仅用于读取层加速（backlinks/tags/search），不可用时降级到 Python 解析
> - **不替代现有功能**：元数据层是增量，不改动现有 archiver/preparer/reflector 的核心逻辑

---

## 2. 现状分析

### 2.1 问题库格式现状

当前问题库（`问题库/八股.md`、`项目-*.md` 等）为纯 Markdown：

```markdown
### Q1：LLM 幻觉怎么优化？
- **来源**：蚂蚁_大厂_260509_一面技术 #23
- **要点**：数据层、Prompt 层、RAG 层...
```

**问题**：
- `#23` 被 Obsidian 误识别为 tag
- 无 frontmatter 元数据头
- 无 wikilink，无法建立图谱关联
- 无 mastery/last_reviewed 字段

### 2.2 Obsidian CLI v1.12.7 能力矩阵

| 操作 | 命令 | 可用 |
|---|---|---|
| 读 properties | `obsidian properties path=xxx` | ✅ |
| 读 backlinks | `obsidian backlinks path=xxx format=json` | ✅ |
| 读 tags | `obsidian tags format=json` | ✅ |
| 全文搜索 | `obsidian search query=xxx format=json` | ✅ |
| 追加内容 | `obsidian append path=xxx content=xxx` | ✅ |
| **写 frontmatter** | （不存在 `properties set`） | ❌ |
| **修改内容** | （无 `edit`/`replace`） | ❌ |

**结论：CLI 强读弱写，写入必须走 Python 直写 YAML。**

---

## 3. 技术方案

### 3.1 架构图

```
┌─────────────────────────────────────────────────────────┐
│                  interview_exp AI Agent                   │
├─────────────────────────────────────────────────────────┤
│  新增模块：frontmatter_utils.py（纯 Python 无依赖）       │
│  ┌───────────────────────────────────────────────────┐  │
│  │ get_frontmatter(path) → dict                      │  │
│  │ set_frontmatter(path, {key: val}) → None          │  │
│  │ parse_wikilinks(content) → list[str]              │  │
│  └───────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────┤
│  新增模块：obsidian_reader.py（可选 CLI 加速层）          │
│  ┌───────────────────────────────────────────────────┐  │
│  │ OBSIDIAN_AVAILABLE: bool                          │  │
│  │ get_backlinks(path) → list[str]                   │  │
│  │ search_vault(query) → list[dict]                  │  │
│  │ get_weak_topics() → list[str]                     │  │
│  └───────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────┤
│  现有模块改动（追加增强钩子，不改核心逻辑）               │
│  ┌───────────────────────────────────────────────────┐  │
│  │ preparer.py: 预测文件生成后 → set_frontmatter()    │  │
│  │ reflector.py: 复盘完成 → set_frontmatter() + mastery│  │
│  │ archiver.py:  归档完成 → 更新来源 wikilink 格式    │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### 3.2 核心模块设计：frontmatter_utils.py

> **放置位置**：`AAA_manager/frontmatter_utils.py`（根目录，与 `logger.py`/`config.py` 同级）

```python
# 不依赖任何外部服务，纯 Python 标准库 + PyYAML
import yaml, re
from pathlib import Path
from typing import Any

def read_frontmatter(file_path: Path) -> tuple[dict, str]:
    """读取 frontmatter 和正文。返回 (metadata_dict, body_text)"""

def write_frontmatter(file_path: Path, updates: dict) -> None:
    """合并更新 frontmatter，保留已有字段"""

def parse_wikilinks(content: str) -> list[str]:
    """从 Markdown 正文中提取所有 [[wikilink]] 引用"""

def upsert_inline_metadata(file_path: Path, qid: int, updates: dict[str, str]) -> None:
    """在问题库文件指定 Q 编号的题块末尾，写入/更新 Dataview inline 字段。
    
    格式: key:: value（每行一个，Q 块末尾，下一个 ### Q 标题之前）
    - 已有 inline 字段 → 合并更新
    - 无 inline 字段 → 在 Q 块末尾追加
    - Q 编号不存在 → 记录 warning，静默跳过
    
    示例输出:
        ### Q1：LLM 幻觉怎么优化？
        ...
        mastery:: weak
        last_reviewed:: 2026-05-26
        review_count:: 2
        
        ### Q2：什么时候做微调？
    """
```

### 3.3 可选增强模块设计：obsidian_reader.py

> **放置位置**：`AAA_manager/obsidian_reader.py`（根目录，与 `frontmatter_utils.py` 同级）

```python
import subprocess, json

def _check_cli() -> bool:
    """启动时健康检查 obsidian 命令是否可用"""
    ...

OBSIDIAN_AVAILABLE: bool = _check_cli()

def get_backlinks(file_path: str, fallback_to_parse: bool = True) -> list[str]:
    """优先 CLI 查询，不可用时降级到 Python 正则解析"""

def search_vault(query: str, fallback_to_grep: bool = True) -> list[dict]:
    """优先 CLI 全文搜索，不可用时降级到 pathlib + re"""

def get_files_by_property(key: str, value: str) -> list[str]:
    """搜索所有 frontmatter 中 key=value 的文件"""
```

### 3.4 数据格式规范

#### 问题库文件格式示例（含每题级 inline 元数据）

```markdown
### Q1：LLM 幻觉怎么优化？
- **来源**：[[蚂蚁_大厂_260509_一面技术]] #23
- **关联**：[[Q15-RAG检索流程]] [[Q7-Prompt工程]]
- **要点**：...
- **💬 面试话术**：
  > 幻觉治理我认为要分层来做...

mastery:: weak
last_reviewed:: 2026-05-26
review_count:: 2

### Q2：什么时候做微调？
- **来源**：[[蚂蚁_大厂_260509_一面技术]] #24
...
```

> **设计原理**：`key:: value` 是 Obsidian Dataview 的 inline field 语法。
> - Dataview 插件可查询：`TABLE mastery WHERE mastery = "weak"`
> - 纯文本可读，不影响其他工具解析
> - 每题独立标记，解决文件级 frontmatter 粒度不匹配问题

#### 岗位预测文件 frontmatter 示例

```markdown
---
company: 字节跳动
position: AI应用开发实习生
date: "2026-05-25"
department: 抖音
prep_type: 岗位预测
---
```

#### 复盘文件 frontmatter 示例

```markdown
---
company: 字节跳动
company_type: 大厂
date: "2026-05-13"
round: 一面技术
doc_type: 面试复盘
---
```

### 3.5 降级路径

| 功能 | 有 Obsidian（增强路径） | 无 Obsidian（降级路径） |
|---|---|---|
| 写入 frontmatter | `frontmatter_utils.write_frontmatter()`（纯 Python） | 同左（无差异） |
| 读取 backlinks | `obsidian backlinks` CLI → JSON 解析 | `pathlib` 遍历 + `re.findall(r'\[\[(.+?)\]\]')` |
| 全文搜索 | `obsidian search` CLI → JSON | `pathlib.rglob("*.md")` + 逐行 grep |
| 按 property 查询 | `obsidian search` 匹配 frontmatter 行 | `frontmatter_utils.read_frontmatter()` 遍历 |
| 知识图谱可视化 | Obsidian Graph View（人工使用） | 不适用（纯 CLI 无 GUI 场景） |

---

## 4. 集成点设计

### 4.1 preparer.py 增强

**触发时机**：岗位预测文件生成后（`out_path.write_text()` 之后）

**增强内容**：
```python
from frontmatter_utils import write_frontmatter

out_path.write_text(body + "\n", encoding="utf-8")

# ── 可选增强：打 frontmatter ──
try:
    write_frontmatter(out_path, {
        "company": company,
        "position": position,
        "date": date,
        "prep_type": "岗位预测",
        **({"department": department} if department else {}),
    })
except Exception:
    pass  # 增强失败不影响主流程
```

### 4.2 reflector.py 增强（三方写入）

**触发时机**：复盘完成，Summary Agent 产出结构化评估后

**增强内容**：

1. **复盘文件打 frontmatter**（文件级，company/date/round/doc_type）——不变
2. **每题级 mastery 打标**（inline 字段，非文件级 frontmatter）——全新设计
3. **复习时间更新**：`last_reviewed` + `review_count` 递增

#### 4.2.1 扩展 Summary Agent 输出 Schema

在 `ReflectionSummary` 中增加结构化字段，解决自然语言文本无法映射到 `(qid, category)` 的问题：

```python
class QuestionItem(BaseModel):
    """单个问题的结构化评估"""
    qid: int = Field(description="问题编号，如 Q1 的 1")
    category: str = Field(description="分类，如 八股/AI_Coding/项目-law_sea")
    reason: str = Field(default="", description="简短原因，≤30字")

class ReflectionSummary(BaseModel):
    """Summary Agent 最终输出"""
    performance_summary: str
    well_answered: list[str] = Field(default_factory=list)      # 保留自然语言
    poorly_answered: list[str] = Field(default_factory=list)
    well_answered_qids: list[QuestionItem] = Field(default_factory=list)   # NEW
    poorly_answered_qids: list[QuestionItem] = Field(default_factory=list) # NEW
    interviewer_focus: list[str] = Field(default_factory=list)
    improvement_suggestions: list[str] = Field(default_factory=list)
    review_content: str = Field(min_length=100)
```

> **为什么 LLM 能输出结构化 `(qid, category)`？**  
> Summary Agent 的 transcript 格式化时必须显式包含 `category_suggestion`。当前 `_format_transcript()` 只传了 `id` 和 `text`，**需同步修改**：
> ```python
> # reflector.py _format_transcript() 修复前
> parts.append(f"Q{q.get('id', '?')}: {q.get('text', '')}")
> 
> # 修复后
> parts.append(f"Q{q.get('id', '?')} [{q.get('category_suggestion', '未分类')}]: {q.get('text', '')}")
> ```

#### 4.2.2 增强主函数

```python
from frontmatter_utils import write_frontmatter, upsert_inline_metadata
from config import CATEGORY_FILE_MAP, QUESTION_BANK_PATH
import datetime

def _enhance_mastery_from_summary(summary_output: ReflectionSummary) -> None:
    """从 Summary Agent 结构化输出中提取评估，写入问题库每题 inline 元数据"""
    today = datetime.datetime.now().strftime("%Y-%m-%d")

    for item in summary_output.poorly_answered_qids:
        target_file = CATEGORY_FILE_MAP.get(item.category)
        if not target_file:
            continue
        upsert_inline_metadata(QUESTION_BANK_PATH / target_file, item.qid, {
            "mastery": "weak",
            "last_reviewed": today,
        })

    for item in summary_output.well_answered_qids:
        target_file = CATEGORY_FILE_MAP.get(item.category)
        if not target_file:
            continue
        upsert_inline_metadata(QUESTION_BANK_PATH / target_file, item.qid, {
            "mastery": "mastered",
            "last_reviewed": today,
        })
```

> **`review_count` 递增**：`upsert_inline_metadata` 为合并模式，已有 `review_count` 时需在调用前读取并 +1。实现时由 `_enhance_mastery_from_summary` 负责此逻辑，或在 `upsert_inline_metadata` 内部支持 `$inc` 语义。

在 `reflect_interview_async()` 中调用：

```python
    # 持久化（含汇总分析）
    reflect_path = _save_reflect_log(meta, questions, transcript, summary_output)

    # ── Obsidian 增强：复盘文件 frontmatter + 每题 mastery 打标 ──
    try:
        if reflect_path:
            write_frontmatter(reflect_path, {
                "company": meta.get("company", ""),
                "company_type": meta.get("company_type", ""),
                "date": meta.get("date", ""),
                "round": meta.get("round", ""),
                "doc_type": "面试复盘",
            })
        _enhance_mastery_from_summary(summary_output)
    except Exception:
        pass  # 增强失败不影响主流程
```

#### 4.2.3 Summary Agent Prompt 更新

`_build_summary_agent()` 的 system prompt 需增加以下指令：

```markdown
## 结构化输出要求

除自然语言汇总外，你必须精确输出以下结构化字段：

- `well_answered_qids`：回答出色的题目列表
  - `qid`：题目编号（整数，如 1 代表 Q1）
  - `category`：题目分类（从输入 transcript 的 category_suggestion 字段引用）
  - `reason`：为什么答得好（≤30字）
- `poorly_answered_qids`：回答不佳的题目列表（同上格式）

注意：`well_answered` / `poorly_answered`（自然语言）与 `_qids`（结构化）必须一致——
自然语言中提到的每一道题，都必须在对应的 `_qids` 字段中出现。
```

#### 4.2.4 `upsert_inline_metadata` 实现要点

```python
def upsert_inline_metadata(file_path: Path, qid: int, updates: dict[str, str]) -> None:
    """定位 Q 块 → 解析已有 inline 字段 → 合并 → 写回
    
    关键算法：
    1. 正则定位 `### Q{qid}[：:]` 行（行号 q_start）
    2. 定位下一个 `### Q\d+[：:]` 行（行号 q_end），无则用文件尾
    3. 从 q_end 向上扫描，收集已有 inline 字段行到 existing dict
       - **仅收集白名单 key**（`mastery`/`last_reviewed`/`review_count`），避免正文中 `:: ` 误匹配
    4. existing.update(updates)
    5. 用 [行:strip_start] + new_inlines + [行:q_end] 重建文件
    """
```

> **边缘情况**：Q 编号不存在 → warning 日志 + return；文件无 Q 块 → 同上

#### 4.2.5 与文件级 frontmatter 的职责分离

| 元数据 | 存储位置 | 粒度 | 示例 |
|---|---|---|---|
| 复盘文件元信息 | 文件级 YAML frontmatter | 每文件 | `company: 字节跳动` |
| 题库 mastery | inline 字段（Q 块末尾） | 每题 | `mastery:: weak` |
| 题库关联关系 | wikilink `[[...]]` | 跨文件 | `[[Q15-RAG检索流程]]` |

### 4.3 archiver.py 增强（格式升级）

**触发时机**：`sync` 归档新问题到问题库时

**改动**：将 `来源` 行从纯文本改为 wikilink 格式：
```markdown
# 旧格式
- **来源**：蚂蚁_大厂_260509_一面技术 #23

# 新格式
- **来源**：[[蚂蚁_大厂_260509_一面技术]] #23
```

**联动修改**：`question_bank._extract_source()` 的正则 `(.+)` 会捕获 `[[` `]]` 括号，需同步增加剥离逻辑：
```python
# question_bank.py _extract_source() 末尾
source = re.sub(r'^\[\[|\]\]$', '', source.strip())  # 剥离 wikilink 括号
```

---

## 5. 数据迁移方案

### 5.1 存量回填脚本

脚本 `scripts/backfill_frontmatter.py`：

1. 遍历 `问题库/*.md`，为每道题追加初始 inline 元数据：
   ```
   mastery:: unset
   last_reviewed:: null
   review_count:: 0
   ```
2. 将现有 `来源` 行批量转为 `[[wikilink]]` 格式
3. 为 `面试复盘/` 目录下的现有文件补打 frontmatter（company/date/round 等）

### 5.2 迁移触发

- **方式一**：手动执行 `python scripts/backfill_frontmatter.py`
- **方式二**：在 `sync` 命令末尾自动触发（可选，需确认）
- **幂等性**：脚本检查 inline 字段是否已存在，不重复写入

---

## 6. 可选性保障

### 6.1 启动时健康检查

```python
# obsidian_reader.py 模块级
OBSIDIAN_AVAILABLE = subprocess.run(
    ["obsidian", "version"], capture_output=True
).returncode == 0
```

### 6.2 所有增强点包裹 try/except

- 写入层（`frontmatter_utils`）无外部依赖，不抛异常（除非文件权限问题）
- 读取层（`obsidian_reader`）CLI 调用失败 → 自动降级到 Python 解析
- 主路径代码零感知，增强钩子以独立代码块追加到现有函数末尾

### 6.3 无 Obsidian 时的能力等价

| | 能力 |
|---|---|
| ✅ 保留 | 问题归档、岗位预测、面试复盘、QA 模拟问答 |
| ✅ 保留 | frontmatter 写入（Python 直写，Obsidian 打开后自动识别） |
| ⚠️ 降级 | backlinks 查询（正则扫描 → 比 CLI 慢但功能等价） |
| ❌ 不可用 | Obsidian Graph View 可视化（仅在 Obsidian UI 中可用） |

---

## 7. 测试策略

### 7.1 单元测试

| 模块 | 测试内容 |
|---|---|
| `frontmatter_utils` | 读写 frontmatter、合并已有字段、空文件兜底、wikilink 解析、**upsert_inline_metadata（含合并/新增/边缘）** |
| `obsidian_reader` | CLI 可用/不可用分支、降级路径正确性 |
| `ReflectionSummary` | 新 `QuestionItem` 字段的序列化/反序列化 |

### 7.2 集成测试

| 场景 | 验证点 |
|---|---|
| preparer 增强 | 预测文件生成后 frontmatter 正确写入 |
| reflector 增强 | 复盘后 mastery/last_reviewed 正确更新 |
| 无 Obsidian 环境 | 降级路径正常工作，不抛异常 |

### 7.3 回归测试

确保现有 preparer/reflector/archiver 核心逻辑不受影响。

---

## 8. 实施阶段

| 阶段 | 内容 | 涉及文件 |
|---|---|---|
| **P1** | 编写 `frontmatter_utils.py`（纯 Python 读写 YAML frontmatter） | 新增 1 个文件 |
| **P2** | 编写 `obsidian_reader.py`（CLI 加速读取 + 降级路径） | 新增 1 个文件 |
| **P3** | preparer.py 增强（预测文件打 frontmatter） | 修改 preparer.py |
| **P4** | reflector.py 增强（mastery 打标 + 时间追踪） | 修改 reflector.py |
| **P5** | archiver.py 增强（来源格式 wikilink 化） | 修改 archiver.py |
| **P6** | 回填脚本 `scripts/backfill_frontmatter.py` | 新增 1 个脚本 |
| **P7** | 单元测试 + 集成测试 | 新增/修改测试文件 |
| **P8** | 端到端验证 + 文档更新 | docs/CHANGELOG.md |

---

## 9. 风险与限制

| 风险 | 影响 | 缓解措施 |
|---|---|---|
| PyYAML 覆盖写入可能改变用户手动编辑的 frontmatter | 数据丢失 | `write_frontmatter` 合并模式（非覆盖），保留未知字段 |
| wikilink 格式变更导致 `question_bank._extract_source` 捕获 `[[` `]]` 括号 | source 字段含 wikilink 括号 | P5 联动修改 `_extract_source` 末尾增加 `re.sub(r'^\[\[|\]\]$', '', ...)`（见 §4.3） |
| archiver 单元测试硬编码旧来源格式 | 测试失败 | P5 格式变更时同步更新 test_archiver.py fixture |
| Summary Agent 结构化输出可能遗漏某道题（LLM 不精确） | 部分题 mastery 未更新 | `_enhance_mastery_from_summary` 仅操作 LLM 输出的数据，不影响存量 |
| `upsert_inline_metadata` 依赖 `### Q{n}[：:]` 正则匹配 Q 块 | 格式不规范的 Q 标题匹配失败 | warning 日志 + 静默跳过，不影响主流程 |
| Obsidian CLI 版本升级可能改变命令语法 | 读取层失效 | `OBSIDIAN_AVAILABLE` 启动检查 + 自动降级 |

---

## 10. 设计审查反馈

### v1.0 → v1.1

| 缺陷编号 | 严重程度 | 问题 | 修复 |
|---|---|---|---|
| R1 | 🔴 致命 | 文件级 frontmatter 无法表达每题 mastery 粒度 | 改用 Dataview inline 字段（`key:: value`），每题独立 |
| R2 | 🔴 致命 | `poorly_answered` 自然语言无法映射 `(qid, category)` | 新增 `QuestionItem` 结构化字段 + Summary Agent prompt 更新 |
| R3 | 🟡 中 | wikilink 影响 `_extract_source` | §9 风险表格增加此项 |
| R4 | 🟡 中 | 模块放置目录未指定 | §3.2/§3.3 明确根目录位置 |

### v1.1 → v1.2

| 审查发现 | 严重程度 | 问题 | 修复 |
|---|---|---|---|
| `_format_transcript` 缺 category | 🔴 高 | Summary Agent 看不到 `category_suggestion`，LLM 只能猜 | §4.2.1 增加 `_format_transcript` 修复方案 |
| inline 字段 `:: ` 误匹配 | 🟡 中 | 正文中 `:: ` 可能被误识别为 inline 字段 | §4.2.4 算法增加 key 白名单（`mastery`/`last_reviewed`/`review_count`） |
| `_extract_source` 剥离 | 🟡 中 | wikilink 剥离逻辑仅文字描述 | §4.3 增加具体代码示例 |
| 伪代码 `__self__` 不可执行 | 🟢 低 | `_save_reflect_log.__self__` 不适用于模块级函数 | §4.2.2 改为 `reflect_path = _save_reflect_log(...)` |

---

## 11. 审批记录

| 阶段 | 角色 | 状态 |
|---|---|---|
| SPEC 编写 | 主 Agent | ✅ 已完成 |
| 架构审查（初版） | design-reviewer | ❌ 驳回（v1.0，R1+R2 致命缺陷） |
| 架构审查（v1.2） | design-reviewer | ✅ 有条件通过（实现时修复 `_format_transcript`） |
