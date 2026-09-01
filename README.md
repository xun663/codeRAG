# CodeRAG - RAG 编程学习知识库与辅助问答系统

[![Backend Tests](https://github.com/xun663/codeRAG/actions/workflows/test.yml/badge.svg)](https://github.com/xun663/codeRAG/actions/workflows/test.yml)

基于检索增强生成 (RAG) 的编程学习代码知识库与智能问答平台。上传代码/教程文档 → 向量化入库 → 智能问答，配套自动出题 + 间隔重复复习闭环。

## 项目亮点

- **两阶段混合检索**：Dense + BM25 → RRF 融合 → Cross-Encoder 重排，文档级 top-5 命中 100%
- **自动化 RAG 质量门禁**：无人工 GT 场景自监督评估任意用户库（去同源化出题 + 多轮采样 + 三档判定）
- **学习闭环**：LLM 自动出题 + SM-2 间隔重复 + 错题本回顾
- **工程化**：225 个 pytest 自动化测试，VPS 生产部署，移动端适配

## 功能模块

| 模块 | 功能 |
|------|------|
| 知识库管理 | 文档上传/URL导入/Git仓库对接，代码感知分割，向量索引 |
| 智能问答 | 多轮对话，RAG管道（查询重写→混合检索→重排序→生成），流式回复 |
| 知识复习 | LLM自动出题、SM-2间隔重复排程、答题反馈 |
| 反馈评估 | 答案评分、Recall@K/MRR评估、A/B实验管理 |
| 系统管理 | LLM/Embedding切换、混合检索权重调节、Token监控 |
| 用户权限 | 注册登录、learner/admin/experimenter角色、KB级权限 |

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.12, FastAPI, SQLAlchemy 2.0 (async), Celery + Redis |
| 数据库 | MySQL 8.0 |
| 向量库 | ChromaDB（持久化） |
| 前端 | React 18, TypeScript, Vite, Ant Design 5, Zustand |
| LLM | DeepSeek V4（OpenAI 兼容协议，可运行时切换） |
| Embedding | bge-m3（本地）/ 千问 text-embedding-v3（云端），1024 维 |

## 快速开始

### 环境要求
- Python 3.12+
- Node.js 18+
- MySQL 8.0+ (或 PostgreSQL 16+)
- ChromaDB

### 1. 配置 API Key
```bash
# Windows (以管理员身份运行 CMD)
setx LLM_API_KEY "your-openai-api-key"

# 或在 backend/.env 中设置
LLM_API_KEY=sk-your-key
```

### 2. 启动后端
```bash
cd backend
pip install -e ".[dev]"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8085 --reload
```

### 3. 启动前端
```bash
cd frontend
npm install
npx vite --host 0.0.0.0 --port 5173
```

### 4. 访问
- 前端: http://localhost:5173
- API文档: http://localhost:8085/docs

## 项目结构

```
coderag/
├── backend/
│   ├── app/
│   │   ├── api/v1/          # REST API 路由 (15 个模块)
│   │   ├── core/            # 业务逻辑
│   │   │   ├── auth/        # JWT + 密码
│   │   │   ├── documents/   # 文档解析、分割、管道
│   │   │   ├── rag/         # RAG 管道 (查询/检索/生成)
│   │   │   ├── learning/    # SM-2 间隔重复排程
│   │   │   ├── evaluation/  # 评估指标、数据集、实验
│   │   │   ├── feedback/    # 用户反馈采集
│   │   │   └── monitoring/  # 配置管理、指标追踪
│   │   ├── models/          # SQLAlchemy ORM (18 张表)
│   │   ├── schemas/         # Pydantic 请求/响应模型
│   │   ├── services/        # 业务服务层
│   │   ├── llm/             # LLM 抽象层 (OpenAI/Anthropic/Local)
│   │   ├── embedding/       # 嵌入模型工厂
│   │   ├── vector_store/    # 向量库抽象 (ChromaDB/Milvus)
│   │   └── tasks/           # Celery 异步任务
│   └── tests/
├── frontend/
│   └── src/
│       ├── api/             # Axios 请求层
│       ├── stores/          # Zustand 状态管理
│       ├── components/      # 公共组件
│       ├── pages/           # 路由页面 (17 页)
│       └── i18n/            # 中英文国际化
└── docs/
```

## 数据库表

| 表名 | 用途 |
|------|------|
| users | 用户账户 |
| knowledge_bases | 知识库 |
| kb_members | KB成员权限 |
| documents | 文档元数据 |
| document_chunks | 文档分块 |
| conversations | 对话会话 |
| messages | 对话消息 |
| feedback_details | 反馈详情 |
| eval_datasets | 评估数据集 |
| eval_qa_pairs | 评估问答对 |
| eval_results | 评估结果 |
| experiments | A/B实验 |
| exercises | 复习题目 |
| exercise_states | 复习进度 / SM-2 排程 |
| learning_paths | 知识图谱边 |
| llm_profiles | LLM 运行配置 |
| system_config | 系统配置 |
| operation_logs | 审计日志 |

## API 端点

### 认证 (`/api/v1/auth`)
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /auth/register | 注册 |
| POST | /auth/login | 登录 |
| POST | /auth/refresh | 刷新令牌 |
| GET | /auth/me | 当前用户 |

### 知识库 (`/api/v1/kbs`)
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /kbs | 列表 |
| POST | /kbs | 创建 |
| GET/PATCH/DELETE | /kbs/{id} | 详情/更新/删除 |
| GET/POST/DELETE | /kbs/{id}/members | 成员管理 |

### 文档 (`/api/v1/kbs/{id}/documents`)
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /documents | 列表 |
| POST | /documents/upload | 上传文件 |
| POST | /documents/from-url | URL导入 |
| POST | /documents/from-git | Git导入 |

### 聊天 (`/api/v1/chat`)
| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | /conversations | 列表/创建 |
| GET/POST | /conversations/{id}/messages | 消息列表/发送 |
| POST | /conversations/{id}/stream | SSE流式 |

### 知识复习
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /exercises/generate | LLM 出题 |
| POST | /exercises/generate-async | 异步出题（Celery） |
| POST | /exercises/sessions/start | 开始学习会话 |
| POST | /exercises/sessions/answer | 提交答案，SM-2 排程更新 |
| GET | /exercises/stats/{kb_id} | 学习统计 |

## 开发记录

### 2026-07-13 (continued)

1. **Windows 环境问题根治 — 端口漂移 + GBK 编码** — `main.py` 启动时强制 UTF-8（`reconfigure(encoding="utf-8", errors="replace")`）；新增 `start_all.ps1`/`start_all.sh` 启动脚本（自动清理僵尸进程 + 端口检测 + Vite 代理对齐）。编码崩溃清零，一键启动不再手动换端口。

2. **学习页面三模式重构 + 一键出题** — 页面改为三个独立学习模式：Continue Learning（新题）/ Review Past（回看旧题）/ SM-2 Review（间隔重复到期提醒）。新增 +20 More 和 Generate All 两个出题按钮，替代之前需要去 Swagger 手动调 API。后端 `get_due_exercises` 新增 `mode` 参数（new/due/review/all）。

3. **出题功能完善 — 中文题目 + SM-2 可视化 + KB 筛选修复** — 出题 prompt 中文化（Java KB 32 题 + Python KB 30 题）；答题反馈显式展示"Next review: X days"；KB 选择器隐藏纯模型选项；chunk 白名单补全。

4. **数据清洗管道增强 — 噪声深度过滤 + 孤儿标题清理 + 文档去重** — `NoiseLineFilter` 扩展到 30+ 种模式；`UnicodeSanitizer` 修复 nbsp；分块器 MIN_CONTENT_CHARS=30；doc_hash 查重。Java KB chunks 1,821→1,527（-16%）。

5. **向量切片出题 + SM-2 间隔重复学习** — LLM 自动出题 + SM-2 排程。四种题型、EF 差异化、猜测惩罚。新增 `core/learning/sm2.py`、`services/exercise_service.py`、`api/v1/exercises.py`、`QuizPage.tsx`。

6. **Java 公开资料收集与清洗** — W3Schools Java Tutorial 44 篇 → 预处理管道 → Java KB（44 docs / 1,527 chunks）。

### 2026-07-13

1. **查询标准化管道（意图分类 + 五阶段改写）** — 解决所有消息无差别走 RAG 的问题。  
   - **意图分类器**：两层架构（快速正则 + LLM 兜底），将消息分为 `greeting/meta/knowledge/clarification` 四类
   - **五阶段查询标准化**：①上下文补全（代词消解）→ ②文本清洗（规则）→ ③LLM 查询改写（核心）→ ④术语扩展（术语表 + LLM）→ ⑤多路并行检索合并
   - **意图分流路由**：greeting/meta → 纯 LLM（独立 system prompt，自然回答），knowledge/clarification → 完整 RAG 管道
   - **效果**："hello" 从 5 chunks + 元组教程推销 → 0 chunks, "Hi there!"
   - 新增 `core/rag/intent_classifier.py`、`core/rag/query_standardizer.py`、`core/rag/terminology.py`（32 个 Python 术语表）

2. **KB 选择功能 + 向量元数据增强** — 用户创建新对话时可选择知识库来源。  
   - **前端**：新增 `KBSelectorModal` 组件（卡片式 KB 列表 + "纯模型对话"选项），`ChatPage` 侧边栏和聊天头部显示 KB 标签
   - **后端**：`process_file/process_url` chunk metadata 新增 `doc_title`、`kb_id`、`doc_id` 三个标签
   - **效果**：选 KB 后只检索该 KB 的分块，配合意图分类双重节省 token

### 2026-07-10

1. **修复智能问答缺乏对话记忆** — `ChatService.send_message_and_get_answer()` 和 `stream_answer()` 调用 RAG 管道/LLM 时未传递历史消息，导致同一会话中多轮对话无法记住上文。  
   **典型场景**：用户先问"使用 C 语言不注意内存回收常见的问题"，系统返回详细解答；用户追问"如何避免这些问题？"——系统却回复泛泛的"请说明你指的是什么问题"，无法关联到 C 内存管理。  
   **修复**：新增 `_get_recent_history()` 取最近 10 条消息（时间倒序→反转→dict 列表）。KB 路径传 `conversation_history` 给 `RAGPipeline.generate_answer/generate_stream`（`_build_prompt` 将最近 6 条嵌入 prompt）；非 KB 路径将历史拼入 prompt 文本。两个方法均已修复。

2. **修复前端 API 代理端口** — `vite.config.ts` 代理 `/api` → `localhost:8083` 应为 `localhost:8080`，导致登录及所有 API 请求失败。

3. **修复后端构建配置** — `pyproject.toml` 缺少 `[tool.hatch.build.targets.wheel]` 配置，`packages = ["app"]`，`pip install -e` 失败。

4. **清理后端 node_modules** — 后端目录下存在残余的 `package.json` + `node_modules`，干扰前端 Vite 的模块解析，已移除。

5. **修复流式生成时页面抖动** — 流式回复时每个 token 都触发 `scrollIntoView({ behavior: 'smooth' })`，数百个平滑动画堆积互相打断，导致页面上下抖动不流畅。  
   **修复**：
   - 流式期间用 `behavior: 'auto'`（即时滚动），只在非流式时用 `smooth`
   - 用 `requestAnimationFrame` 合并同一帧内的多次滚动调用（顶多 60fps）
   - 消息容器加 `overflowAnchor: 'auto'`（CSS 原生滚动锚定），流式气泡加 `overflowAnchor: 'none'` 避免新增内容与锚定冲突
   - `MessageBubble` 组件用 `React.memo` 避免历史消息重复渲染
   - `MarkdownRenderer` 用 `React.memo` 避免同内容重复解析

6. **修复 ChromaDB 内存模式 + RAG 管道 bug**  
   - **持久化**：ChromaDB 从内存模式改为 `PersistentClient`（路径 `./data/chroma_db`），重启后向量数据不再丢失。新增配置 `CHROMA_PERSIST_PATH`
   - **RAG 首次真正跑通**：修复了两个隐藏 bug — `count_tokens` 未 `await`（返回协程对象而非整数）；`kb_id` 作为 UUID 对象传入 JSON 字段（非 JSON 可序列化）
   - 上传 `智能交互案例1.txt` 到 admin's KB 作为第一篇知识库文档，验证 RAG 检索+生成链路完整可用

7. **新增文档数据清洗模块（毕业设计学术增强）**
   - 在 `DocumentPipeline` 的 parse → chunk 之间插入 **责任链模式清洗层**，6 个清洗器可独立开关
   - 清洗器：`UnicodeSanitizer`（全角→半角/NFC归一）、`HTMLResidueCleaner`（残留标签）、`WhitespaceNormalizer`（换行/空行）、`NoiseLineFilter`（版权/广告噪声）、`DuplicateParagraphDeduplicator`（段落去重）、`TrailingWhitespaceRemover`（行尾空白）
   - 配置化（`CLEANING_*`），可在论文中做有清洗 vs 无清洗的对比消融实验
   - 清洗统计保存到 `doc.metadata_json`，前端文档表格展示清洗前后字数对比及删除百分比

## 配置说明

### LLM API Key 优先级
1. 系统环境变量 `LLM_API_KEY` (通过 `setx` 设置)
2. `.env` 文件中 `LLM_API_KEY=`
3. `.env` 文件中 `OPENAI_API_KEY=`

### 数据库切换
```env
# MySQL (当前)
DATABASE_URL=mysql+asyncmy://root:root@localhost:3309/coderag

# SQLite (开发)
DATABASE_URL=sqlite+aiosqlite:///./coderag.db

# PostgreSQL (生产)
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/coderag
```
