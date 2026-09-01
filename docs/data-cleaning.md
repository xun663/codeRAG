# 数据清洗管道设计文档

## 概述

数据清洗管道是 CodeRAG 文档处理流程的前置环节，负责将原始 HTML 文档（如 Python 官方教程、技术博客等）**安全、无损**地转换为适合 RAG 知识库存储和检索的干净 Markdown。

### 核心目标

| 目标 | 说明 |
|------|------|
| **安全** | 彻底移除 `<script>`、可执行内容，确保只分析不执行 |
| **结构保留** | 标题层级、列表、代码块、表格、链接等完整转为 Markdown |
| **噪声清除** | 删除导航、页脚、侧边栏、广告、评论区等无关内容 |
| **元数据标注** | YAML front matter 标记来源、版本、主题、语言、类型 |
| **代码增强** | 为纯代码文件生成功能摘要，作为检索锚点 |

---

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│                    数据清洗管道                                │
│                                                             │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐ │
│  │ HTML     │──▶│ 噪声清洗  │──▶│ Markdown │──▶│ YAML     │ │
│  │ 输入     │   │          │   │ 转换     │   │ 元数据   │ │
│  └──────────┘   └──────────┘   └──────────┘   └──────────┘ │
│                      │               │              │        │
│                 BeautifulSoup   HTML→MD       front matter   │
│                 CSS Selectors   转换器                        │
└─────────────────────────────────────────────────────────────┘
```

### 两条使用路径

1. **批处理脚本**（`scripts/preprocess_docs.py`）
   - 用于批量处理下载的文档目录
   - 输出 YAML + Markdown 文件，可后续通过前端上传入库

2. **实时解析器**（`app/core/documents/parsers/html_parser.py`）
   - 通过 `POST /kbs/{kb_id}/documents/upload` 上传 `.html` 文件时触发
   - 或通过 `from-url` 导入时触发
   - 输出纯 Markdown 给下游分块 → 嵌入 → 索引

两条路径共享 `app/core/documents/converters/html_to_md.py` 中的转换核心。

---

## 详细流程

### 第一阶段：解析与清洗

```
输入: 原始 HTML
输出: 干净的 BeautifulSoup 对象
```

**步骤：**

1. **BeautifulSoup 解析** — 使用 Python 内置的 `html.parser`
2. **移除脚本和样式** — `soup(["script", "style"]).decompose()`
   - 彻底移除 `<script>` 及其内部所有内容
   - 彻底移除 `<style>` 及其内部所有 CSS
3. **CSS 选择器噪声移除** — 匹配以下元素并 `decompose()`：

| 类别 | 选择器 |
|------|--------|
| 导航 | `nav`, `.navbar`, `.navigation`, `.breadcrumb` |
| 侧边栏 | `.sidebar`, `.toc`, `.toctree`, `.contents` |
| 页脚 | `footer`, `.footer`, `.copyright` |
| 广告 | `.advertisement`, `.ad`, `.sponsor` |
| 评论区 | `.comments`, `.disqus`, `#disqus_thread` |
| 搜索 | `.searchbox`, `#searchbox` |
| UI 元素 | `.headerlink`, `.back-to-top`, `.pager` |

4. **图标元素清理** — 移除仅有图标无文字内容的元素

### 第二阶段：HTML → Markdown 转换

```
输入: 干净的 BeautifulSoup
输出: 结构化 Markdown
```

**标签映射规则：**

| HTML 标签 | Markdown 输出 |
|-----------|---------------|
| `<h1>` ~ `<h6>` | `#` ~ `######` 标题 |
| `<p>` | 段落文本 + 空行 |
| `<ul>` / `<ol>` | `-` / `1.` 列表 |
| `<pre><code>` | ` ```语言` 代码块 |
| `<pre>`（裸） | 无 code 标签时直接提取文本，从父级 class 检测语言 |
| `<table>` | Markdown 表格（`| --- | --- |`） |
| `<a>` | `[文本](链接)` |
| `<strong>` / `<b>` | `**加粗**` |
| `<em>` / `<i>` | `*斜体*` |
| `<blockquote>` | `> 引用` |
| `<hr>` | `---` 分隔线 |
| `<code>`（内联） | `` `内联代码` `` |

**代码语言检测策略：**

使用 BeautifulSoup 的 CSS class 检测，按优先级：
1. 标签自身 class（`class="highlight-python3"` → `python`）
2. 父级标签 class（Sphinx 文档中，`<pre>` 的父 `<div>` 带有 `highlight-xxx`）
3. 回退：`class="highlight"` → 默认为 `python`（适用于 Python 官方文档）

### 第三阶段：YAML 元数据标注（仅批处理）

```
示例:
---
source: "Python Official Tutorial (zh-CN)"
version: "3.14"
topic: "Control Flow"
language: "Python"
type: "tutorial"
---
```

| 字段 | 说明 | 取值来源 |
|------|------|----------|
| `source` | 文档来源 | 固定值（可配置） |
| `version` | 文档版本 | 从 `<title>` 提取 |
| `topic` | 主题标签 | TOPIC_MAP 映射表 |
| `language` | 编程语言 | 固定值或自动检测 |
| `type` | 文档类型 | `tutorial` / `reference` / `howto` / `source-code` |

### 第四阶段：代码预处理（预留）

对于**纯代码文件**（无自然语言解释），预期生成：
- 每个函数/类/方法的功能摘要（50-150 字）
- 摘要作为 Markdown 引用块（`>`）置于代码块之前
- 摘要涵盖：用途、输入/输出、关键逻辑

> 当前阶段文档为 Python 教程（含自然语言），此阶段主要面向后续导入的纯代码仓库。

---

## 文件结构与职责

```
backend/
├── app/
│   └── core/
│       └── documents/
│           ├── converters/
│           │   ├── __init__.py
│           │   └── html_to_md.py      ← HTML→Markdown 转换器 + 噪声清洗（共享核心）
│           ├── parsers/
│           │   └── html_parser.py     ← HEML解析器（调用共享核心）
│           │   └── ...                ← 其他解析器
│           ├── cleaners/
│           │   └── pipeline.py        ← 原有清洗管道（文本级清洗）
│           │   └── rules.py           ← Unicode/空格/HTML残渣/噪声行/去重
│           └── pipeline.py            ← 文档处理管道编排器
└── scripts/
    └── preprocess_docs.py             ← 批处理脚本（独立，含自身转换实现）
```

### 关键设计决策

1. **共享 vs 独立转换器**：`html_to_md.py` 中的 `HTMLToMarkdownConverter` 和 `HTMLNoiseCleaner` 是共享核心，`html_parser.py`（实时路径）直接导入。批处理脚本 `preprocess_docs.py` 保留自身副本以保持独立可运行性。

2. **两阶段清洗**：
   - **HTML 级清洗**（`HTMLNoiseCleaner`）：在解析阶段用 CSS 选择器移除大块噪声元素
   - **文本级清洗**（`CleaningPipeline`）：在文本阶段用正则处理 Unicode、空白、重复段落等细粒度噪声
   - 两者互补，分别作用于不同抽象层次

3. **安全原则**：`<script>` 和 `<style>` 在 BeautifulSoup 解析阶段通过 `decompose()` 彻底移除，不会进入下游的任何处理环节。

---

## 配置项

参见 `backend/app/config.py` 中的清洗相关配置：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `cleaning_enabled` | `True` | 是否启用文本级清洗 |
| `cleaning_normalize_unicode` | `True` | Unicode 归一化 |
| `cleaning_remove_html_residue` | `True` | 移除 HTML 残留标签 |
| `cleaning_normalize_whitespace` | `True` | 空格规范化 |
| `cleaning_filter_noise` | `True` | 过滤噪音行 |
| `cleaning_deduplicate_paragraphs` | `True` | 段落去重 |

---

## 使用方式

### 批处理预处理

```bash
# 从 backend/ 目录运行
python scripts/preprocess_docs.py --input-dir 知识库资料/ --output-dir 知识库资料_clean/

# 处理单个文件
python scripts/preprocess_docs.py --input 知识库资料/index.html --output 知识库资料_clean/

# 仅查看主题映射
python scripts/preprocess_docs.py --input-dir 知识库资料/ --list-topics
```

### 实时导入（通过 API）

```bash
# 上传 .html 文件
curl -X POST http://localhost:8080/api/v1/kbs/{kb_id}/documents/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@document.html"

# 或从 URL 导入
curl -X POST http://localhost:8080/api/v1/kbs/{kb_id}/documents/from-url \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://docs.python.org/zh-cn/3/tutorial/index.html"}'
```

两种方式都会自动经过 `HTMLParser`（噪声清洗 → Markdown 转换）后再进入分块和索引流程。

---

## 质量保障

### 校验项

| 检查点 | 标准 | 检测方式 |
|--------|------|----------|
| 脚本无残余 HTML 标签 | 无 `<[^>]+>` 匹配 | 正则扫描 |
| 代码块有语言标注 | 主要代码块标注语言 | 抽样检查 |
| YAML 元数据完整 | 必填字段非空 | 解析验证 |
| 标题层级保留 | h1~h6 → #~###### | 对比原始 HTML |
| 无脚本内容残留 | 不含 `function(`/`var ` 等 | 关键字扫描 |

### 已知限制

- HTML → Markdown 转换对于极其复杂的嵌套布局（多重嵌套表格、浮动布局）可能丢失部分信息
- Sphinx 文档中的交叉引用（`:ref:`）保留为相对路径链接，本地浏览可能失效
- 纯代码预处理（功能摘要生成）当前为预留占位，尚未实现

### 常见问题

#### Q: 上传 .md 文件触发 `'coroutine' object is not iterable`

**原因**: `HybridChunker._split_markdown` 内部 `_split()` 用 `async def` 定义，但传给 `asyncio.to_thread()` — 后者期望普通函数，调用后拿到 coroutine 对象而非结果。

**修复**: 将 `async def _split()` 改为 `def _split()`（已在 `app/core/documents/chunkers/hybrid.py:41` 修复）。

#### Q: 文档处理返回 500 Internal Server Error

**原因**: `pipeline.py` 缺少 `from app.config import settings` 导入。

**修复**: 补回导入语句（已在 `app/core/documents/pipeline.py:8` 修复）。

#### Q: 清洗后文档内容过少

**YAML front matter 不会被清洗移除**，因为清洗器作用于文本阶段，而 front matter 作为 Markdown 头部保留。如果仍然过少，请检查 `HTMLNoiseCleaner.NOISE_SELECTORS` 是否匹配了正文元素。

---

## 变更记录

| 日期 | 变更内容 | 作者 |
|------|----------|------|
| 2026-07-10 | 初始版本：HTML→Markdown 转换器 + 噪声清洗 + YAML 元数据 + 开发文档 | - |
| 2026-07-10 | 修复 `HybridChunker` 协程 Bug + `pipeline.py` 缺失导入 | - |
