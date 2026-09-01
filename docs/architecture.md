# CodeRAG 架构文档

## 系统架构

```
┌────────────────────────────────────────────────────┐
│                  Frontend (React)                   │
│   ChatUI │ KB Mgmt │ Eval │ Config │ Admin         │
└────────────────────┬───────────────────────────────┘
                     │ Axios / SSE
┌────────────────────┴───────────────────────────────┐
│               FastAPI Backend                       │
│  ┌─────────────────────────────────────────────┐   │
│  │           API Layer (REST + SSE)             │   │
│  └──────┬──────┬──────┬──────┬─────────────────┘   │
│         │      │      │      │                      │
│  ┌──────┴──┐ ┌─┴───┐ ┌─┴───┐ ┌┴──────────┐        │
│  │ Auth    │ │KB   │ │Chat │ │Eval/      │        │
│  │ Module  │ │Svc  │ │/RAG │ │Monitor    │        │
│  └─────────┘ └─────┘ └──┬───┘ └───────────┘        │
│                         │                           │
│          ┌──────────────┴──────────────┐            │
│          │     Intent Router (NEW)      │            │
│          │  Tool │ RAG │ Pure LLM       │            │
│          └──────────────────────────────┘            │
│                         │                           │
│          ┌──────────────┴──────────────┐            │
│          │       RAG Pipeline           │            │
│          │  Query → Retrieve → Generate │            │
│          └──────────────────────────────┘            │
│                         │                           │
│  ┌──────────┐  ┌────────┴────────┐  ┌────────────┐ │
│  │ LLM      │  │ Vector Store     │  │ Document    │ │
│  │ Factory  │  │ Factory          │  │ Pipeline    │ │
│  └──────────┘  └─────────────────┘  └─────────────┘ │
│                                                     │
│  ┌──────────────────────────────────────────────┐   │
│  │  RAG 增强层 (2026-07-13)                      │   │
│  │  ┌──────────────────┐ ┌────────────────────┐ │   │
│  │  │ Intent Classifier │ │ Query Standardizer  │ │   │
│  │  │ greeting/meta/    │ │ 动态决策:           │ │   │
│  │  │ tool/knowledge/   │ │ 清晰→FastPath(0 LLM)│ │   │
│  │  │ clarification     │ │ 模糊→合并LLM(1 调用) │ │   │
│  │  └──────────────────┘ └────────────────────┘ │   │
│  │  ┌──────────────────────────────────────┐    │   │
│  │  │  Learning Module                      │    │   │
│  │  │  ┌────────────┐ ┌──────────────────┐ │    │   │
│  │  │  │ Exercise   │ │ SM-2 Scheduler    │ │    │   │
│  │  │  │ Generator  │ │ interval/EF/rep   │ │    │   │
│  │  │  │ (LLM出题)  │ │ 间隔重复排程      │ │    │   │
│  │  │  └────────────┘ └──────────────────┘ │    │   │
│  │  └──────────────────────────────────────┘    │   │
│  │  ┌──────────────────────────────────────┐    │   │
│  │  │  Tool Module (NEW)                    │    │   │
│  │  │  datetime / calculator / weather      │    │   │
│  │  │  currency_converter / unit_converter  │    │   │
│  │  └──────────────────────────────────────┘    │   │
│  └──────────────────────────────────────────────┘   │
│                                                     │
│  ┌──────────────────────────────────────────────┐   │
│  │  GPU Acceleration (NEW)                       │   │
│  │  ┌──────────────────┐ ┌────────────────────┐ │   │
│  │  │ Embedding (CUDA) │ │ Reranker (CUDA)     │ │   │
│  │  │ 8-9x vs CPU      │ │ 6x vs CPU           │ │   │
│  │  └──────────────────┘ └────────────────────┘ │   │
│  └──────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────┘
         │                │                  │
    ┌────▼────┐    ┌──────▼──────┐    ┌─────▼─────┐
    │ DeepSeek │    │ ChromaDB    │    │ MySQL/     │
    │ V4 Flash │    │ (local)     │    │ PostgreSQL │
    └─────────┘    └─────────────┘    └────────────┘
```

## Intent Router — 多路径智能问答路由 (2026-07-16)

```
用户问题 → classify_intent()
             │
     ┌───────┼────────┐
     │       │        │
     ▼       ▼        ▼
   Tool    RAG     Pure LLM
(工具执行) (知识库)  (纯模型)
```

| 意图 | 示例 | 路由 |
|------|------|------|
| `tool` | "现在几点了", "123乘456" | 直接调用工具模块，0 LLM，0 检索 |
| `knowledge` | "元组和列表区别" | 完整 RAG 管道（标准化 → 检索 → 生成） |
| `clarification` | "没懂", "举个例子" | RAG，结合对话历史上下文 |
| `greeting` | "hello", "谢谢" | 纯 LLM + 自然对话 prompt，不检索 |
| `meta` | "你能做什么", "怎么用" | 纯 LLM + 能力介绍 prompt |

来源标识基于执行元数据（`tool_used/retrieval_used/llm_used`）而非文本比例判断。

## RAG 管道详解

### 0. 意图分类 (Intent Classification)
```
用户消息 → 快速正则匹配（greeting/meta/tool 模式，零 LLM 开销）
              ↓ 不确定
        轻量 LLM 分类 → 五类意图
```
| 规则层 | 优先级 | 方法 |
|--------|--------|------|
| Tool (新) | 最高 | `_tool_re` 匹配时间/日期/计算/天气/转换 5 类模式 |
| Greeting / Meta | 高 | 现有 GREETING/META_PATTERNS |
| Clarification | 中 | 短查询匹配 clarification 规则（如含知识词则升级为 KNOWLEDGE） |
| Knowledge | 低 | KNOWLEDGE_KEYWORDS 匹配（40+ 技术词） |

### 1. 查询标准化 (Query Standardization) — 动态优化版
在 `_retrieve()` 之前处理用户问题，采用 **动态决策** 替代固定 5 阶段流程：

```
cleaned_query
     │
     ├── _is_already_retrieval_ready()?
     │      • 含技术关键词
     │      • 无语义歧义（代词/第二人称）
     │      • 非开放式分析
     │      • 有完整语义
     │
     ├── YES → Fast Path (0 LLM 调用)
     │      rewritten = cleaned + 术语表扩展
     │
     └── NO  → 合并 LLM (1 次调用)
            结构化返回 {rewritten, keywords, sub_queries}
```

| 路径 | LLM 调用 | 场景 |
|------|----------|------|
| Fast Path | 0 次 | 清晰技术问题（"Java HashMap原理"） |
| LLM Path | 1 次 | 模糊/代词/开放式（"它怎么用比较好"） |

### 2. 混合检索 — 第一阶段：高召回 (High-Recall Retrieval)
```
Dense:  语义向量相似度 (cosine) — ChromaDB ANN 检索，candidate_k=30
Sparse: BM25 关键词匹配 — rank-bm25 + jieba 分词，candidate_k=30
  - 支持中英文混合，自动构造/刷新索引
  - 缓存基于文档 ID hash 自动失效
  - 可选 metadata 过滤 (filter={"subject": "Java"})
融合:   Reciprocal Rank Fusion (RRF), α=0.6 (dense/sparse 权重)
```

### 3. 重排序 — 第二阶段：高精度 (High-Precision Reranking)
```
RRF 候选 (30) → Cross-Encoder (query, document) 语义打分 → Top-K (5)

模型: cross-encoder/ms-marco-MiniLM-L-6-v2 (可切换 bge-reranker-base 等)
管理: CrossEncoderReranker (单例, 懒加载, GPU自动检测, 异常回退)
```

完整两阶段检索流程:
```
Query
  ├── Dense Retrieval (candidate_k=30)
  └── BM25 Retrieval  (candidate_k=30)
         ↓
      RRF Fusion (candidate_k=30)
         ↓
      Cross-Encoder Re-Rank → Top-K (output_k=5)
         ↓
      LLM Generation
```

### 4. 生成 (Generation)
- 上下文窗口管理 (最后 6 轮对话)
- Prompt 模板: 系统指令 + 知识库上下文 + 对话历史 + 用户问题
- **原始 query 保留在 prompt 中**，标准化 query 仅用于检索
- 流式输出 (SSE)
- 来源引用标注 [source:N]

## 文档处理管道

```
源文件
  → 解析器 (PDF/Markdown/HTML/Code)
  → 数据清洗 (责任链: Unicode归一(含nbsp)→HTML残渣→行尾空格→换行合并→噪声行(30+模式)→段落去重)
  → HTML→Markdown 转换 (标题/列表/代码块/表格结构保留)
  → Markdown 级噪声清洗 (W3Schools/教程网站特有模式)
  → 代码感知分割 (hybrid: heading+code block边界, MIN_CONTENT_CHARS=30)
  → 嵌入向量生成 (sentence-transformers / OpenAI)
  → 文档去重 (doc_hash 查重)
  → ChromaDB 索引存储
```

## 代码感知分割策略

| 语言 | 策略 |
|------|------|
| Python | def/class 边界分割 |
| JavaScript | function/class/arrow 边界 |
| Java | method/class 边界 |
| Go | func/struct 边界 |
| Markdown | 标题 + 代码块边界 |
| 其他 | 递归段落分割 |

	## 异步任务系统 (Celery + Redis)

```
HTTP Request → API (FastAPI)
       │
       ├── 同步短任务: 直接 await service
       │
       └── 异步长任务 (如出题):
             │
             └── POST /exercises/generate-async → task.delay()
                     │
                     ├── Celery Worker (concurrency=4)
                     │     ├── Redis Broker (db 1) ← task queue
                     │     ├── Redis Backend (db 2) → result store
                     │     └── 7 个注册任务
                     │
                     └── GET /tasks/{task_id} → 轮询状态

配置: .env 中 REDIS_URL / CELERY_BROKER_URL / CELERY_RESULT_BACKEND
启动: bash start_celery.sh 或 start_all.sh (自动启动)
```

```
api/v1/* → services/* → core/* + models/*
                          ↓
                    core/rag/
                    ├── pipeline.py          # RAG 主管道
                    ├── intent_classifier.py  # 意图分类 (NEW)
                    ├── query_standardizer.py # 五阶段查询标准化 (NEW)
                    └── terminology.py        # 术语表 + 正则模式 (NEW)
                          ↓
                    llm/ embedding/ vector_store/
```

- **API 层**: 只处理 HTTP 请求/响应，委托给 service 层
- **Service 层**: 业务逻辑编排，调用 core 和 models。`chat_service.py` 负责意图分类 + 分流路由
- **Core 层**: 核心算法实现 (RAG, 查询标准化, 意图分类, 文档处理, SM-2 间隔重复, 自动出题)
- **LLM/Embedding/VectorStore**: 抽象工厂模式，支持运行时切换

## 降级策略

| 场景 | 行为 |
|------|------|
| LLM API Key 未配置 | 返回 "LLM provider not configured" 提示 |
| LLM 出题失败 | 跳过该 chunk，继续处理下一个（不阻塞管道） |
| ChromaDB 不可用 | 嵌入模式降级为内存模式 |
| Redis 不可用 | 跳过缓存，直接查询数据库 |
| Celery 不可用 | 文档处理同步执行 |
| Embedding 模型未安装 | 使用随机向量 (NoopEmbedding) |
| 文档重复上传 | doc_hash 查重，返回 ConflictException |
| 噪声行过滤过度 | 清洗后 word_count < 50 打印 WARN（可调阈值） |

## 数据库 Schema 变更

### CHAR(36) UUID 策略
```python
class CustomUUID(TypeDecorator):
    """PostgreSQL: native UUID; SQLite/MySQL: CHAR(36)"""
```

### JSON 字段
所有动态字段使用 `JSON` 类型 (MySQL 5.7+/PG 9.2+ 原生支持)

### 时间戳
使用 Python `datetime.now` 客户端默认值 (避免数据库 RETURNING 兼容问题)
