const RSS_FEEDS = [
  { name: "Reuters World", url: "https://feeds.reuters.com/Reuters/worldNews" },
  { name: "BBC World", url: "http://feeds.bbci.co.uk/news/world/rss.xml" },
  { name: "AP Top News", url: "https://apnews.com/hub/ap-top-news?output=rss" },
  { name: "NPR World", url: "https://feeds.npr.org/1004/rss.xml" },
  { name: "The Guardian World", url: "https://www.theguardian.com/world/rss" },
  { name: "Al Jazeera", url: "https://www.aljazeera.com/xml/rss/all.xml" },
  { name: "DW World", url: "https://rss.dw.com/rdf/rss-en-world" },
];

const CATEGORY_KEYWORDS = {
  "地缘政治": ["war", "military", "missile", "sanction", "summit", "president", "minister", "conflict", "border", "nato", "iran", "israel", "ukraine"],
  "经济金融": ["economy", "inflation", "rate", "market", "trade", "tariff", "jobs", "oil", "fed", "central bank", "gdp", "bond"],
  "科技产业": ["ai", "chip", "semiconductor", "tech", "cyber", "software", "internet", "data", "cloud", "robot"],
  "气候灾害": ["climate", "storm", "flood", "earthquake", "wildfire", "heat", "emissions", "weather"],
  "公共卫生": ["health", "virus", "outbreak", "vaccine", "hospital", "disease"],
};

const REGION_RULES = {
  "中东": ["iran", "israel", "gaza", "syria", "lebanon", "hormuz", "saudi", "uae"],
  "欧洲": ["eu", "europe", "ukraine", "russia", "france", "germany", "britain", "uk"],
  "北美": ["us", "u.s.", "america", "canada", "trump", "fed", "washington"],
  "亚太": ["china", "japan", "korea", "taiwan", "india", "asia", "pacific"],
  "拉美": ["brazil", "mexico", "argentina", "latin"],
  "非洲": ["africa", "sudan", "nigeria", "ethiopia"],
};

const TOP_EVENTS = 8;
const MAX_ITEMS_PER_FEED = 12;
const CACHE_TTL_SECONDS = 900;

const REPORT_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["generated_at", "source_mode", "executive_summary", "china_brief", "market_brief", "watchlist", "items"],
  properties: {
    generated_at: { type: "string" },
    source_mode: { type: "string" },
    executive_summary: { type: "string" },
    china_brief: { type: "string" },
    market_brief: { type: "string" },
    watchlist: { type: "array", items: { type: "string" }, maxItems: 5 },
    items: {
      type: "array",
      maxItems: 10,
      items: {
        type: "object",
        additionalProperties: false,
        required: [
          "title",
          "title_cn",
          "category",
          "region",
          "significance",
          "original_summary_en",
          "summary_cn",
          "impact_cn",
          "economic_impact_cn",
          "asset_impact_cn",
          "china_sector_impact_cn",
          "china_impact_cn",
          "market_impact_cn",
          "watchpoints_cn",
          "event_date",
          "source_name",
          "source_url",
        ],
        properties: {
          title: { type: "string" },
          title_cn: { type: "string" },
          category: { type: "string" },
          region: { type: "string" },
          significance: { type: "integer", minimum: 1, maximum: 5 },
          original_summary_en: { type: "string" },
          summary_cn: { type: "string" },
          impact_cn: { type: "string" },
          economic_impact_cn: { type: "string" },
          asset_impact_cn: { type: "string" },
          china_sector_impact_cn: { type: "string" },
          china_impact_cn: { type: "string" },
          market_impact_cn: { type: "string" },
          watchpoints_cn: { type: "string" },
          event_date: { type: "string" },
          source_name: { type: "string" },
          source_url: { type: "string" },
        },
      },
    },
  },
};

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (url.pathname === "/api/health") {
      return json({ ok: true, service: "global-news-agent-worker" });
    }

    if (url.pathname === "/api/report") {
      const refresh = url.searchParams.get("refresh") === "1";
      return handleReportRequest(request, env, ctx, refresh);
    }

    return new Response(buildDashboardHtml(), {
      headers: {
        "content-type": "text/html; charset=utf-8",
        "cache-control": "no-store",
      },
    });
  },
};

async function handleReportRequest(request, env, ctx, refresh) {
  const cache = caches.default;
  const cacheKey = new Request(new URL("/__report_cache", request.url).toString(), { method: "GET" });
  if (!refresh) {
    const cached = await cache.match(cacheKey);
    if (cached) return cached;
  }

  const report = await buildReport(env);
  const response = json(report, {
    "cache-control": `public, max-age=${CACHE_TTL_SECONDS}`,
  });
  ctx.waitUntil(cache.put(cacheKey, response.clone()));
  return response;
}

async function buildReport(env) {
  const { items, warnings } = await collectNews();
  if (!items.length) {
    return {
      generated_at: isoDate(),
      source_mode: "rss_failed",
      executive_summary: "当前 RSS 抓取未能生成有效日报。",
      china_brief: "请检查上游 RSS 可用性、网络策略和 Worker 出站访问。",
      market_brief: "当前没有足够事件生成市场影响概览。",
      watchlist: ["检查 RSS 源状态", "检查 Worker 日志", "确认 OpenAI secret 配置"],
      items: [],
      warnings,
    };
  }

  if (env.OPENAI_API_KEY) {
    try {
      const report = await buildReportWithOpenAI(items, warnings, env);
      report.warnings = [...warnings, ...(report.warnings || [])];
      return report;
    } catch (error) {
      warnings.push(`OpenAI report generation failed, fallback used: ${String(error.message || error)}`);
    }
  }

  return buildFallbackReport(items, warnings);
}

async function collectNews() {
  const warnings = [];
  const dedup = new Map();
  const jobs = RSS_FEEDS.map(async (feed) => {
    try {
      const response = await fetch(feed.url, {
        headers: { "user-agent": "global-news-agent-worker/1.0" },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const xml = await response.text();
      for (const item of parseFeed(feed.name, xml).slice(0, MAX_ITEMS_PER_FEED)) {
        const key = normalizeTitle(item.title);
        if (!key) continue;
        const existing = dedup.get(key);
        if (!existing || item.score > existing.score) dedup.set(key, item);
      }
    } catch (error) {
      warnings.push(`${feed.name}: ${String(error.message || error)}`);
    }
  });
  await Promise.all(jobs);
  const items = [...dedup.values()]
    .sort((a, b) => compareItems(b, a))
    .slice(0, TOP_EVENTS);
  return { items, warnings };
}

function compareItems(a, b) {
  return (a.score - b.score) || String(a.published).localeCompare(String(b.published));
}

function parseFeed(sourceName, xml) {
  if (xml.includes("<feed")) return parseAtomFeed(sourceName, xml);
  return parseRssFeed(sourceName, xml);
}

function parseAtomFeed(sourceName, xml) {
  const entries = extractBlocks(xml, "entry");
  return entries.map((entry) => {
    const title = cleanText(extractTag(entry, "title"));
    const summary = cleanText(extractTag(entry, "summary"));
    const published = parseDate(cleanText(extractTag(entry, "updated")));
    const link = extractAttr(entry, "link", "href");
    return enrichItem({ title, summary, published, link, source: sourceName });
  }).filter(Boolean);
}

function parseRssFeed(sourceName, xml) {
  const items = extractBlocks(xml, "item");
  return items.map((block) => {
    const title = cleanText(extractTag(block, "title"));
    const summary = cleanText(extractTag(block, "description"));
    const link = cleanText(extractTag(block, "link"));
    const published = parseDate(cleanText(extractTag(block, "pubDate")));
    return enrichItem({ title, summary, published, link, source: sourceName });
  }).filter(Boolean);
}

function enrichItem(item) {
  if (!item.title) return null;
  const combined = `${item.title} ${item.summary}`;
  return {
    ...item,
    category: categorize(combined),
    region: inferRegion(combined),
    score: scoreItem(item.title, item.summary, item.source),
  };
}

function extractBlocks(xml, tag) {
  const pattern = new RegExp(`<${tag}\\b[^>]*>([\\s\\S]*?)<\\/${tag}>`, "gi");
  return [...xml.matchAll(pattern)].map((match) => match[1]);
}

function extractTag(xml, tag) {
  const cdataPattern = new RegExp(`<${tag}\\b[^>]*><!\\[CDATA\\[([\\s\\S]*?)\\]\\]><\\/${tag}>`, "i");
  const cdataMatch = xml.match(cdataPattern);
  if (cdataMatch) return cdataMatch[1];
  const pattern = new RegExp(`<${tag}\\b[^>]*>([\\s\\S]*?)<\\/${tag}>`, "i");
  const match = xml.match(pattern);
  return match ? match[1] : "";
}

function extractAttr(xml, tag, attr) {
  const pattern = new RegExp(`<${tag}\\b[^>]*\\s${attr}="([^"]+)"[^>]*\\/?>`, "i");
  const match = xml.match(pattern);
  return match ? match[1] : "";
}

function cleanText(value) {
  return decodeHtml(String(value || ""))
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function decodeHtml(value) {
  return value
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, "\"")
    .replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, " ");
}

function containsKeyword(text, keyword) {
  const lowered = String(text || "").toLowerCase();
  const needle = String(keyword || "").trim().toLowerCase();
  if (!needle) return false;
  if (/^[a-z0-9 .-]+$/.test(needle)) {
    return new RegExp(`(?<![a-z0-9])${escapeRegex(needle)}(?![a-z0-9])`).test(lowered);
  }
  return lowered.includes(needle);
}

function escapeRegex(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function normalizeTitle(title) {
  return cleanText(title).toLowerCase().replace(/[^a-z0-9\u4e00-\u9fff ]+/g, " ").replace(/\s+/g, " ").trim();
}

function categorize(text) {
  let best = "综合";
  let bestScore = 0;
  for (const [category, keywords] of Object.entries(CATEGORY_KEYWORDS)) {
    const score = keywords.reduce((sum, keyword) => sum + (containsKeyword(text, keyword) ? 1 : 0), 0);
    if (score > bestScore) {
      best = category;
      bestScore = score;
    }
  }
  return best;
}

function inferRegion(text) {
  let best = "全球";
  let bestScore = 0;
  for (const [region, keywords] of Object.entries(REGION_RULES)) {
    const score = keywords.reduce((sum, keyword) => sum + (containsKeyword(text, keyword) ? 1 : 0), 0);
    if (score > bestScore) {
      best = region;
      bestScore = score;
    }
  }
  return best;
}

function scoreItem(title, summary, source) {
  const combined = `${title} ${summary}`;
  let score = 1;
  const impactWords = ["global", "world", "election", "war", "tariff", "oil", "fed", "economy", "sanction", "summit", "ceasefire", "earthquake", "storm", "chip", "ai", "hormuz", "missile", "nuclear"];
  for (const word of impactWords) if (containsKeyword(combined, word)) score += 2;
  if (String(source).toLowerCase().startsWith("reuters") || String(source).toLowerCase().startsWith("ap") || String(source).toLowerCase().startsWith("bbc")) score += 2;
  if (String(title).length > 55) score += 1;
  return score;
}

function assessSignificance(item) {
  const text = `${item.title} ${item.summary}`.toLowerCase();
  let score = item.score;
  const strategic = ["war", "missile", "nuclear", "ceasefire", "hormuz", "tariff", "sanction", "fed", "inflation", "interest rate", "oil", "gas", "earthquake", "summit"];
  const market = ["market", "bond", "currency", "trade", "shipping", "chip", "ai"];
  const leaders = ["trump", "president", "prime minister", "xi", "putin", "netanyahu"];
  for (const word of strategic) if (containsKeyword(text, word)) score += 2;
  for (const word of market) if (containsKeyword(text, word)) score += 1;
  for (const word of leaders) if (containsKeyword(text, word)) score += 1;
  if (item.category === "地缘政治" || item.category === "经济金融") score += 2;
  if (["中东", "北美", "欧洲", "亚太"].includes(item.region)) score += 1;
  if (/^(reuters|bbc|ap|npr|dw|the guardian)/i.test(item.source)) score += 1;
  if (score >= 14) return 5;
  if (score >= 10) return 4;
  if (score >= 7) return 3;
  if (score >= 4) return 2;
  return 1;
}

function parseDate(value) {
  const date = new Date(value);
  if (!Number.isNaN(date.getTime())) return date.toISOString().slice(0, 16).replace("T", " ");
  return cleanText(value);
}

async function buildReportWithOpenAI(items, warnings, env) {
  const today = isoDate();
  const payload = {
    model: env.OPENAI_MODEL || "gpt-5-mini",
    input: [
      {
        role: "system",
        content: [{
          type: "input_text",
          text:
            `你是国际时政与宏观研究编辑。基于给定 RSS 候选事件，生成一份适合中文读者阅读的全球大事日报。` +
            `不能捏造新事实，只能基于输入事件做筛选、翻译、归纳和影响分析。` +
            `全部使用简体中文，title 保留英文原标题，title_cn 提供自然中文标题，source_mode 固定写 rss_openai_edge。` +
            `generated_at 使用 ${today}。watchlist 提供 3 到 5 条。`,
        }],
      },
      {
        role: "user",
        content: [{
          type: "input_text",
          text: JSON.stringify({
            generated_at: today,
            warnings,
            candidates: items.map((item) => ({
              title: item.title,
              summary: item.summary,
              source_name: item.source,
              source_url: item.link,
              event_date: item.published,
              category_hint: item.category,
              region_hint: item.region,
              significance_hint: assessSignificance(item),
            })),
          }, null, 2),
        }],
      },
    ],
    text: {
      format: {
        type: "json_schema",
        name: "global_news_report",
        strict: true,
        schema: REPORT_SCHEMA,
      },
    },
  };

  const response = await fetch("https://api.openai.com/v1/responses", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${env.OPENAI_API_KEY}`,
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(`OpenAI HTTP ${response.status}`);
  }
  const raw = await response.json();
  const text = parseResponseOutputText(raw);
  return JSON.parse(text);
}

function parseResponseOutputText(raw) {
  if (typeof raw.output_text === "string" && raw.output_text.trim()) return raw.output_text.trim();
  const chunks = [];
  for (const item of raw.output || []) {
    if (item.type !== "message") continue;
    for (const content of item.content || []) {
      if (typeof content.text === "string") chunks.push(content.text);
    }
  }
  return chunks.join("").trim();
}

function buildFallbackReport(items, warnings) {
  const enrichedItems = items.map((item) => {
    const significance = assessSignificance(item);
    const hasEnergy = ["oil", "gas", "energy", "hormuz", "shipping"].some((word) => containsKeyword(`${item.title} ${item.summary}`, word));
    return {
      title: item.title,
      title_cn: item.title,
      category: item.category,
      region: item.region,
      significance,
      original_summary_en: item.summary || item.title,
      summary_cn: item.summary || item.title,
      impact_cn: hasEnergy ? "事件可能通过能源和航运渠道外溢到更广泛市场。" : "事件短期内主要影响风险偏好和政策预期。",
      economic_impact_cn: hasEnergy ? "宏观上重点看能源、运价和通胀预期是否重定价。" : "宏观影响仍需观察是否进入增长、监管或贸易层面。",
      asset_impact_cn: hasEnergy ? "原油、黄金和航运链相对更敏感。" : "市场初期更可能围绕情绪和避险资产波动。",
      china_sector_impact_cn: "中国相关行业需关注供应链、外贸、能源成本和运力扰动。",
      china_impact_cn: "对中国的影响取决于事件是否继续外溢到贸易、能源或监管领域。",
      market_impact_cn: "市场可能先做情绪定价，再根据后续政策与基本面修正。",
      watchpoints_cn: "关注官方表态、二次升级以及资产价格的联动反馈。",
      event_date: item.published || isoDate(),
      source_name: item.source,
      source_url: item.link,
    };
  });

  return {
    generated_at: isoDate(),
    source_mode: "rss_edge_fallback",
    executive_summary: "日报基于边缘侧 RSS 聚合即时生成，当前未启用 OpenAI 中文深度整理。",
    china_brief: "中国视角下建议优先观察能源、贸易链路和外部风险偏好的传导。",
    market_brief: "市场层面优先关注能源、汇率、避险资产和科技板块的联动。",
    watchlist: ["主要经济体政策表态", "能源与航运扰动", "全球股债汇二次定价", "科技与安全监管变化"],
    items: enrichedItems,
    warnings,
  };
}

function isoDate() {
  return new Date().toISOString().slice(0, 10);
}

function json(data, extraHeaders = {}) {
  return new Response(JSON.stringify(data, null, 2), {
    headers: {
      "content-type": "application/json; charset=utf-8",
      ...extraHeaders,
    },
  });
}

function buildDashboardHtml() {
  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Global News Agent</title>
  <style>
    :root{--bg:#efe3d2;--paper:#fffaf2;--ink:#17202b;--muted:#5b6472;--accent:#b14a22;--line:rgba(23,32,43,.12)}
    *{box-sizing:border-box} body{margin:0;font-family:"Segoe UI","Microsoft YaHei",sans-serif;color:var(--ink);background:linear-gradient(180deg,#f5eadb 0%,#efe3d2 100%)}
    .page{width:min(1180px,calc(100% - 24px));margin:0 auto;padding:24px 0 48px}
    .hero{background:#17202b;color:#fff;border-radius:28px;padding:28px;box-shadow:0 24px 48px rgba(0,0,0,.12)}
    .hero h1{margin:10px 0;font-size:clamp(30px,5vw,52px)}
    .hero p{margin:8px 0;color:rgba(255,255,255,.82);line-height:1.7}
    .toolbar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:18px 0}
    button{border:0;background:var(--accent);color:#fff;padding:10px 14px;border-radius:999px;cursor:pointer}
    .secondary{background:#fff;color:var(--ink);border:1px solid var(--line)}
    .panel{background:var(--paper);border:1px solid var(--line);border-radius:22px;padding:18px;box-shadow:0 18px 36px rgba(0,0,0,.06)}
    .summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-top:16px}
    .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px;margin-top:18px}
    .card{background:var(--paper);border:1px solid var(--line);border-radius:22px;padding:18px}
    .eyebrow{font-size:12px;color:var(--muted);letter-spacing:.08em;text-transform:uppercase}
    .card h2{margin:8px 0 0;font-size:22px;line-height:1.35}
    .original{color:var(--muted);font-size:14px;line-height:1.6;margin-top:8px}
    .meta{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}
    .tag{display:inline-block;padding:6px 10px;border-radius:999px;background:#f3dfd1;color:var(--accent);font-size:12px}
    .tag.alt{background:#dbe9e4;color:#1f5c4d}
    .card p{line-height:1.7;margin:10px 0}
    .status{margin-top:14px;color:var(--muted)}
    .warning{margin-top:18px;padding:16px;border-radius:18px;background:rgba(177,74,34,.08);border:1px solid rgba(177,74,34,.22)}
    a{color:var(--accent);text-decoration:none}
    @media (max-width:900px){.summary{grid-template-columns:1fr}}
  </style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <div class="eyebrow">Cloudflare Edge Edition</div>
      <h1>Global News Agent</h1>
      <p>长期部署版本。页面和 API 由 Cloudflare Worker 提供，RSS 在边缘抓取，中文报告优先通过 OpenAI secret 生成。</p>
      <div class="toolbar">
        <button id="refreshBtn">刷新日报</button>
        <a class="secondary" href="/api/report" target="_blank" rel="noreferrer">查看 JSON</a>
      </div>
      <div class="status" id="status">正在加载报告...</div>
    </section>
    <section class="summary" id="summary"></section>
    <section class="cards" id="cards"></section>
    <section class="warning" id="warning" hidden></section>
  </main>
  <script>
    const statusNode = document.getElementById('status');
    const summaryNode = document.getElementById('summary');
    const cardsNode = document.getElementById('cards');
    const warningNode = document.getElementById('warning');
    async function loadReport(refresh) {
      statusNode.textContent = refresh ? '正在刷新...' : '正在加载报告...';
      const response = await fetch('/api/report' + (refresh ? '?refresh=1' : ''));
      const report = await response.json();
      statusNode.textContent = '生成日期: ' + (report.generated_at || '') + ' | 模式: ' + (report.source_mode || '');
      summaryNode.innerHTML = [
        ['总览', report.executive_summary || ''],
        ['中国视角', report.china_brief || ''],
        ['市场视角', report.market_brief || '']
      ].map(([title, text]) => '<article class="panel"><h3>' + title + '</h3><p>' + text + '</p></article>').join('');
      cardsNode.innerHTML = (report.items || []).map((item, index) => \`
        <article class="card">
          <div class="eyebrow">#\${String(index + 1).padStart(2, '0')} | \${item.event_date || ''}</div>
          <h2>\${escapeHtml(item.title_cn || item.title || '')}</h2>
          <div class="original">\${escapeHtml(item.title || '')}</div>
          <div class="meta">
            <span class="tag">\${escapeHtml(item.category || '')}</span>
            <span class="tag alt">\${escapeHtml(item.region || '')}</span>
            <span class="tag">重要度 \${item.significance || ''}/5</span>
          </div>
          <p><strong>摘要</strong> \${escapeHtml(item.summary_cn || '')}</p>
          <p><strong>宏观</strong> \${escapeHtml(item.economic_impact_cn || '')}</p>
          <p><strong>市场</strong> \${escapeHtml(item.market_impact_cn || '')}</p>
          <p><strong>中国</strong> \${escapeHtml(item.china_impact_cn || '')}</p>
          <p><strong>观察</strong> \${escapeHtml(item.watchpoints_cn || '')}</p>
          <p><a href="\${escapeHtml(item.source_url || '#')}" target="_blank" rel="noreferrer">原始链接</a></p>
        </article>
      \`).join('');
      if (report.warnings && report.warnings.length) {
        warningNode.hidden = false;
        warningNode.innerHTML = '<strong>Warnings</strong><ul>' + report.warnings.map((item) => '<li>' + escapeHtml(item) + '</li>').join('') + '</ul>';
      } else {
        warningNode.hidden = true;
      }
    }
    function escapeHtml(value) {
      return String(value || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
    document.getElementById('refreshBtn').addEventListener('click', () => loadReport(true).catch(showError));
    function showError(error) {
      statusNode.textContent = '加载失败: ' + String(error && error.message ? error.message : error);
    }
    loadReport(false).catch(showError);
  </script>
</body>
</html>`;
}
