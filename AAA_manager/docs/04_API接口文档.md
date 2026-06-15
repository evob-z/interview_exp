# API 接口文档

> 版本：v1.1 | 最后更新：2026-05-17 | 状态：已更新

## 1. 概述

- **基础URL**：`http://localhost:8000`
- **协议**：HTTP/1.1
- **数据格式**：JSON
- **流式响应**：Server-Sent Events (SSE)
- **CORS**：默认允许所有来源

## 2. 问答接口

### POST /api/qa

模拟面试问答（非流式版本）。

**请求体**：
```json
{
  "question": "什么是RAG？",
  "mode": "interview",
  "session_id": "abc123",
  "history": [
    {"role": "user", "content": "上一个问题"},
    {"role": "assistant", "content": "上一个回答"}
  ]
}
```

**参数说明**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| question | string | 是 | 用户问题 |
| mode | string | 否 | 问答模式：`interview`/`detailed`/`quick`，默认`interview` |
| session_id | string | 否 | 会话ID，用于上下文关联 |
| history | array | 否 | 对话历史 |

**响应**：
```json
{
  "answer": "RAG (Retrieval-Augmented Generation) 是...",
  "sources": ["AI_Coding.md#L12", "项目-compliance_checker.md#L5"],
  "followups": ["RAG的检索策略有哪些？", "如何评估RAG效果？"]
}
```

### POST /api/qa/stream

模拟面试问答（SSE流式版本）。

**请求体**：同 `/api/qa`

**响应**：SSE事件流
```
data: {"type": "token", "content": "RAG"}
data: {"type": "token", "content": " 是一种"}
data: {"type": "sources", "content": ["AI_Coding.md#L12"]}
data: {"type": "followups", "content": ["追问1", "追问2"]}
data: {"type": "done"}
```

## 3. 用户画像接口

### GET /api/profile

获取用户画像完整信息。

**响应**：
```json
{
  "basic_info": {"name": "...", "target_role": "..."},
  "skills": {"Python": 0.9, "LLM": 0.85},
  "strengths": ["项目经验丰富", "系统设计能力强"],
  "weaknesses": ["算法题需加强"],
  "growth_trend": "...",
  "interview_count": 8,
  "last_updated": "2026-05-15"
}
```

### GET /api/profile/brief

获取画像简要摘要（4-6句话）。

**响应**：
```json
{
  "overview": "AI应用开发方向的候选人，具备..."
}
```

### POST /api/profile/initialize

初始化或重建用户画像。

**响应**：
```json
{
  "status": "success",
  "message": "画像初始化完成"
}
```

### GET /api/profile/advice

获取个性化面试准备建议。

**响应**：
```json
{
  "advice": "建议重点复习..."
}
```

### GET /api/profile/encouragement

获取鼓励话语。

**响应**：
```json
{
  "encouragement": "你的进步很明显..."
}
```

## 4. 同步接口

### POST /api/sync

触发全流程同步（detect→extract→archive→review）。

**请求体**：
```json
{
  "auto_commit": false,
  "dry_run": false
}
```

**参数说明**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| auto_commit | bool | 否 | 是否自动Git提交，默认false |
| dry_run | bool | 否 | 预览模式，不执行实际操作 |

**响应**：
```json
{
  "status": "success",
  "processed_files": ["字节跳动_大厂_260513_技术一面.md"],
  "new_questions": 12,
  "reviews_generated": 1,
  "committed": false
}
```

## 5. 统计接口

### GET /api/stats

获取系统统计信息。

**响应**：
```json
{
  "question_bank": {
    "total": 156,
    "by_category": {
      "AI_Coding": 42,
      "八股": 35,
      "项目-law_sea": 28
    }
  },
  "interviews": {
    "total": 8,
    "companies": ["字节跳动", "美团", "蚂蚁"]
  },
  "submissions": {
    "total": 20,
    "in_progress": 5,
    "ended": 12
  }
}
```

## 6. 会话历史接口

### GET /api/history/sessions

获取所有会话列表。

**响应**：
```json
{
  "sessions": [
    {
      "id": "abc123",
      "title": "RAG相关问题",
      "created_at": "2026-05-15T10:30:00",
      "message_count": 12
    }
  ]
}
```

### GET /api/history/sessions/{session_id}

获取指定会话详情。

**响应**：
```json
{
  "id": "abc123",
  "messages": [
    {"role": "user", "content": "...", "timestamp": "..."},
    {"role": "assistant", "content": "...", "timestamp": "..."}
  ]
}
```

### POST /api/history/sessions

创建新会话。

**响应**：
```json
{
  "id": "new_session_id",
  "created_at": "2026-05-17T14:00:00"
}
```

### DELETE /api/history/sessions/{session_id}

删除指定会话。

**响应**：
```json
{
  "status": "success"
}
```

## 7. 岗位预测接口

### POST /api/prepare

触发岗位预测题生成（Agent 自主决策：搜 JD → 读简历/项目 → 结合画像 → 出题 → 自评 → 写入 `岗位预测/`）。

**请求体**：
```json
{
  "company": "京东",
  "position": "后端开发工程师",
  "department": "CHO体系-企业信息化部",
  "date": "260520",
  "count": 20
}
```

**参数说明**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| company | string | 是 | 公司名称 |
| position | string | 是 | 岗位名称 |
| department | string | 否 | 部门/团队名（可选），如 `CHO体系-企业信息化部` |
| date | string | 否 | 面试日期（YYMMDD格式），默认当天 |
| count | integer | 否 | 期望题数，默认读取 `PREP_QUESTION_COUNT` 配置 |

**响应**：
```json
{
  "status": "ok",
  "message": "生成完成：共 15 题",
  "company": "京东",
  "position": "后端开发工程师",
  "department": "CHO体系-企业信息化部",
  "date": "260520",
  "output_file": "岗位预测/京东_CHO体系-企业信息化部_后端开发工程师_260520.md",
  "output_filename": "京东_CHO体系-企业信息化部_后端开发工程师_260520.md",
  "question_count": 15,
  "jd_snippet_count": 14,
  "jd_source_count": 14,
  "elapsed_sec": 65.4,
  "used_agent": true,
  "agent_iterations": 3,
  "quality_score": 0.82,
  "hint": "已自动纳入模拟面试检索，可直接搜索复习"
}
```

## 8. 追问预测接口（可选）

### POST /api/followup

生成追问预测（需FOLLOWUP_ENABLED=true）。

**请求体**：
```json
{
  "history": [...],
  "last_answer": "..."
}
```

**响应**：
```json
{
  "followups": [
    "能否详细说明你在项目中如何...",
    "这个方案的性能瓶颈在哪里？",
    "你是如何做技术选型的？"
  ]
}
```

## 9. 语音识别接口（可选）

### WebSocket /api/asr/ws

语音识别WebSocket连接（需ASR_ENABLED=true）。

**通信协议**：
```
# 客户端发送音频数据（二进制帧）
→ binary: <audio_chunk>

# 服务端返回识别结果
← {"type": "partial", "text": "正在识别..."}
← {"type": "final", "text": "完整识别结果"}
```

## 10. 错误响应格式

所有接口的错误响应遵循统一格式：

```json
{
  "detail": "错误描述信息",
  "code": "ERROR_CODE"
}
```

**常见错误码**：

| HTTP状态码 | 错误码 | 说明 |
|-----------|--------|------|
| 400 | INVALID_REQUEST | 请求参数错误 |
| 404 | NOT_FOUND | 资源不存在 |
| 500 | INTERNAL_ERROR | 服务器内部错误 |
| 503 | LLM_UNAVAILABLE | LLM服务不可用 |

## 11. 依赖注入（内部）

应用启动时通过 `api/deps.py` 初始化以下单例服务：

| 服务 | 类 | 说明 |
|------|---|------|
| question_bank | QuestionBank | 题库检索引擎 |
| project_reader | ProjectReader | 项目文档理解 |
| resume_reader | ResumeReader | 简历解析 |
| excel_reader | ExcelReader | Excel投递表处理 |
| profile_manager | ProfileManager | 用户画像管理 |
| web_searcher | WebSearcher | 网络搜索（可选） |
