# 贡献指南

感谢你愿意为 **interview_exp** 贡献代码、文档或想法！本指南帮助你快速参与到项目中。

---

## 行为准则

参与本项目须遵守 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。请保持友善、尊重与建设性。

---

## 开发环境

### 准备

```bash
git clone <your-fork-url>
cd interview_exp

conda create -n interview_exp python=3.11 -y
conda activate interview_exp

cd AAA_manager
pip install -r requirements.txt
cp .env.example .env   # 填入测试用的 API Key
```

### 启用提交前钩子（推荐）

```bash
pip install pre-commit
pre-commit install
```

这样每次 `git commit` 若触及 `AAA_manager/`，会自动运行 `pytest`。

---

## 工作流

### 1. Fork & 分支

```bash
git checkout -b feat/<short-topic>     # 新功能
git checkout -b fix/<issue-id>         # bug 修复
git checkout -b docs/<topic>           # 仅文档
git checkout -b refactor/<scope>       # 重构
git checkout -b test/<scope>           # 仅测试
```

### 2. 开发并自测

```bash
cd AAA_manager
pytest                  # 全量
pytest tests/unit -k test_extractor   # 只跑某文件
```

外部依赖（LLM、讯飞 ASR、Git 远程、网络搜索）全部 mock，**离线可跑、无需任何 API Key**。

### 3. 提交信息（Conventional Commits）

```
<type>(<scope>): <subject>

<body>
```

`type` 取值：

| type | 用途 |
|------|------|
| feat | 新功能 |
| fix | bug 修复 |
| docs | 仅文档 |
| refactor | 重构（不改外部行为） |
| test | 仅增删测试 |
| chore | 构建脚本、依赖更新等 |
| perf | 性能优化 |

示例：

```
feat(api): add /api/prepare/list endpoint
fix(extractor): handle empty markdown body
docs(readme): clarify .env setup steps
```

### 4. 提 PR

- 标题使用同样的 Conventional Commits 格式
- 描述包含：动机、改动概述、测试情况、是否破坏性变更
- 关联 Issue：`Closes #123` / `Refs #456`
- 等待 CI 全绿（参见 `.github/workflows/test.yml`）

---

## 代码规范

- **Python 3.11**，遵循 PEP 8
- 公开函数 / 类 写 docstring（Google 或 NumPy 风格皆可，保持文件内一致）
- 类型注解：新增代码尽量带 type hints
- 单元测试位于 `AAA_manager/tests/`，PR 必须包含覆盖新代码路径的测试
- 不要硬编码绝对路径、API Key、个人信息——一律走 `config.py` 读 `.env`
- 中文注释 / 文档允许保留，但变量名、函数名使用英文

### 目录约定

- `AAA_manager/api/routes/`：FastAPI 路由
- `AAA_manager/core/`：底层能力（搜索、ASR）
- `AAA_manager/knowledge/`：知识源读取
- `AAA_manager/profile/`：用户画像
- `AAA_manager/prompts/`：LLM Prompt 模板（纯 Markdown，不要在代码里拼字符串）

---

## 报告 Bug / 提需求

- **Bug**：使用 `.github/ISSUE_TEMPLATE/bug_report.md` 模板，附最小复现步骤、Python 版本、操作系统、相关日志（注意脱敏）
- **Feature**：使用 `.github/ISSUE_TEMPLATE/feature_request.md` 模板，描述使用场景与替代方案
- **安全问题**：**不要公开提交 Issue**，参见 [SECURITY.md](SECURITY.md)

---

## 隐私与合规

本仓库为开源代码，**严禁提交任何个人或他人面试数据**：

- 真实姓名、联系方式、简历、面试问题/答案
- 真实公司面经、内部题目
- API Key、token、cookie

所有个人数据目录（`面试原始问题/`、`面试复盘/`、`问题库/`、`个人情况/`、`公司投递情况/`、`岗位预测/`）已在 [.gitignore](.gitignore) 中排除，PR 中若新增数据文件请确保走脱敏样例（见 `*.example` 命名）。

---

## 许可证

提交 PR 即视为同意将贡献代码以 [MIT](LICENSE) 协议发布。
