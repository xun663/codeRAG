# CodeRAG 2C4G 线上部署手册

> 目标：阿里云 2C4G（Ubuntu 24.04）全功能部署——本地 **bge-reranker-base 重排**、云嵌入（千问 text-embedding-v3）、云 LLM（DeepSeek）、Celery 异步出题全保留。

## 架构总览

```
[Nginx :80]  静态前端 (build 产物) + 反代 /api
   └─ 127.0.0.1:8085  uvicorn（单 worker，ChromaDB 进程内，重排模型常驻）
   ├─ 127.0.0.1       celery --pool=solo --concurrency=1（异步出题）
   ├─ 127.0.0.1:6379  redis（Celery broker）
   └─ 127.0.0.1:3306  MySQL 8（调优 ~512M）
外部 API：dashscope（嵌入） / api.deepseek.com（LLM）
```

内存预算（2C4G / 4GB）：
| 组件 | 占用 |
|------|------|
| 后端进程（Python + ChromaDB + bge-reranker-base 1.1G） | ~1.6GB |
| MySQL 8 调优后 | ~0.6GB |
| Celery worker | ~0.4GB |
| Redis / Nginx / OS | ~0.3GB |
| **合计** | **~2.9GB / 4GB ✅** |

## 一、前置准备

1. **购买实例**：阿里云轻量/ECS 2C4G，系统镜像 **Ubuntu 24.04**（自带 Python 3.12）。
2. **安全组**放行 **80** 端口（+22 SSH）。记下公网 IP。
3. 准备两个 API key：
   - **DeepSeek** LLM key（与本地 `backend/.env` 的 `LLM_API_KEY` 相同）
   - **DashScope** key（千问 embedding，`https://dashscope.console.aliyun.com` 创建）
4. 确认本仓库已 push 到 GitHub（`git@github.com:xun663/codeRAG.git`）。**私有仓库**需在服务器配 SSH key 或改用带 token 的 HTTPS 地址（把 `setup_2c4g.sh` 里 `GIT_REPO` 换成 `https://<token>@github.com/xun663/codeRAG.git`）。

## 二、一键部署

```bash
# SSH 登录服务器后
sudo bash -c 'cd /tmp && curl -fsSL -o setup.sh https://raw.githubusercontent.com/xun663/codeRAG/main/deploy/setup_2c4g.sh && bash setup.sh <DeepSeekKey> <DashScopeKey>'
```

> 若仓库未公开、不想用 curl，把本仓库 `deploy/` 目录 scp 到服务器后：
> ```bash
> scp -r deploy ubuntu@<IP>:/tmp/deploy
> ssh ubuntu@<IP> "sudo bash /tmp/deploy/setup_2c4g.sh <DeepSeekKey> <DashScopeKey>"
> ```

脚本会自动完成：系统依赖 + 2G swap → clone 代码 → venv（torch CPU 版）→ MySQL 调优建库 → 生成生产 `.env` → alembic 建表 → **seed 千问嵌入配置** → 预下载 bge-reranker-base → 前端构建 → Nginx → systemd 常驻 → 自检。

## 三、部署后验证

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8085/docs   # 应 200
systemctl is-active coderag-api coderag-celery mysql redis-server nginx
# 浏览器访问 http://<公网IP>  →  用 admin / admin123 登录
```

> **SSH 安全**：脚本已自动安装并启用 fail2ban（10 分钟内连错 5 次封 1 小时）。
> 若用密码登录，务必用强随机密码（如 `openssl rand -base64 16`），别用习惯密码；以后想更稳可再补密钥。

登录后到「系统配置」页确认：
- **LLM 配置单**：可保持空（`.env` 已兜底 DeepSeek），或新建一个配置单并激活走 UI 管理。
- **嵌入模型**：应为 `openai / text-embedding-v3 / 1024 维`（脚本已 seed，无需手填）。

然后建一个知识库、传文档，验证检索/问答/出题全链路。

## 四、数据备份（重要）

生产数据三处，务必定期备份：

| 数据 | 路径 |
|------|------|
| MySQL | `mysqldump -u root coderag > backup.sql` |
| 向量库 | `/opt/coderag/backend/data/chroma_db/`（文件复制） |
| 上传文档 | `/opt/coderag/backend/data/uploads/` |

```bash
# 一条 cron：每天凌晨 3 点打包到 /backup
0 3 * * *  cd /opt/coderag/backend && mysqldump -u coderag -p'密码' coderag > /backup/db_$(date +\%F).sql && tar czf /backup/chroma_$(date +\%F).tgz data/chroma_db data/uploads
```

## 五、日常运维

```bash
journalctl -u coderag-api -f        # API 日志
journalctl -u coderag-celery -f     # Celery 日志
systemctl restart coderag-api       # 改 .env / 代码后重启（代码变更需 git pull + 重启）
```

**升级代码**：
```bash
cd /opt/coderag && sudo -u coderag git pull --ff-only
sudo systemctl restart coderag-api coderag-celery
# 如有数据库迁移：cd backend && /home/coderag/venv/bin/alembic upgrade head
```

## 六、常见问题

| 症状 | 排查 |
|------|------|
| 8085 起不来 | `journalctl -u coderag-api -n 50`；确认 `asyncmy` 已装（`/home/coderag/venv/bin/pip show asyncmy`）；确认 MySQL 可连（`mysql -u coderag -p -e 'select 1' coderag`） |
| 检索出题卡住/任务永不完成 | `redis-cli ping`；看 celery 日志是否消费 `default` 队列（`celery inspect active`） |
| 问答重排慢 | bge-reranker-base 首次调用会加载模型（~10-30s），之后常驻；2C4G 上 CPU 推理约 1-2s/查询，可接受 |
| 上传大文件 413 | 已配 `client_max_body_size 120m`；再大调 Nginx 与 `.env` 的 `MAX_UPLOAD_SIZE_MB` |
| 想上 HTTPS | 域名解析到 IP 后 `apt install certbot python3-certbot-nginx && certbot --nginx` |

## 七、预留升级路径

- **数据/并发增长**：升 4C8G 即可，无需改架构；uvicorn 可加 worker（注意每 worker 会复制 ChromaDB + 重排模型内存）。
- **嵌入改回本地**：需要 GPU/内存 ≥6G 的机器，改 `DEFAULT_EMBEDDING_PROVIDER=local` 并全库重嵌入；当前云嵌入成本极低，不建议。
- **前端 CDN**：静态资源放 OSS/CDN，Nginx 只留 /api 反代。
