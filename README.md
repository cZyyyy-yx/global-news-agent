# Global News Agent

这是一个面向 Cloudflare 长期部署路线重构的全球新闻日报项目。

当前仓库同时保留两条路线：

- `src/worker.js`：长期方案，面向 Cloudflare Workers
- 旧版本地 Python 脚本：迁移过渡期保留，不再是首选部署方式

## 当前推荐路线

如果你的目标是：

- 连接 GitHub 自动部署
- 长期稳定公开访问
- 不再依赖本地 `cloudflared`
- 以后逐步扩展历史、搜索、趋势

那就直接使用 Worker 版本。

## Worker 版本现在能做什么

- 在边缘抓取全球 RSS 新闻源
- 去重、分类、排序，选出重点事件
- 在没有 OpenAI API Key 的情况下生成可用的中文日报
- 如果以后配置 `OPENAI_API_KEY`，自动升级中文质量
- 提供网页仪表盘和 JSON API
- 自动缓存日报结果 15 分钟
- 如果绑定 `REPORTS_KV`，自动开启历史归档、历史搜索、趋势统计和归档详情查看

## 仓库关键文件

- `wrangler.toml`：Cloudflare Worker 配置
- `src/worker.js`：Worker 主入口
- `.dev.vars.example`：本地开发时的 secret 示例
- `.gitignore`：已排除本地缓存、报告目录和不该入库的文件

旧版本地脚本仍然保留，但现在只作为迁移参考：

- `agent.py`
- `server.py`
- `share_public.py`
- 各类 `.bat` 启动脚本

## 无 API 版本优先部署

现在这版项目可以在没有 OpenAI API Key 的情况下直接部署。

部署步骤：

1. 安装 Wrangler
2. 登录 Cloudflare

```bash
wrangler login
```

3. 本地预览

```bash
wrangler dev
```

4. 正式部署

```bash
wrangler deploy
```

部署成功后，你会拿到一个固定的 Worker 地址，例如：

```text
https://global-news-agent.<your-subdomain>.workers.dev
```

无 API 版本已经包含：

- RSS 聚合
- 重点事件排序
- 中文标题/摘要 fallback
- 网页日报页面
- JSON 报告接口

## 可选的 KV 历史模式

如果你后面想开启历史归档、历史搜索和趋势功能，需要绑定一个 Cloudflare KV 命名空间，绑定名固定为：

```text
REPORTS_KV
```

示例配置：

```toml
[[kv_namespaces]]
binding = "REPORTS_KV"
id = "your_production_kv_namespace_id"
preview_id = "your_preview_kv_namespace_id"
```

配置流程：

1. 在 Cloudflare 创建 KV namespace
2. 把上面的 `[[kv_namespaces]]` 配置加到 `wrangler.toml`
3. 重新部署 Worker

绑定完成后，这些能力会自动生效：

- `/api/history`
- `/api/search?q=关键词`
- `/api/trends`
- `/api/archive?key=...`

不需要再改主逻辑。

## 可选的 OpenAI 增强

如果你以后拿到 OpenAI API Key，可以把它作为增强项加进去：

```bash
wrangler secret put OPENAI_API_KEY
wrangler secret put OPENAI_MODEL
```

`OPENAI_MODEL` 是可选项，默认值是：

```text
gpt-5-mini
```

加上以后，Worker 会优先调用 OpenAI 提升中文标题、摘要和整体日报质量，但不会破坏无 API 版本的可用性。

## GitHub 自动部署

推荐做法：

1. 把仓库推到 GitHub
2. 在 Cloudflare Workers 里连接 GitHub 仓库
3. 如果你有 OpenAI Key，再把 `OPENAI_API_KEY` 配成生产 secret
4. 使用 `wrangler.toml` 作为默认部署配置

这样以后你每次推送到 `main`，都可以自动重新部署。

## 当前 API

- `GET /`：网页仪表盘
- `GET /api/report`：最新日报 JSON
- `GET /api/report?refresh=1`：绕过缓存立即重新生成
- `GET /api/history`：最近归档元数据，需配置 `REPORTS_KV`
- `GET /api/search?q=keyword`：历史搜索，需配置 `REPORTS_KV`
- `GET /api/trends`：趋势统计，需配置 `REPORTS_KV`
- `GET /api/archive?key=...`：单次历史快照详情，需配置 `REPORTS_KV`
- `GET /api/health`：健康检查

## 当前状态说明

- Worker 版本已经是长期方案
- 无 API 版本已经可以作为正式第一版上线
- OpenAI 现在是增强项，不是硬依赖
- 历史、搜索、趋势、归档详情已经按 KV 路线接好
- 如果后面要做更完整的数据能力，下一步建议扩展成 KV + D1 或 R2
