# 变更日志 (Changelog)

> 未来计划见 `docs/development-plan.md`

## 2026-08-16 — eval 模块潜伏 bug 修复 + 评估 GT 修正

### 变更 31: eval 模块三处潜伏 bug + chunk GT 全库重标注

**背景**: 给个人 C 语言库测上下文召回率时发现 eval 模块从未被真实调用过（metrics.py 重构后一直处于损坏状态），并暴露 GT 标注方法学问题。

**修复的三个潜伏 bug**:
| 文件 | 问题 |
|------|------|
| `app/core/evaluation/dataset_service.py` | 顶层 import 引用了 metrics.py 重构前的老函数名（`recall_at_k` 等）→ 任何 `/eval/datasets` 调用 500 |
| `app/schemas/misc.py` | `EvalQAPairCreate` 缺 `relevant_doc_ids`/`relevant_doc_titles` 字段 → 文档级 GT 被 pydantic 静默丢弃 |
| `app/services/kb_service.py` | `delete_kb` 未级联删除关联评估数据集 → MySQL 外键约束导致删库 500 |

**GT 标注方法学修正**（`scripts/fix_chunk_gt_global.py`）:
- 旧重标注限定在历史文档归属内匹配 chunk——Python 官方教程章节交叉复杂，历史 doc_id 本身有偏差（"生成器"被标到 glossary.md 术语表），导致 GT 标错、context_recall 系统性低估
- 改为**全库范围语义匹配**：GT chunk = 全库中与"问题+标注说明"最相似的 chunk，同时修正 relevant_doc_ids 为 GT chunk 所属文档
- 修正效果：Python context_recall 0.6786 → 0.7857 →（人工补全 6 道多主题题 GT 后）**0.8929**；Java → **0.9231**。此前"Python < Java"的倒挂确认为标注污染假象

**新增测试脚本**:
| 脚本 | 用途 |
|------|------|
| `scripts/test_c_kb_context_recall.py` | 个人 C 库（4 页）标注 5 题测召回率（发现 top-5≈全库的虚高问题） |
| `scripts/test_c_kb_selected.py` | 精选 30 页主题明确资料 + 10 道考题测真实召回率 |
| `scripts/fix_chunk_gt_global.py` | 全库范围 chunk GT 重标注（修正文档归属偏差） |

**方法论结论**（论文素材）:
- 评估 GT 标注与检索**同源**（embedding 匹配标注）时指标虚高——人工标注是金标准
- "机制/区别"类多主题问题的答案分散多个 chunk，单点 GT 必然假失败，应按需标注 1-2 个必要 chunk
- context_recall 对 chunk 粒度极敏感：大 chunk（~660 tokens）易命中但精度差，小 chunk（~58 tokens）命中难但语义聚焦

---

## 2026-08-16 — 用户上传场景实战：C 语言资料收集 + HTML 清洗管道修复

### 变更 30: W3Schools C 教程收集 + 普通用户上传全链路验证

**背景**: 模拟"普通用户上传个人资料"场景——收集公开 C 语言资料（桌面 `C语言资料/w3schools/`，117 页/25MB），tester1 建个人库直接上传**原始 HTML**（不预清洗），验证清洗→分块→向量化→检索→问答→隔离全链路。

**实战暴露并修复 4 个真实管道问题**:

| # | 问题 | 修复 |
|---|------|------|
| 1 | `HTMLNoiseCleaner` 选择器不覆盖 W3Schools 新版布局（2024+）：顶部导航 `#top-nav-bar`/`#pagetop`、侧边栏 `#sidenav`/`.tut_overview`、广告 `#bottomads`/`#skyscraper` 等全部残留，正文仅占 chunk 的 1/5 | +25 个选择器（`[id^='tnb-']`、`.servicebox`、`#footerwrapper` 等） |
| 2 | **P0: `HTMLResidueCleaner` 的 `<[^>]*>` 正则把 C 代码的 `#include <stdio.h>`、比较运算 `a < b` 当 HTML 标签删除**——c_strings 正文误删 55%（5084→2251 字符） | 改为严格 HTML 标签语法正则（标签名 + 属性语法），`<stdio.h>` 因 `.` 非合法标签字符而保留；+7 个回归测试 |
| 3 | `NoiseLineFilter` 缺 W3Schools 新版 UI 文本（Earn XP/Sign In 等）与残留标签行模式 | +12 个模式（`original:`/`ny:`、markdown 链接形式导航、sharethis 残渣等） |
| 4 | 页面布局示例（`<div class='w3-row'>` 单引号属性）混入正文块 | 针对性模式（`w3-` 前缀 + 单引号属性特征） |

**验证**: 修复后清洗移除率恢复正常（c_strings 65%→17.2%），4 文档上传即索引，RAG 问答质量良好（指针比喻 + 来源引用），隔离验证通过。全套测试 217 个通过（+7 新增）。

**环境教训**: Windows 上 uvicorn `--reload` 的 worker 子进程在父进程被杀后成为孤儿继续占用端口与 **GPU 显存**（5 个残留进程占满 6.6GB/8GB 导致 CUDA OOM）；进程名是 `python3.12` 而非 `python`，清理时需注意。

**新增脚本**:
| 脚本 | 用途 |
|------|------|
| `backend/scripts/download_c_docs.py` | W3Schools C 教程下载（链接自动发现，排除练习页） |
| `backend/scripts/test_user_upload_c.py` | 普通用户上传全链路验证（建库/上传/统计/问答/隔离） |

---

## 2026-08-15 — 质量门控式知识库构建流程（双层模型 + 入库门禁 + 质量报告）

### 变更 29: 知识库双层模型 + 入库质量门禁 + admin 质量报告

**问题**: RAG 平台允许所有用户自由建库，无法保证语料清洗/分块/向量化质量——"上传者非专业，检索质量如何保证"。

**设计**: 质量不能靠上传者把关，由系统在发布前自动跑**检索级评估门禁**（不调 LLM），双指标达标才标记 verified。

**改动**:

| 层 | 文件 | 说明 |
|----|------|------|
| 模型 | `app/models/knowledge_base.py` | + `scope`（platform/personal）、+ `quality_status`、+ `quality_metrics_json` |
| 迁移 | `alembic/versions/a3f9c2d1e4b5_*.py` | 新列 + 存量库标记 platform |
| 配置 | `app/config.py` | + `gate_doc_hit_threshold=0.9`、`gate_context_recall_threshold=0.6`、`gate_k=5` |
| 权限 | `app/services/kb_service.py` | platform 库仅 admin 可建（403）；公开 platform 库全员可见；系统 admin 全库只读治理（无写绕过） |
| 门禁 | `app/core/evaluation/gate.py` **新建** | 检索级评估（doc_hit@5 + context_recall@5，复用 29 条 GT QA）+ 双阈值判定 + 按问题去重（新数据集优先） |
| API | `app/api/v1/knowledge_bases.py` | + `POST /kbs/{id}/quality-gate`、`GET /kbs/quality-report`（均 admin） |
| 前端 | `KBList.tsx` / `QualityReportPage.tsx` **新建** / `App.tsx` / `Sidebar.tsx` | scope/质量状态标签、admin 建库类型选择、质量报告页（清洗/分块/门禁指标 + 一键运行门禁） |
| 修复 | `app/services/chat_service.py` | 建对话绑定 KB 时补校验 `check_kb_access`（封堵凭 kb_id 探测私有库） |

**数据修复**（本轮发现并处理）:
1. `scripts/cleanup_duplicate_eval_datasets.py` — 清理误导入的重复数据集（6 个数据集/73 对 QA，保留 fix_gt.py 修正过的 2 个；备份 `data/dup_datasets_backup.json`）
2. `scripts/reannotate_chunk_gt.py` — 向量集合重建后 chunk id 失效（标注偏移），按"标注说明+问题"语义匹配重标注 27 对 QA 的 chunk GT（备份 `data/chunk_gt_backup.json`）

**实测结果**（真实检索管道 + GPU 重排，~30s/库）:

| 指标 | Python KB | Java KB | 门槛 |
|------|-----------|---------|------|
| doc_hit@5 | 1.0 | 1.0 | ≥ 0.9 ✅ |
| doc MRR | 0.964 | 0.862 | — |
| NDCG@5 | 0.974 | 0.890 | — |
| context_recall@5 | 0.679 | 0.769 | ≥ 0.6 ✅ |
| **判定** | **verified** | **verified** | |

**测试**: +12（门禁判定/去重/作用域/可见性/治理权/报告聚合），全套 210 通过，无回归。

---

## 2026-07-16 — GPU 推理加速 + Query 优化 + Intent Router / 工具调用

### 变更 28: 基于意图识别的多路径智能问答路由机制
**时间**: 2026-07-16 10:00-11:00

**问题**: "现在几点了"被误判为知识库问题，检索到 Python datetime 教程。系统缺少实时工具类问题的处理能力。

**设计**: 新增 `TOOL` 意图类型 + Intent Router 三层分流架构。问题先经路由器判断类型，再分流到 Tool / RAG / Pure LLM 三条路径。

**新增文件**:

| 文件 | 说明 |
|------|------|
| `backend/app/core/tools/__init__.py` | 工具模块：datetime、calculator、weather、currency_converter、unit_converter；模式注册 + 匹配 |

**修改文件**:

| 文件 | 改动 |
|------|------|
| `backend/app/core/rag/intent_classifier.py` | + `TOOL` Intent 枚举值；新增 `_tool_re` 规则模式（时间/日期/计算/天气/转换 5 类）；knowledge 信号优先于 clarification 短路修正 |
| `backend/app/services/chat_service.py` | 重写：+`_route_tool()` 工具执行、+`_route_pure_llm()`、+`_route_rag()`；非流式/流式双端均实现 Intent Router 分流；+`_SOURCE_META` 执行元数据记录（tool_used/retrieval_used/llm_used）；+`_build_footer()` 基于元数据生成来源标识 |
| `backend/app/core/rag/pipeline.py` | generate_stream 增加 phase 阶段事件（analyzing/searching/generating） |
| `frontend/src/api/chat.ts` | StreamEvent + `phase` 类型；ChatStream + `onPhase` 回调 |
| `frontend/src/stores/chatStore.ts` | + `streamPhase` 状态跟踪 |
| `frontend/src/pages/ChatPage.tsx` | + 处理阶段状态指示器（Spin + 文字） |

**来源分类体系**（基于执行元数据，非文本比例）:

| 图标 | 类型 | 条件 |
|------|------|------|
| 🔧 | Tool | `tool_used=True` |
| 📚 | Knowledge | `retrieval_used=True, llm_used=True` |
| 🔀 | Hybrid | `retrieval_used=True, llm_used=True, is_hybrid=True` |
| 🤖 | Pure LLM | `llm_used=True, no retrieval, no tool` |

**最终路由流程**:
```
用户问题 → Intent Router
  ├─ TOOL      → 工具执行 (0 LLM, 0 RAG)          → 🔧
  ├─ KNOWLEDGE → Query Standardizer → RAG Pipeline → 📚/🔀
  ├─ GREETING  → 纯 LLM                           → 🤖
  └─ META      → 纯 LLM                           → 🤖
```

### 变更 27: Query Standardizer 动态优化——Fast Path + 合并 LLM 调用
**时间**: 2026-07-16 09:00-10:00

**问题**: 每条知识类问题都串行调用 3 次 LLM（改写+扩展+多角度查询），即使问题本身已经表达清晰。

**设计**: 增加 `_is_already_retrieval_ready()` 启发式判断。清晰技术问题（含关键词、无语义歧义、非开放式）直接跳过 LLM；复杂问题合并 3 阶段为 1 次结构化 LLM 调用。

**修改文件**:

| 文件 | 改动 |
|------|------|
| `backend/app/core/rag/query_standardizer.py` | 重写：+`_is_already_retrieval_ready()`（6 条规则：技术关键词/代词/开放式/第二人称/完整度/历史依赖）；+`_process_complex_query()` 合并 LLM 返回 rewrite+keywords+sub_queries；修复 CJK `\b` 边界问题 |
| `backend/app/core/rag/intent_classifier.py` | KNOWLEDGE_KEYWORDS 扩展 40+ 词（tcp/redis/hashmap/mysql/线程/锁等） |
| `backend/tests/test_rag_pipeline.py` | 更新流式事件测试（适配新增 phase 事件） |
| `backend/benchmarks/benchmark_query_optimizer.py` | 新建对比测试脚本 |

**性能对比**:

| 维度 | 优化前 | 优化后 |
|------|--------|--------|
| 简单问题 LLM 调用 | 3 次 | 0 次 |
| 复杂问题 LLM 调用 | 3 次 | 1 次 |
| 总体 LLM 调用节省 | — | 83% |
| 20 样本分类正确率 | — | 20/20 (100%) |

### 变更 26: CUDA GPU 推理加速——Embedding + Reranker
**时间**: 2026-07-16 08:30-09:00

**问题**: 项目拥有 RTX 4070 Laptop 8GB 显卡和 CUDA 13.3 驱动，但 PyTorch 安装的是 CPU-only 版本，Embedding 和 Reranker 全部在 CPU 上推理。

**设计**: 更换 CUDA 版 PyTorch（2.13.0+cu126），统一设备检测工具，Embedding 和 Reranker 自动使用 GPU。

**修改文件**:

| 文件 | 改动 |
|------|------|
| `backend/app/utils/device.py` | **新建** — 统一设备检测 `get_device()`（cuda/cpu 自动检测，结果缓存） |
| `backend/app/embedding/local_embedding.py` | `SentenceTransformer(model_name, device=get_device())` |
| `backend/pyproject.toml` | （无改动 — torch 由 pip 管理非 pyproject 依赖） |
| `backend/benchmarks/benchmark_gpu.py` | **新建** — GPU vs CPU 性能对比脚本 |

**加速效果**（RTX 4070 Laptop GPU vs CPU）:

| 场景 | CPU | GPU | 加速比 |
|------|-----|-----|--------|
| Embedding 100 chunks | 0.314s (319/s) | **0.035s (2852/s)** | **9.0x** |
| Embedding 500 chunks | 1.832s (273/s) | **0.251s (1992/s)** | **7.3x** |
| Reranker 50 candidates | 170.75ms | **26.39ms** | **6.5x** |

**注意**: PyTorch CUDA 版本通过 `pip install torch --index-url https://download.pytorch.org/whl/cu126` 单独安装，不在 pyproject.toml 中锁定，避免 CI 环境因缺失 CUDA 驱动而失败。

### 变更 25: Redis/Celery 异步任务系统集成

**时间**: 2026-07-16

**问题**: Redis/Celery 未运行，异步任务不可用。出题管道（`generate_for_kb`）在 HTTP 请求中同步执行，对大量 chunk 的 KB（如 Java KB 1527 chunk）需要等待 10min+，用户体验差。

**设计**: 安装并配置 Redis（Windows Redis 3.0.504），集成 Celery 任务系统，新增异步出题端点 + 任务状态查询端点。

**改动**:

| 文件 | 改动 |
|------|------|
| `backend/.env` | 启用 Redis/Celery URL（`redis://localhost:6379/0-2`） |
| `backend/app/tasks/celery_app.py` | Monkey-patch RESP2 协议兼容 Redis 3.x；注册 exercise_generation 任务 |
| `backend/app/tasks/exercise_generation.py` | **新建** — Celery 任务包装 `ExerciseService.generate_for_kb` |
| `backend/app/db/redis.py` | 重写为懒加载单例 + RESP2 patch |
| `backend/app/api/v1/exercises.py` | + `POST /generate-async` 异步提交 + `GET /tasks/{task_id}` 状态查询 |
| `backend/app/schemas/exercise.py` | + `GenerateExercisesAsyncResponse`、`TaskStatusResponse` |
| `backend/pyproject.toml` | 放宽 redis 版本约束（兼容 4.x） |
| `backend/start_celery.sh` | **新建** — Celery worker 启动脚本 |
| `backend/start_all.sh` | 集成 Celery worker 自动启动 |

**Celery 任务列表** (共 7 个):

| 任务 | 说明 |
|------|------|
| `index_document` | 文档索引 |
| `index_url` | URL 索引 |
| `rebuild_kb_index` | 知识库重建 |
| `sync_git_repo` | Git 仓库同步 |
| `run_evaluation_task` | 评估运行 |
| `run_experiment_task` | A/B 实验 |
| `generate_exercises_task` | **新增** — 出题生成 |

**启动方式**:
```bash
# 启动全部 (Redis 必须已作为 Windows 服务运行)
bash start_all.sh     # 后端 + 前端 + Celery

# 或单独启动 Celery
bash start_celery.sh

# 手动启动 Celery
cd backend
python -m celery -A app.tasks.celery_app worker --loglevel=info --concurrency=4
```

**API 使用**:
```bash
# 异步提交出题
curl -X POST /api/v1/exercises/generate-async \
  -H "Authorization: Bearer <token>" \
  -d '{"kb_id":"...", "limit": 20}'
# → {"kb_id":"...", "task_id":"...", "status":"pending"}

# 轮询状态
curl GET /api/v1/exercises/tasks/{task_id} \
  -H "Authorization: Bearer <token>"
# → {"task_id":"...", "status":"SUCCESS", "result":{...}}

# 同步出题（原有，短任务使用）
curl POST /api/v1/exercises/generate \
  ...（同上，同步等待）
```

**限制**: 当前开发环境使用 Redis 3.0 for Windows，需 RESP2 协议兼容层。生产环境建议升级至 Redis 6+ 或 Memurai。

---

### 变更 24: Cross-Encoder Re-Ranker 集成 — 两阶段混合检索增强

**时间**: 2026-07-16

**问题**: 当前 RAG 检索流为 `Dense + BM25 → RRF → Top-K`，缺少语义级精排环节。Hybrid Fusion 仅基于 RRF 位置分，无法对候选结果进行细粒度的 (query, document) 相关性判断，排在后面的高相关文档容易被截断。

**设计**: 在 RRF 融合之后新增 Cross-Encoder 重排序阶段，形成完整的两阶段检索架构：

```
Query
  ├── Dense Retrieval (semantic, candidate_k=30)
  └── BM25 Retrieval  (keyword,  candidate_k=30)
         ↓
      RRF Fusion (candidate_k=30)
         ↓
      Cross-Encoder Re-Rank → Top-K (output_k=5)
         ↓
      LLM Generation
```

**架构**:
```
app/core/rag/reranker.py
  └── CrossEncoderReranker       — singleton, lazy-load, GPU auto-detect
        ├── rerank()             — (query, documents) → re-ranked top-k
        ├── load_model()         — explicit model (re)load / switch
        └── get_model_info()     — runtime inspection
```

**模块特性**:

| 特性 | 说明 |
|------|------|
| 模型可配置 | 默认 `cross-encoder/ms-marco-MiniLM-L-6-v2`，可切换 `bge-reranker-base` 等中文模型 |
| 单例管理 | 服务启动/首次请求时加载，不重复下载 |
| GPU 自动检测 | CUDA → MPS → CPU 自动降级 |
| 异常兜底 | 模型加载失败 / 预测异常 → 自动返回 RRF 原始结果 |
| Alpha 独立 | dense/sparse 权重 (RRF) 与 Cross-Encoder 精排互不影响 |

**配置** (`app/config.py` + `.env`):

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `RERANK_ENABLED` | `true` | 总开关 |
| `RERANK_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | 模型名称 |
| `RERANK_CANDIDATE_K` | `30` | 送入 reranker 的候选项数 |
| `RERANK_OUTPUT_K` | `5` | 最终返回数 |
| `RERANK_BATCH_SIZE` | `16` | 推理批次 |

**修改文件**:
| 文件 | 改动 |
|------|------|
| `backend/app/core/rag/reranker.py` | **新建** — CrossEncoderReranker (~150 行) |
| `backend/app/core/rag/pipeline.py` | `_retrieve` 扩展 recall 至 candidate_k；`_rerank` 替换为真实 CrossEncoder 调用；`search_only/generate_answer/generate_stream` 输出增加 `rerank_score` |
| `backend/app/config.py` | + 5 项 rerank 配置 |
| `backend/.env` | + rerank 配置默认值 |
| `backend/tests/test_reranker.py` | **新建** — 14 个测试用例 |

**测试覆盖** (14 个):
| 类别 | 测试点 |
|------|--------|
| Reranker 单元 (7) | 排序准确性、top_k 限制、空文档、模型加载失败回退、单例、get_model_info、rerank_score 注入 |
| Pipeline 集成 (4) | 扩展 recall、rerank on/off、search_only rerank、generate_answer 含 rerank_score |
| 中文场景 (1) | "快速排序时间复杂度" — 排序文档优先 |
| 两阶段验证 (2) | RRF 未被替代、Alpha 与 rerank 独立 |

**论文描述**:
> 系统采用两阶段混合检索架构，首先利用 Dense Retrieval 和 BM25 Sparse Retrieval 进行多源知识召回，通过 RRF 算法融合候选结果，再利用 Cross Encoder 模型进行语义级重排序，提高知识匹配准确率，为后续智能出题和个性化学习提供高质量知识支持。

**验证**: 全部 194 个测试通过（14 新 + 180 原），无回归。

### 变更 23: KB 计数器缓存修复

**时间**: 2026-07-16

**问题**: `knowledge_bases.doc_count` 和 `chunk_count` 在文档增删后从未更新，始终为 0，导致 KB 列表/详情页显示错误。

**修改文件**:
| 文件 | 改动 |
|------|------|
| `backend/app/services/kb_service.py` | 新增 `sync_counters()` 单 KB 同步 + `sync_all_counters()` 全量修复 |
| `backend/app/services/document_service.py` | `upload_file` / `import_from_url` / `delete_document` 完成后自动调用 sync |
| `backend/app/api/v1/knowledge_bases.py` | 新增 `POST /kbs/sync-all-counts` 批量修复端点 |

**验证结果**:
```
python  KB: 0/0 → 24/991    ✅
Java KB: 0/0 → 44/1527   ✅
java KB: 0/0 → 0/0       ✅ 空 KB 正确
```

---

### 变更 22: BM25 稀疏检索实装 — 中英混合分词 + 按需缓存 + Metadata 过滤

**时间**: 2026-07-16

**问题**: `_sparse_search` 是空实现（返回 `[]`），hybrid 策略实际退化为纯 dense 检索，关键词匹配能力缺失。

**设计**: 基于 `rank-bm25` 实现完整的 BM25 稀疏检索器，支持中文/英文混合分词、文档 hash 缓存失效、metadata 过滤。

**架构**:
```
BM25SparseRetriever
  ├── MixedTokenizer       — jieba 中文分词 + regex 英文/代码标识符 + 停用词过滤
  ├── _BM25Index           — 每个 collection 独立的 BM25 + docs 缓存
  ├── search()             — 自动构建/刷新 + 后置 metadata 过滤 + 统一返回格式
  └── invalidate()         — 手动/自动生命周期管理
```

**Tokenizer 特性**:
| 特性 | 说明 |
|------|------|
| 中文分词 | jieba 精确模式，预注入 50+ 技术术语（HashMap/快速排序/多线程等） |
| 英文/代码 | regex 保留 `_` `-` `+`（如 `__init__`、`spring-boot`、`C++`） |
| 停用词 | 100+ CN/EN 无意义词，支持自定义覆盖 |
| 纯数字过滤 | 独立数字 token 丢弃，`3.12` 等组合保留 |

**缓存失效机制**:
```
cache_key = (collection_name, docs_hash)
其中 docs_hash = SHA256(sorted(doc_ids))[:16]
```
- 文档增/删 → hash 变化 → 自动重建 BM25
- 同数量替换 → hash 变化 → 仍能检测
- 每个 collection 独立缓存

**Metadata 过滤**:
```
filter={"subject": "Java"}  → 只返回 Java 文档
```
- 后置过滤：在全量 BM25 结果上按 metadata 精确匹配
- 支持未来按科目/语言/框架限定检索域

**结果格式**: `{id, score, document, metadata}` — 与 dense retriever 完全一致，直接进入 `_hybrid_fusion()` RRF 融合

**新增文件**:
| 文件 | 说明 |
|------|------|
| `backend/app/core/rag/retrieval/__init__.py` | 包入口，导出 BM25SparseRetriever |
| `backend/app/core/rag/retrieval/bm25_retriever.py` | BM25SparseRetriever (~270 行) + MixedTokenizer + 缓存 + 过滤 |
| `backend/tests/test_bm25_retriever.py` | 25 个测试用例 |

**修改文件**:
| 文件 | 改动 |
|------|------|
| `backend/app/vector_store/base.py` | + `get_all_documents()` 抽象方法 |
| `backend/app/vector_store/chroma_store.py` | + `get_all_documents()` ChromaDB 实现（`collection.get()`） |
| `backend/app/core/rag/pipeline.py` | `_sparse_search` 替换为真实 BM25 调用（异常回退返回空） |
| `backend/app/core/rag/retrieval/__init__.py` | 导出 BM25SparseRetriever |
| `backend/tests/conftest.py` | MockVectorStore + `get_all_documents()` |
| `backend/pyproject.toml` | + `jieba>=0.42.1` |
| `CLAUDE.md` | 更新已知问题：BM25 标记为已实装 |

**测试覆盖** (25 个)**:**
| 类别 | 测试点 |
|------|--------|
| Tokenizer (8) | 中文分词、英文、混合 CN/EN、代码关键词、空输入、停用词、数字过滤、自定义停用词 |
| 检索 (4) | 英文 BM25、中文检索、代码关键词、格式验证 |
| Metadata 过滤 (4) | Java/Python 过滤、不匹配返回空、中文 subject 过滤 |
| 缓存 (4) | 命中、增文档重建、删文档重建、invalidate 隔离 |
| 生命周期 (3) | invalidate_all、get_stats、空 collection |
| 边界 (2) | 空查询、k > corpus |

**验证**: 全部 180 个测试通过（25 新 + 155 原），无回归。

---

## 2026-07-13 — 查询标准化 + KB 选择 + 切片出题

### 变更 21: Windows 环境问题根治 — 端口漂移 + GBK 编码崩溃

**时间**: 2026-07-13

**问题**: 
1. 端口僵尸进程——8080/8081/8082/8083 被残留 Python 进程占用，`taskkill` 无法清除；每次重启都要手动换端口，后端已从 8080 漂移到 8085
2. GBK 编码——Windows 控制台默认 GBK（cp936），Python 输出 emoji 或 CJK 扩展字符时触发 `UnicodeEncodeError` 崩溃；curl 传中文 Body 失败

**设计**: 三层修复——Python 层（main.py 启动时强制 UTF-8）、Shell 层（启动脚本设置环境变量）、配置层（固定端口 + Vite 代理对齐）。

**修改文件**:
| 文件 | 改动 |
|------|------|
| `backend/app/main.py` | 所有 import 之前插入 UTF-8 强制配置——`PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`、`sys.stdout/stderr.reconfigure(encoding="utf-8", errors="replace")` |
| `backend/.env` | 新增 `BACKEND_PORT=8085` |
| `start_all.ps1` | **新建**——Windows PowerShell 启动脚本：chcp 65001 → 检测并 kill 8080-8085 上的 python 僵尸进程 → 自动扫描可用端口 → 对齐 Vite 代理 → 启动后端+前端 → 保持运行 |
| `start_all.sh` | **新建**——Git Bash/Linux 启动脚本：UTF-8 环境变量 → pkill 清理 → 端口检测 → sed 更新 Vite 配置 → 启动 |
| `frontend/vite.config.ts` | proxy target 固定为 `localhost:8085` |
| `CLAUDE.md` | 启动命令更新（推荐使用脚本 + 手动命令加 UTF-8 环境变量）；已知问题列表更新（端口/编码标记为已修复） |

**效果**: `0 encoding errors`；一次 `.\start_all.ps1` 即可启动全部服务，不再手动换端口。

---

### 变更 20: 学习页面三模式重构 + 一键出题按钮

**时间**: 2026-07-13

**问题**:
1. 学习页面只有一个"Start Review"按钮，用户无法区分"学新题"、"复习旧题"、"SM-2 到期提醒"三种需求
2. 题目生成只能通过 Swagger API 手动调，页面无入口——用户看到"No exercises yet"后不知道该做什么
3. SM-2 排程数据需要用户先做题才能体现，初始状态 due=0 时页面完全空白

**设计**: 页面重新设计为三个独立的学习模式 + 两个出题按钮。

**三模式架构**:
| 模式 | API mode 参数 | 逻辑 | 按钮文案 |
|:--|:--|:--|:--|
| Continue Learning | `new` | 仅返回从未做过的题 | "Continue Learning (36 new)" |
| Review Past | `review` | 返回所有已尝试过的题（主动复习） | "Review Past Questions (5 attempted)" |
| SM-2 Review | `due` | 仅返回 SM-2 排程到期的题（被动提醒） | "SM-2 Review (3 due today)" |

**出题按钮**:
| 按钮 | API 调用 | 行为 |
|:--|:--|:--|
| +20 More | `POST /exercises/generate {"limit": 20}` | 处理 20 个 chunk，约 20-40 道题，~40 秒 |
| Generate All | `POST /exercises/generate {}` | 处理所有未出题的 chunk，后台运行 |

**修改文件**:
| 文件 | 改动 |
|------|------|
| `backend/app/services/exercise_service.py` | `get_due_exercises` 新增 `mode` 参数——new/due/review/all 四种过滤模式 |
| `backend/app/schemas/exercise.py` | `SessionStartRequest` 新增 `mode` 字段 |
| `backend/app/api/v1/exercises.py` | start session 端点传递 mode |
| `frontend/src/api/exercises.ts` | `startSession` 签名改为 opts 对象，支持 mode 参数 |
| `frontend/src/pages/QuizPage.tsx` | 完整重写欢迎页——三模式按钮 + 紧凑统计行 + 出题按钮 + 生成结果反馈；`handleStartSession(mode)` 和 `handleGenerate(limit?)` 两个核心 handler |

**验证数据**:
```
mode=new      → 35 exercises  (剩余新题)
mode=review   → 1  exercises  (已答过的题，可主动复习)
mode=due      → 1  exercises  (SM-2 排程到期)
mode=all      → 36 exercises  (new + due)
```

---

### 变更 19: 出题功能完善 — 中文题目 + SM-2 可视化 + KB 筛选修复

**时间**: 2026-07-13

**问题**:
1. 出题 prompt 为英文，生成的题目全是英文，不符合中文学习场景
2. 学习页面的 KB 选择器错误地显示了"纯模型对话"选项——出题必须来自知识库，纯 LLM 无意义
3. SM-2 排程在用户界面不可见——答题后只有一行小字 `SM-2: interval=1d`，用户感受不到间隔重复的价值
4. Python KB 无法出题——chunk 类型 `text_heading` 和 `code_block` 不在生成白名单中
5. 出题管道限流 `sleep(2)` 过慢，生成 20 个 chunk 需要 4 分钟
6. 新部署时后端端口不固定（8080→8085 漂移），前端 Vite 代理目标需手动更新

**修改文件**:
| 文件 | 改动 |
|------|------|
| `backend/app/services/exercise_service.py` | a) prompt 全部改为中文——system/user prompt 要求输出中文题干/选项/解析；b) chunk 类型白名单新增 `text_heading`、`code_block_javascript/go/rust`；c) min token 从 30 降到 15；d) 限流从 2s 降到 0.5s |
| `frontend/src/pages/QuizPage.tsx` | a) KB 选择器传入 `showPureLLM={false}`；b) 欢迎页 SM-2 仪表盘——四格卡片（Due Today / New / Mastered / Weak）+ 排程说明；c) 答题反馈卡——明确显示"Next review: X days" + 绿色 Mastered 标签 / 红色 Weak 标签；d) select KB 后自动加载 stats |
| `frontend/src/components/Chat/KBSelectorModal.tsx` | 新增 `showPureLLM` prop（默认 true），为 false 时隐藏纯模型选项 |
| `frontend/vite.config.ts` | proxy target 改为 `localhost:8085` |

**生成结果**: Java KB 32 题 + Python KB 30 题，全部中文。样题："在Java中，Error和Exception的共同基类是哪个？"、"关于Java包装类（Wrapper Classes）的描述，以下哪一项是正确的？"

---

### 变更 18: 数据清洗管道增强 — 噪声深度过滤 + 孤儿标题清理 + 文档去重

**时间**: 2026-07-13

**问题**:
1. 清洗管道仅做 DOM 级清洗（删除 `<nav>`/`<footer>` 等标签），W3Schools 特有的内嵌文本噪声（"Contact Sales"、"Track your progress"、"❮ Previous Next ❯"）残留在正文中，成为低质量 chunk
2. 孤儿标题（"### Example"、"### Syntax"）——教程中章节标题在清洗后失去内容，被分块器单独切为 2-token 的无效 chunk
3. `\xa0` 不换行空格未归一化，导致 GBK 编码崩溃
4. 同一文件可无限重复上传——`doc_hash` 已计算但从未被查询用于去重

**设计**: 三层改进——预处理级（MD 生成后过滤）→ 后端清洗级（NoiseLineFilter 扩展）→ 分块器级（最小长度过滤）。

**修改文件**:
| 文件 | 改动 |
|------|------|
| `backend/scripts/preprocess_java_docs.py` | 新增 `clean_markdown_noise()` 函数——20+ 种 W3Schools 特有噪声正则，在 HTML→MD 转换后执行 |
| `backend/app/core/documents/cleaners/rules.py` | a) `NoiseLineFilter` 从 12 种模式扩展到 30+ 种——导航文字/推销文案/孤儿标题/版权声明/教程UI文本；b) `UnicodeSanitizer` 新增 `\xa0`→空格归一化 |
| `backend/app/core/documents/chunkers/hybrid.py` | `_split_markdown` 末尾新增 `MIN_CONTENT_CHARS = 30` 过滤，丢弃过短碎片 chunk |
| `backend/app/services/document_service.py` | 上传前查询 `doc_hash`，已存在则拒绝重复导入（`ConflictException`） |

**效果对比**:
| 指标 | 改进前 | 改进后 | 降幅 |
|:--|:--|:--|:--|
| Java KB chunks | 1,821 | 1,527 | -16% |
| 噪声示例 | "Contact Sales"、"### Example"、"W3Schools offers..." | 全部清除 | — |
| 最短 chunk | 2 tokens（孤儿标题） | 7 tokens（代码片段 `capitalCities.clear()`） | — |
| 重复文档防护 | 无 | doc_hash 查重 | — |

---

## 2026-07-13 — 查询标准化 + KB 选择 + 切片出题（续）

### 变更 17: 知识库数据采集 — Java 公开资料收集与清洗

**时间**: 2026-07-13

**问题**: 系统仅有 Python 中文教程一个知识库，需要扩展多语言编程知识覆盖。

**设计**: 按"原始下载 → 清洗管道 → Markdown → 导入 KB"流程，收集 W3Schools Java Tutorial 45 篇教程。

**新增文件**:
| 文件 | 说明 |
|------|------|
| `backend/scripts/download_java_docs.py` | 批量下载 W3Schools Java 教程 HTML（44/45 成功，9.8MB） |
| `backend/scripts/preprocess_java_docs.py` | Java 专用预处理脚本——复用 `app.core.documents.converters.html_to_md` 共享模块 |

**数据目录**:
```
知识库资料/Java/w3schools/*.html       ← 原始 HTML（44 文件，9.8MB）
知识库资料_clean/Java/w3schools/*.md   ← 清洗后 Markdown（44 文件，1.4MB，带 YAML front matter）
```

**KB 导入结果**: Java KB — 44 文档 / 1,821 分块 / 347,031 tokens / 平均 190.6 tokens/chunk

---

### 变更 16: 向量切片自动出题 + SM-2 间隔重复学习

**时间**: 2026-07-13

**问题**: RAG 系统只有"问答"一种交互模式。用户无法通过主动回忆（active recall）巩固知识，缺乏学习闭环。

**设计**: 文档切片入库时/后由 LLM 自动生成选择题，搭配 SM-2 间隔重复算法实现"切片入库即出题"的学习闭环。同时从变更 15 学到的 KB 选择模式复用到学习页面。

**闭环流程**:
```
文档切片入库 → LLM 生成 1-2 道题 → exercises 表
     ↓
用户选择 KB → 开始学习会话 → 逐题呈现
     ↓
用户作答 → SM-2 更新排程 → 即时反馈 + 解析
     ↓
薄弱点标记 → 下次复习优先级提升 → 统计可视化
```

**SM-2 算法适配**（针对编程选择题的三个调整）:
| 调整 | 原因 | 实现 |
|------|------|------|
| 初始 EF 按难度差异化 | 难题遗忘快于简单题 | easy=2.5, medium=2.3, hard=2.0 |
| 首次答对 ×0.7 惩罚 | 4选1有25%猜测概率 | GUESS_PENALTY=0.7 |
| 二值化评分 | 选择题无自评回忆轻松度 | correct→q=4, wrong→q=1 |

**四种题型**:
| 类型 | 适用切片 | 示例 |
|------|---------|------|
| `concept_match` | 概念解释 | "filter() 属于哪种操作？" |
| `code_fill` | API 参考 | "以下哪个是正确的 filter 调用？" |
| `output_predict` | 代码示例 | "以下代码输出是什么？" |
| `error_diagnose` | 错误模式 | "以下代码有什么问题？" |

**新增文件**:
| 文件 | 说明 |
|------|------|
| `backend/app/core/learning/sm2.py` | SM-2 调度器——SM2State 数据类 + SM2Scheduler 无状态算法 |
| `backend/app/services/exercise_service.py` | 出题服务——生成/查询/提交答案/统计 |
| `backend/app/api/v1/exercises.py` | 4 个 API 端点 |
| `backend/app/schemas/exercise.py` | Pydantic schema |
| `frontend/src/api/exercises.ts` | 前端 API 客户端 |
| `frontend/src/pages/QuizPage.tsx` | 学习页面——KB 选择器 → 逐题呈现 → 即时反馈 → 成绩单 |

**修改文件**:
| 文件 | 改动 |
|------|------|
| `backend/app/models/feedback.py` | 新增 `Exercise`、`ExerciseState` 两张表 |
| `backend/app/models/__init__.py` | 注册新模型 |
| `backend/app/api/v1/router.py` | 注册 exercises 路由 |
| `frontend/src/App.tsx` | 新增 `/quiz` 路由 |
| `frontend/src/components/Layout/Sidebar.tsx` | 新增 "Knowledge Review" 菜单项（FormOutlined 图标） |

**API 端点**:
| 方法 | 路径 | 功能 |
|------|------|------|
| POST | `/api/v1/exercises/generate` | 为 KB 的 chunk 批量生成练习题（LLM） |
| POST | `/api/v1/exercises/sessions/start` | 开始学习会话——返回 due 的题目 |
| POST | `/api/v1/exercises/sessions/answer` | 提交答案——返回反馈 + SM-2 更新状态 |
| GET | `/api/v1/exercises/stats/{kb_id}` | 学习统计——掌握/薄弱/待复习/正确率 |

**与 KB 选择器的复用**: 学习页面复用 `KBSelectorModal` 组件，用户先选知识库再开始学习会话，与聊天页的 KB 选择体验一致。

---

## 2026-07-13 — 查询标准化 + KB 选择（续）

### 变更 15: KB 选择功能 + 向量元数据增强

**时间**: 2026-07-13

**问题**: 
1. 创建新对话时无法选择知识库，导致要么走纯 LLM（无检索），要么绑定唯一 KB（无法切换）
2. 向量 chunk 元数据缺少 `doc_title`、`kb_id`、`doc_id`，检索结果来源一律显示 "Unknown"

**设计**: 前端新增 KB 选择器弹窗，后端增强 chunk 元数据标签体系。

**新增文件**:
| 文件 | 说明 |
|------|------|
| `frontend/src/components/Chat/KBSelectorModal.tsx` | KB 选择弹窗组件——列出所有 KB + "纯模型对话"选项，卡片式单选 |

**修改文件**:
| 文件 | 改动 |
|------|------|
| `backend/app/core/documents/pipeline.py` | `process_file`/`process_url` 新增 `doc_id`/`doc_title` 参数；chunk metadata 新增 `doc_title`、`kb_id`、`doc_id` 三个标签 |
| `backend/app/services/document_service.py` | 调用 pipeline 时传入 `doc_id=str(doc.id)` 和 `doc_title=doc.title` |
| `frontend/src/stores/chatStore.ts` | `createConversation(kbId?: string)` 接受可选 kbId |
| `frontend/src/pages/ChatPage.tsx` | "New Chat" 按钮 → 弹出 KB 选择器；侧边栏会话列表显示 KB 标签；聊天头部显示当前 KB 名称 |

**E2E 测试结果**:
```
[TEST 1] RAG with KB:    5 chunks → PASS
[TEST 2] Greeting in KB: 0 chunks → PASS  (意图分流仍然生效)
[TEST 3] Conv kb_id stored: ✓  → PASS
```

**使用方式**:
1. 点击 "+ New Chat" → 弹出 KB 选择器
2. 选择 "Pure Model Chat" → 纯 LLM 对话（无检索）
3. 选择具体 KB → 对话绑定该 KB，所有消息自动从该 KB 检索
4. 会话列表和聊天头部显示当前使用的 KB 名称

---

### 变更 14: 查询标准化管道（意图分类 + 五阶段查询改写）

**时间**: 2026-07-13

**问题**: 
1. 所有用户消息无差别走 RAG 管道——"hello" 也会检索 KB 并强制注入元组教程到回答中，回答不自然
2. 口语化查询（"这玩意咋整"）直接向量化，与文档书面语语义不匹配，召回率低
3. 代词指代（"它怎么用"）无法消解，召回到无关内容

**设计**: 在 RAG 管道 `_retrieve()` 之前插入两层处理：

**第一层：意图分类** (`intent_classifier.py`)
```
用户消息 → 快速正则匹配 → 确定? → 返回意图
                ↓ 不确定
          轻量 LLM 分类 → greeting / meta / knowledge / clarification
```

**第二层：五阶段查询标准化** (`query_standardizer.py`)
```
greeting/meta → 仅文本清洗（轻量模式）
knowledge/clarification → ①上下文补全 → ②清洗 → ③LLM改写 → ④术语扩展 → ⑤多路检索
```

**新增文件**:
| 文件 | 说明 |
|------|------|
| `backend/app/core/rag/terminology.py` | 32 个 Python 概念的中英术语表 + 同义词扩展 + 问候/Meta 正则模式 |
| `backend/app/core/rag/intent_classifier.py` | 两层意图分类器：快速正则（零LLM开销）+ LLM 兜底 |
| `backend/app/core/rag/query_standardizer.py` | 五阶段标准化管道：上下文补全→清洗→改写→扩展→多路查询 |

**修改文件**:
| 文件 | 改动 |
|------|------|
| `backend/app/core/rag/pipeline.py` | `generate_answer/generate_stream` 集成标准化管道；`_retrieve` 支持多路查询合并去重；新增 `intent` 参数 |
| `backend/app/services/chat_service.py` | `send_message_and_get_answer/stream_answer` 先意图分类再分流：greeting/meta → 纯LLM（带独立 system prompt），knowledge/clarification → RAG |

**意图分流规则**:
| 意图 | 示例 | 路径 | System Prompt | Footer |
|------|------|------|---------------|--------|
| greeting | "hello", "say hi", "谢谢" | 纯LLM | 友好简短，不推销KB | 无（自然对话） |
| meta | "你能做什么", "怎么用" | 纯LLM | 介绍系统能力 | 🤖 生成说明 |
| knowledge | "元组和列表区别" | 完整RAG | 基于KB回答 | 📚 参考来源 |
| clarification | "没懂", "举个例子" | RAG | 基于上文 | 按实际KB使用 |

**五阶段管道详情**:
| 阶段 | 功能 | 实现 | 开销 |
|------|------|------|------|
| ① 上下文补全 | 代词消解（"它"→"元组"） | 历史对话实体提取 + 规则替换 | 0-1ms |
| ② 文本清洗 | 去语气词/标点规范/全角半角 | 纯规则 | <1ms |
| ③ 查询改写 | 口语→书面语 + 中英术语补齐 | LLM（核心） | ~1-2s |
| ④ 查询扩展 | 术语表查同义词 + LLM 补关键词 | 术语表 + LLM | 0-500ms |
| ⑤ 多路查询 | 2-3 条不同角度子查询并行检索合并 | 并行 embed + search | 100-300ms |

**效果对比**:
| 输入 | 之前 | 之后 |
|------|------|------|
| "hello" | 5 chunks + 元组教程推销 | 0 chunks, "Hi there!" |
| "say hi" | 5 chunks + Python 课程推销 | 0 chunks, "Hi there! 😊" |
| "元组这玩意咋用" | 原文直传，召回可能差 | 改写为 "元组 tuple 如何使用" + 扩展术语 |

**架构位置**:
```
chat_service.py                 pipeline.py
  ↓ classify_intent()             ↓ QueryStandardizer.process()
  ↓ is_rag_needed()               ↓ _retrieve(standardized_query)
  ↓ generate_answer(intent=)     → LLM generate
```

---

## 2026-07-10 — 数据清洗管道

### 变更 9: 新增文档数据清洗模块
**时间**: 2026-07-10

**设计**: 在 DocumentPipeline 的 parse → chunk 之间插入 cleaner 层，采用**责任链模式**串联多个清洗器，每步可独立开关。

**新增文件**:
| 文件 | 说明 |
|------|------|
| `backend/app/core/documents/cleaners/base.py` | `BaseCleaner` 抽象基类 |
| `backend/app/core/documents/cleaners/rules.py` | 6 个清洗器实现 |
| `backend/app/core/documents/cleaners/pipeline.py` | `CleaningPipeline` 责任链编排 + `CleanerStats` 统计 |

**清洗器列表**:
| 清洗器 | 功能 |
|--------|------|
| `WhitespaceNormalizer` | 统一换行符(\r\n→\n)，合并连续空行(3+→2)，trim |
| `UnicodeSanitizer` | 全角→半角，移除非打印字符，NFC 归一化 |
| `HTMLResidueCleaner` | HTML 残留标签去除（仅对 text/html 源启用） |
| `NoiseLineFilter` | 去除空行、装饰线、版权声明、广告、导航文本等 |
| `DuplicateParagraphDeduplicator` | 去除连续重复段落 |
| `TrailingWhitespaceRemover` | 去除行尾空白 |

**修改文件**:
| 文件 | 改动 |
|------|------|
| `backend/app/config.py` | 新增 `cleaning_*` 6 项配置，独立开关每个清洗器 |
| `backend/.env` | 新增 `CLEANING_*` 配置项 |
| `backend/app/core/documents/pipeline.py` | `process_file/process_url` 在 parse 后、chunk 前执行清洗 |
| `backend/app/services/document_service.py` | 将清洗统计写入 `doc.metadata_json` |
| `frontend/src/pages/KBDetail.tsx` | 文档表格新增 Cleaning 列 + 展开行显示详细清洗对比 |
| `frontend/src/api/kbs.ts` | `DocumentResponse` 增加 `metadata_json`、`word_count` |

**论文价值**: 配置化开关使研究者可以对比"有清洗 vs 无清洗"对分块质量和检索命中率的影响，每个清洗器的效果可单独评估。

---

### 变更 10: HTML→Markdown 结构化转换 + 噪声深度清洗 + 预处理脚本

**时间**: 2026-07-10

**问题**: 原有 HTML 解析（BeautifulSoup `get_text()`）丢失全部结构信息（标题层级、代码块、表格等），且上传 .html 文件时未注册 HTMLParser（fallback 到 MarkdownParser 直接读 raw 内容）。从网页下载的教程文档含导航、页脚等噪声。

**设计**:
1. 新增 `HTMLToMarkdownConverter` — 将 HTML 结构完整转为 Markdown（标题/列表/代码块/表格/链接）
2. 新增 `HTMLNoiseCleaner` — CSS 选择器定位并移除导航/侧边栏/页脚/广告/评论区
3. 批处理脚本 `preprocess_docs.py` — 处理批量下载的 HTML，输出 YAML+Markdown 文件
4. 代码语言自动检测 — 识别 Sphinx 风格 `highlight-python3` class

**新增文件**:
| 文件 | 说明 |
|------|------|
| `app/core/documents/converters/__init__.py` | 转换器包初始化 |
| `app/core/documents/converters/html_to_md.py` | HTML→Markdown 转换器 + 噪声清洗器（共享核心） |
| `scripts/preprocess_docs.py` | 批处理脚本：HTML→MD + YAML front matter + 主题映射 |
| `docs/data-cleaning.md` | 数据清洗管道设计文档 |

**修改文件**:
| 文件 | 改动 |
|------|------|
| `app/core/documents/parsers/html_parser.py` | 重写：使用 HTMLToMarkdownConverter + HTMLNoiseCleaner，输出结构化 Markdown |
| `app/core/documents/pipeline.py` | parsers 字典注册 `"text/html": HTMLParser()`（此前缺失，导致 .html 文件 fallback 到 MarkdownParser） |
| `scripts/preprocess_docs.py` | 标注共享核心位置注释 |

**下载的教程数据**:
```bash
D:\coderag\知识库资料/          # 原始 HTML（Python 3.14 中文教程 17 页）
D:\coderag\知识库资料_clean/    # 处理后 Markdown + YAML（349KB）
```

**安全保证**: BeautifulSoup `decompose()` 彻底移除 `<script>`/`<style>` 及其内容，不执行不请求。---

### 变更 11: RAG 答案来源标注规范

**时间**: 2026-07-10

**问题**: 聊天回答没有标准化来源标注，用户无法区分回答来自知识库检索还是模型推理。

**设计**: 在 RAG 管道和纯 LLM 路径末尾追加标准化来源声明 footer，三种类型：

| 场景 | 图标 | 格式 |
|------|------|------|
| 基于知识库 | 📚 参考来源 | 文档名 > 章节 + 引用原文前 80 字 |
| 纯模型生成 | 🤖 生成说明 | 诚实告知未引用知识库 |
| 混合生成 | 🔀 内容说明 | 区分知识库支撑 vs 模型补充 |

**修改文件**:
| 文件 | 改动 |
|------|------|
| `app/core/rag/pipeline.py` | `_build_prompt` 增加标注格式系统指令；`_format_answer` 重写为三种 footer 的 fallback 逻辑 |
| `app/services/chat_service.py` | 纯 LLM 路径（kb_id=None）在答案末尾追加 `🤖` footer |

---

### 变更 12: 全站 i18n 汉化 + 聊天页面 UI 改进

**时间**: 2026-07-10

**问题**: 只有登录/注册页使用了 i18n 翻译，其余 14 个业务页面全部硬编码英文。聊天页侧边栏会话列表溢出无滚动条。

**修改文件**:
| 文件 | 改动 |
|------|------|
| `frontend/src/i18n/locales/zh.json` | 从 18 个键扩展到 ~150 个，覆盖所有业务页面 |
| `frontend/src/i18n/locales/en.json` | 同步扩展英文翻译 |
| `frontend/src/pages/Dashboard.tsx` | 接入 `useTranslation`（17 处硬编码 → `t()`） |
| `frontend/src/pages/KBList.tsx` | 接入 `useTranslation`（20+ 处） |
| `frontend/src/pages/KBDetail.tsx` | 接入 `useTranslation`（40+ 处） |
| `frontend/src/pages/ChatPage.tsx` | 接入 `useTranslation`（15 处）+ 侧边栏改用 `<div>` 弹性布局，`overflowY: auto` 实现独立滚动 |
| `frontend/src/pages/CodeReview.tsx` | 接入 `useTranslation` |
| `frontend/src/pages/ConceptComparison.tsx` | 接入 `useTranslation` |
| `frontend/src/pages/LearningPath.tsx` | 接入 `useTranslation` |
| `frontend/src/pages/EvalDashboard.tsx` | 接入 `useTranslation` |
| `frontend/src/pages/EvalExperiments.tsx` | 接入 `useTranslation` |
| `frontend/src/pages/MonitoringPage.tsx` | 接入 `useTranslation` |
| `frontend/src/pages/ConfigPage.tsx` | 接入 `useTranslation` |
| `frontend/src/pages/AdminUsers.tsx` | 接入 `useTranslation` |
| `frontend/src/pages/DocumentDetail.tsx` | 接入 `useTranslation` |
| `frontend/src/pages/NotFound.tsx` | 接入 `useTranslation` |

---

### 变更 13: 修复文档处理管道 Bug + 导入 Python 中文教程知识库

**时间**: 2026-07-10

**问题**: 导入清洗后的 Markdown 文档时触发两个 Bug：
1. `pipeline.py` 缺少 `from app.config import settings` 导入 → `NameError`
2. `chunkers/hybrid.py` 的 `_split_markdown` 内部 `_split()` 用 `async def` 定义却传给 `asyncio.to_thread()`（期望普通函数）→ `'coroutine' object is not iterable`

**修复**:
| 文件 | 修复 |
|------|------|
| `app/core/documents/pipeline.py` | 补回 `from app.config import settings` |
| `app/core/documents/chunkers/hybrid.py` | `async def _split() → def _split()` |

**知识库导入结果**:
```bash
文档数: 17 个 Markdown（Python 3.14 中文教程全部页面）
分块数: 991
总 Token: 66,802
平均分块大小: 67.4 tokens
状态: 全部 indexed ✔
```

**当前运行端口**: `localhost:8083`（原 8080/8081/8082 端口有 Windows 残留进程未被释放）

## 2026-07-09 — 项目初始化与迭代

### 变更 8: 修复聊天消息跨页面丢失
**时间**: 2026-07-09 18:10

**问题**: 聊天消息在切换到其他页面后消失。

**根因**:
1. `ChatPage` 使用 `useState` 管理消息，组件卸载时状态丢失
2. `chatStore` 只有一个共享 `messages` 数组，切换对话时被覆盖
3. `api/chat.ts` 和 `api/kbs.ts` 类型定义与后端返回值不匹配（`data` vs `items`、`kbId` vs `kb_id`）
4. SSE 流路径错误（`/messages/stream` → `/stream`），且未解析后端 JSON 事件格式

**修改文件**:
| 文件 | 改动 |
|------|------|
| `frontend/src/api/chat.ts` | 类型匹配后端字段 (snake_case)；SSE 路径修复为 `/stream`；`ChatStream` 解析 JSON `{type, content}` 事件 |
| `frontend/src/api/kbs.ts` | `PaginatedResponse.items`、`KBResponse` 字段名全部匹配后端 |
| `frontend/src/stores/chatStore.ts` | `messagesByConv: Record<string, MessageResponse[]>` 按对话缓存消息，切换不丢失 |
| `frontend/src/pages/ChatPage.tsx` | 移除局部 `useState`，全部改用 `useChatStore` |

### 变更 7: 支持 `LLM_API_KEY` 系统环境变量
**时间**: 2026-07-09 17:50

**修改文件**:
| 文件 | 改动 |
|------|------|
| `backend/app/config.py` | 新增 `llm_api_key` 字段和 `effective_api_key` 属性。优先级: `LLM_API_KEY` > `OPENAI_API_KEY` |
| `backend/app/llm/factory.py` | `get_llm_provider()` 使用 `settings.effective_api_key` 替代 `settings.openai_api_key` |
| `backend/.env` | 新增 `LLM_API_KEY=` 配置项文档 |
| `README.md` | 新增项目完整文档 |
| `docs/architecture.md` | 新增架构文档 |
| `docs/changelog.md` | 新增变更日志 |

**使用方式**:
```bash
# Windows CMD (管理员)
setx LLM_API_KEY "your-openai-api-key"

# 重启终端后生效，或在 .env 中直接设置
```

---

### 变更 6: 页面功能化 + 中英文双语
**时间**: 2026-07-09 17:35

**修改文件**:
| 文件 | 改动 |
|------|------|
| `frontend/src/i18n/index.ts` | 新增 i18next 配置 (默认中文，检测 localStorage/浏览器) |
| `frontend/src/i18n/locales/en.json` | 新增英文翻译 (16 个模块) |
| `frontend/src/i18n/locales/zh.json` | 新增中文翻译 |
| `frontend/src/components/Layout/Header.tsx` | 新增语言切换按钮 (中/EN) |
| `frontend/src/components/Layout/Sidebar.tsx` | 菜单标签 i18n 化 |
| `frontend/src/pages/Login.tsx` | 登录页 i18n |
| `frontend/src/pages/Register.tsx` | 注册页 i18n |
| `frontend/src/pages/Dashboard.tsx` | 从 API 加载真实 KB 数量和对话数 |
| `frontend/src/pages/KBList.tsx` | KB 列表卡片 + 创建 Modal + API 调用 |
| `frontend/src/pages/KBDetail.tsx` | KB 详情 + 文档上传/列表 + 设置编辑 |
| `frontend/src/pages/ChatPage.tsx` | 对话列表 + 消息发送 + SSE 流式 + Markdown 渲染 |
| `frontend/src/pages/CodeReview.tsx` | 代码输入 → API 调用 → 结果展示 |
| `frontend/src/pages/ConceptComparison.tsx` | 两栏概念对比 |
| `frontend/src/pages/LearningPath.tsx` | 学习路径生成 |
| `frontend/src/api/kbs.ts` | 新增 `listDocuments()`, `uploadDocument()`, `deleteDocument()` |
| `frontend/src/api/chat.ts` | 修正字段名匹配后端 (camelCase → snake_case) |
| `frontend/src/stores/authStore.ts` | 修正 token 字段名 |
| `frontend/src/stores/chatStore.ts` | 修正 `kbId` → `kb_id` |
| `package.json` | 新增 `i18next`, `react-i18next`, `i18next-browser-languagedetector` |

---

### 变更 5: 修复 LLM/Embedding 导入 500 错误
**时间**: 2026-07-09 17:40

**问题**: `POST /review/code` 和 `POST /concepts/compare` 返回 500，因为 `openai` 包未安装且 API key 为占位值。

**修改文件**:
| 文件 | 改动 |
|------|------|
| `backend/app/llm/openai_provider.py` | `from openai import AsyncOpenAI` 从模块级改为 `__init__` 内懒加载 |
| `backend/app/llm/factory.py` | 新增 `NoopProvider` 降级类；检测无效 API key 时返回降级 |
| `backend/app/embedding/factory.py` | 新增 `NoopEmbedding` 降级类 |
| `backend/app/api/v1/review.py` | 所有端点添加 try/except 错误处理 |
| `backend/app/api/v1/concepts.py` | 同上 |

---

### 变更 4: 切换到 MySQL 数据库
**时间**: 2026-07-09 16:49

**问题**: 原配置使用 SQLite，但本机有 MySQL 8.0 (端口 3309, 密码 root)。

**修改文件**:
| 文件 | 改动 |
|------|------|
| `backend/.env` | `DATABASE_URL` → `mysql+asyncmy://root:root@localhost:3309/coderag` |
| `backend/app/db/session.py` | 非 SQLite URL 使用连接池 (pool_size=20, pool_pre_ping=True) |
| `backend/app/models/base.py` | 新增 `CustomUUID` TypeDecorator (PG: UUID, SQLite/MySQL: CHAR(36)) |
| `backend/app/models/*.py` | `JSONB` → `JSON` (MySQL 兼容)；`DateTime(timezone=True)` → `DateTime`；`server_default` → `default` (Python 端) |
| `backend/app/core/auth/password.py` | `passlib` → `bcrypt` (兼容 bcrypt 5.x) |
| `backend/pyproject.toml` | 新增 `asyncmy` 依赖 |
| `frontend/vite.config.ts` | proxy target → `localhost:8081` |

---

### 变更 3: 项目脚手架 + 全部模块实现
**时间**: 2026-07-09 16:00-16:45

**新建文件**: 150+ 文件
- 后端: FastAPI 应用、15 张数据库表、14 个 API 路由组、RAG 管道、文档处理管道、LLM/Embedding/VectorStore 抽象层、Celery 任务
- 前端: React 18 + Vite + Ant Design 5、Zustand 状态管理、17 个页面、4 个布局组件、i18n 预留

---

### 变更 2: 前端认证 API 修复
**时间**: 2026-07-09 17:15

**问题**: 登录时 `TypeError`，前端用 camelCase 字段名但后端返回 snake_case。

**修改文件**:
| 文件 | 改动 |
|------|------|
| `frontend/src/api/auth.ts` | `TokenResponse.accessToken` → `access_token`；`UserResponse` 匹配后端字段 |
| `frontend/src/stores/authStore.ts` | `tokens.accessToken` → `tokens.access_token` |

---

### 变更 1: 密码哈希兼容修复
**时间**: 2026-07-09 16:28

**问题**: `passlib` + `bcrypt 5.x` 不兼容导致注册失败。

**修改文件**:
| 文件 | 改动 |
|------|------|
| `backend/app/core/auth/password.py` | `passlib.context.CryptContext` → `bcrypt.hashpw/checkpw` 直接调用 |
