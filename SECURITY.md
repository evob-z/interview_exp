# 安全策略

## 受支持的版本

本项目处于早期开源阶段，仅维护 `main` 分支。请始终基于最新 `main` 提交进行复现与测试。

## 报告漏洞

如果你发现安全漏洞，**请不要在公开 Issue 中披露**。

请通过以下方式联系维护者：

- 在仓库的 GitHub Security Advisories 中提交 Private Vulnerability Report
- 或发邮件至：`<2502366203@qq.com>`

请在报告中包含：

- 漏洞类型（注入、信息泄露、权限提升、依赖漏洞等）
- 受影响模块或文件路径
- 最小复现步骤
- 影响评估（攻击场景、潜在受害面）
- 你建议的修复方案（可选）

我们会在 **3 个工作日内**初步回复，确认后协调披露窗口与修复时间表。

---

## 用户安全须知

本项目涉及多个第三方 API 与本地文件系统，请遵守以下原则：

### API Key 管理

- **必须**通过 [.env](AAA_manager/.env.example) 文件配置 `DEEPSEEK_API_KEY`、`SEARCH_API_KEY`、`XUNFEI_*` 等密钥
- **禁止**将真实密钥硬编码在代码、注释、prompts 模板或测试用例中
- **禁止**将 `.env` 提交到 git（已在 [.gitignore](.gitignore) 中排除）
- 若密钥泄露，立即在对应服务商控制台 **吊销并重新生成**

### Issue / PR 中的敏感信息

提交 Issue、PR 或日志时，请脱敏：

- 真实姓名、手机号、邮箱、身份证号
- 真实简历、面试问题、面试答案、面试官评价
- API Key、Cookie、Bearer Token、Session ID
- 内部公司名（建议替换为「某厂」「公司 A」等）
- `data/sessions/*.json`、`data/user_profile.json` 内容

### 本地数据目录

以下目录默认包含个人数据，**仅存在于本地、不会被 git 跟踪**：

- `面试原始问题/` `面试复盘/` `问题库/`
- `个人情况/` `公司投递情况/` `岗位预测/`
- `AAA_manager/data/sessions/` `AAA_manager/data/user_profile.json`
- `AAA_manager/logs/`

请勿在 PR 中新增上述目录的真实数据文件；如需提供示例，请使用 `.example` 后缀且**完全虚构**内容。

### 第三方服务调用

- LLM 调用会将面试问题与个人画像发往 DeepSeek / Qwen，使用前请阅读对应服务商的隐私政策
- 网络搜索会将公司名 / 职位关键词发往 Tavily / Bing / Serper
- 讯飞 ASR 会上传音频到讯飞服务器
- 如对隐私敏感，可在 `.env` 中关闭：`ENABLE_WEB_SEARCH=false`、`ENABLE_VOICE_INPUT=False`

---

## 致谢

感谢所有负责披露漏洞的研究者。修复发布后，我们会在 Release Notes 中列出贡献者（如你不希望署名请提前告知）。
