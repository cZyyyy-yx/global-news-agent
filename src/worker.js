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

    if (url.pathname === "/api/history") {
      return json(await listHistory(env));
    }

    if (url.pathname === "/api/trends") {
      return json(await buildTrendSnapshot(env));
    }

    if (url.pathname === "/api/search") {
      return json(await searchHistory(env, url.searchParams.get("q") || ""));
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
  ctx.waitUntil(persistReport(env, report));
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

  return await buildFallbackReport(items, warnings);
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

async function buildFallbackReport(items, warnings) {
  const enrichedItems = await Promise.all(items.map(async (item) => {
    const translatedTitle = await translateText(item.title);
    const translatedSummary = await translateText(item.summary || item.title);
    const analysis = fallbackAnalysis(item);
    return {
      title: item.title,
      title_cn: polishCnTitle(translatedTitle || item.title),
      category: item.category,
      region: item.region,
      significance: analysis.significance,
      original_summary_en: item.summary || item.title,
      summary_cn: polishCnSummary(translatedSummary || item.summary || item.title, item.title),
      impact_cn: analysis.impact_cn,
      economic_impact_cn: analysis.economic_impact_cn,
      asset_impact_cn: analysis.asset_impact_cn,
      china_sector_impact_cn: analysis.china_sector_impact_cn,
      china_impact_cn: analysis.china_impact_cn,
      market_impact_cn: analysis.market_impact_cn,
      watchpoints_cn: analysis.watchpoints_cn,
      event_date: item.published || isoDate(),
      source_name: item.source,
      source_url: item.link,
    };
  }));

  return {
    generated_at: isoDate(),
    source_mode: "rss_edge_fallback",
    executive_summary: buildExecutiveSummary(enrichedItems),
    china_brief: buildChinaBrief(enrichedItems),
    market_brief: "市场层面优先关注能源、汇率、避险资产和科技板块的联动。",
    watchlist: buildWatchlist(warnings),
    items: enrichedItems,
    warnings,
  };
}

async function translateText(text) {
  const cleaned = cleanText(text);
  if (!cleaned) return "";
  if (/[\u4e00-\u9fff]/.test(cleaned)) return cleaned;
  const endpoints = [
    "https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=zh-CN&dt=t&q=" + encodeURIComponent(cleaned),
    "https://api.mymemory.translated.net/get?q=" + encodeURIComponent(cleaned) + "&langpair=en|zh-CN",
  ];
  for (const url of endpoints) {
    try {
      const response = await fetch(url, { headers: { "user-agent": "global-news-agent-worker/1.0" } });
      if (!response.ok) continue;
      if (url.includes("translate.googleapis.com")) {
        const parsed = await response.json();
        const translated = (parsed[0] || []).map((part) => part && part[0] ? part[0] : "").join("").trim();
        if (translated) return translated;
      } else {
        const parsed = await response.json();
        const translated = cleanText(parsed?.responseData?.translatedText || "");
        if (translated) return translated;
      }
    } catch (_error) {
      continue;
    }
  }
  return cleaned;
}

function polishCnTitle(text) {
  let value = cleanText(text);
  if (!value) return "";
  value = value.replace(/^中文标题[:：]\s*/i, "");
  value = value.replace(/直播[:：]?/g, "");
  value = value.replace(/\s*\([^()]*\)/g, "");
  value = value.replace(/\s+/g, " ").trim().replace(/[ .;；，,]+$/g, "");
  return value;
}

function polishCnSummary(text, originalTitle = "") {
  let value = cleanText(text);
  if (!value) return polishCnTitle(originalTitle);
  value = value.replace(/继续阅读[。.…]*/gi, "");
  value = value.replace(/Continue reading[。.…]*/gi, "");
  value = value.replace(/^我们了解[^，。:：]*[，。:：]\s*/u, "");
  value = value.replace(/^最新消息[，。:：]\s*/u, "");
  value = value.replace(/^直播[：:]\s*/u, "");
  value = value.replace(/\s*\([^()]*\)/g, "");
  value = value.replace(/\s+/g, " ").trim().replace(/[ .;；，,]+$/g, "");
  const parts = value.split(/[。！？]/).map((part) => part.trim()).filter(Boolean);
  const dedup = [];
  const seen = new Set();
  for (const part of parts) {
    const normalized = part.replace(/\s+/g, "");
    if (normalized.length < 8 || seen.has(normalized)) continue;
    seen.add(normalized);
    dedup.push(part);
    if (dedup.length >= 2) break;
  }
  value = dedup.length ? dedup.join("。") + "。" : value;
  if (value.length > 88 && value.includes("。")) value = value.split("。")[0].trim() + "。";
  return value || polishCnTitle(originalTitle);
}

function fallbackAnalysis(item) {
  const text = `${item.title} ${item.summary}`.toLowerCase();
  const hasEnergy = ["oil", "gas", "energy", "hormuz", "shipping"].some((word) => containsKeyword(text, word));
  const hasPolicy = ["fed", "rate", "inflation", "tariff", "sanction", "policy", "shutdown"].some((word) => containsKeyword(text, word));
  const hasTech = ["ai", "chip", "semiconductor", "cyber", "software", "data"].some((word) => containsKeyword(text, word));
  const hasConflict = ["war", "missile", "military", "strike", "nuclear", "conflict"].some((word) => containsKeyword(text, word));
  const hasConsumption = ["airport", "travel", "consumer", "concert", "tourism"].some((word) => containsKeyword(text, word));

  let impactParts;
  let chinaParts;
  let marketParts;
  let economicParts;
  let assetParts;
  let chinaSectorParts;

  if (item.category === "地缘政治") {
    impactParts = ["事件会先影响区域安全预期。", hasEnergy ? "若波及能源运输，全球风险资产和通胀预期会一起受扰动。" : "后续要看是否外溢到制裁、航运或外交升级。"];
    chinaParts = ["中国层面主要看能源进口、航运安全和外交平衡。"];
    if (["中东", "欧洲"].includes(item.region)) chinaParts.push("若冲突持续，相关原材料和远洋链路的稳定性会更关键。");
    marketParts = ["市场通常先交易避险情绪。", hasEnergy ? "原油、黄金与航运链条更容易成为第一反应资产。" : "汇率、黄金和国防链弹性可能更明显。"];
    economicParts = ["宏观上要看能源、贸易和运价是否被重新定价。"];
    if (hasPolicy) economicParts.push("如果伴随制裁升级，外贸和资本流向也会受影响。");
    assetParts = ["资产层面偏利多避险资产和上游资源。"];
    if (hasConflict) assetParts.push("航空、可选消费和高估值成长板块相对承压。");
    chinaSectorParts = ["中国行业链条重点看油气、航运、化工和外贸制造。"];
    if (hasTech) chinaSectorParts.push("若牵涉技术限制，电子和通信链也要防二次冲击。");
  } else if (item.category === "经济金融") {
    impactParts = ["事件更容易改变利率预期、汇率走势和跨境资本流向。"];
    if (hasEnergy) impactParts.push("如果能源价格同步波动，全球通胀路径会更复杂。");
    chinaParts = ["中国主要看外需、人民币汇率和政策对冲空间。"];
    if (hasPolicy) chinaParts.push("出口链和稳增长政策的节奏可能需要重新评估。");
    marketParts = ["股债汇商品会围绕政策预期重新定价。"];
    economicParts = ["核心观察点是增长、通胀、利率和贸易条件是否同时发生变化。"];
    assetParts = ["美元、美债、黄金、工业品和权益风格切换是主要交易线索。"];
    chinaSectorParts = ["中国相关行业重点看出口制造、金融地产、大宗原材料和高股息资产。"];
  } else if (item.category === "科技产业") {
    impactParts = ["事件会先影响 AI、芯片、网络安全和关键供应链预期。"];
    if (hasPolicy) impactParts.push("若伴随监管或出口限制，全球科技链会更快重估。");
    chinaParts = ["中国重点看技术管制、国产替代和产业链再配置。"];
    marketParts = ["科技股估值、半导体和算力链对消息面最敏感。"];
    economicParts = ["宏观上传导到资本开支、生产率预期和科技投资周期。"];
    assetParts = ["半导体、云计算、AI 应用与网络安全板块波动会更明显。"];
    chinaSectorParts = ["中国受影响方向主要是算力、芯片设备、工业软件和国产替代链条。"];
  } else if (item.category === "气候灾害") {
    impactParts = ["事件会冲击局部供应链、物流和保险成本。"];
    if (hasEnergy) impactParts.push("若波及港口或能源产区，影响会明显放大。");
    chinaParts = ["中国要看进口原料、航运时效和制造交付是否受牵连。"];
    marketParts = ["能源、航运、保险和公用事业相关资产更敏感。"];
    economicParts = ["宏观影响通常体现为供给收缩、物流受阻和重建支出抬升。"];
    assetParts = ["商品、航运、保险和公用事业板块更容易出现相对收益。"];
    chinaSectorParts = ["相关产业链重点看上游原料、港口物流和制造排产。"];
  } else if (item.category === "公共卫生") {
    impactParts = ["事件会影响公共卫生政策、跨境流动和服务消费预期。"];
    chinaParts = ["中国重点观察跨境流动、医疗物资和风险沟通节奏。"];
    marketParts = ["旅游、消费和医药板块容易出现分化交易。"];
    economicParts = ["宏观上传导到服务消费恢复、劳动力供给和出行活动。"];
    assetParts = ["医药、航空、酒店和可选消费更容易出现分化。"];
    chinaSectorParts = ["中国相关方向主要是医疗供应链、出行消费和跨境商务活动。"];
  } else {
    impactParts = ["短期内重点看事件是否继续扩散到政策、贸易或市场层面。"];
    if (hasConsumption) impactParts.push("如果影响居民出行或消费，服务业预期会更快反映。");
    chinaParts = ["与中国的直接关联暂时有限，但要持续看贸易、舆情和外交层面变化。"];
    marketParts = ["市场初期更多受情绪驱动，后续取决于政策和基本面确认。"];
    economicParts = ["宏观影响仍需观察是否演变为增长、成本或监管变量。"];
    assetParts = ["资产价格会先做情绪定价，再看基本面是否跟进。"];
    chinaSectorParts = ["对中国行业的传导还不清晰，先看供应链、贸易和监管信号。"];
  }

  const watchpoints = [];
  if (["oil", "gas", "hormuz", "sanction", "tariff"].some((word) => containsKeyword(text, word))) watchpoints.push("关注能源价格、航运路线和制裁措施是否升级。");
  if (["fed", "rate", "inflation", "jobs", "bond"].some((word) => containsKeyword(text, word))) watchpoints.push("关注后续数据和央行表态是否修正利率预期。");
  if (["chip", "ai", "cyber", "software"].some((word) => containsKeyword(text, word))) watchpoints.push("关注技术出口限制、企业财报与监管动作。");
  if (!watchpoints.length) watchpoints.push("关注官方声明、二次传播和市场反馈。");

  return {
    significance: assessSignificance(item),
    impact_cn: impactParts.join(" "),
    economic_impact_cn: economicParts.join(" "),
    asset_impact_cn: assetParts.join(" "),
    china_sector_impact_cn: chinaSectorParts.join(" "),
    china_impact_cn: chinaParts.join(" "),
    market_impact_cn: marketParts.join(" "),
    watchpoints_cn: watchpoints.join(" "),
  };
}

function buildExecutiveSummary(items) {
  const categoryCounts = countBy(items, "category");
  const topCategories = [...categoryCounts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3).map(([name]) => name);
  return `今日全球重点集中在${topCategories.length ? topCategories.join("、") : "多领域事件"}，需同时关注政策表态与市场定价。`;
}

function buildChinaBrief(items) {
  const regionCounts = countBy(items, "region");
  const topRegions = [...regionCounts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 2).map(([name]) => name);
  return `中国相关观察重点在${topRegions.length ? topRegions.join("、") : "外部需求与供应链"}的外溢影响。`;
}

function buildWatchlist(warnings) {
  const watchlist = [
    "主要经济体最新政策表态",
    "能源价格与航运扰动是否扩大",
    "全球股债汇是否出现二次定价",
    "科技与安全监管是否加码",
  ];
  if (warnings.length) watchlist.push("关注新闻源缺口是否影响事件覆盖面");
  return watchlist.slice(0, 5);
}

function countBy(items, key) {
  const counter = new Map();
  for (const item of items) {
    const name = item[key] || "未知";
    counter.set(name, (counter.get(name) || 0) + 1);
  }
  return counter;
}

async function persistReport(env, report) {
  if (!env.REPORTS_KV || typeof env.REPORTS_KV.put !== "function") return;
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const reportKey = `report:${stamp}`;
  const meta = {
    key: reportKey,
    generated_at: report.generated_at || isoDate(),
    source_mode: report.source_mode || "",
    event_count: Array.isArray(report.items) ? report.items.length : 0,
    top_titles: (report.items || []).slice(0, 3).map((item) => item.title_cn || item.title || ""),
  };

  let history = [];
  try {
    history = JSON.parse(await env.REPORTS_KV.get("history:index", "text") || "[]");
  } catch (_error) {
    history = [];
  }
  history = [meta, ...history.filter((item) => item.key !== reportKey)].slice(0, 30);

  await Promise.all([
    env.REPORTS_KV.put(reportKey, JSON.stringify(report)),
    env.REPORTS_KV.put("history:index", JSON.stringify(history)),
    env.REPORTS_KV.put("history:latest", JSON.stringify(meta)),
  ]);
}

async function listHistory(env) {
  if (!env.REPORTS_KV || typeof env.REPORTS_KV.get !== "function") {
    return {
      storage_enabled: false,
      items: [],
      message: "REPORTS_KV not configured. Deploy works, but history is disabled until KV is bound.",
    };
  }
  try {
    const items = JSON.parse(await env.REPORTS_KV.get("history:index", "text") || "[]");
    return { storage_enabled: true, items };
  } catch (_error) {
    return { storage_enabled: true, items: [], message: "History index is empty or unreadable." };
  }
}

async function buildTrendSnapshot(env) {
  const historyPayload = await listHistory(env);
  if (!historyPayload.storage_enabled) {
    return {
      storage_enabled: false,
      snapshot_count: 0,
      category_counts: [],
      region_counts: [],
      keyword_counts: [],
      message: historyPayload.message,
    };
  }

  const historyItems = historyPayload.items || [];
  const reports = [];
  for (const entry of historyItems.slice(0, 20)) {
    try {
      const raw = await env.REPORTS_KV.get(entry.key, "text");
      if (raw) reports.push(JSON.parse(raw));
    } catch (_error) {
      continue;
    }
  }

  const categoryCounts = new Map();
  const regionCounts = new Map();
  const keywordCounts = new Map();
  for (const report of reports) {
    for (const item of report.items || []) {
      incMap(categoryCounts, item.category || "综合");
      incMap(regionCounts, item.region || "全球");
      for (const token of tokenizeTitle(item.title || "")) incMap(keywordCounts, token);
    }
  }

  return {
    storage_enabled: true,
    snapshot_count: reports.length,
    category_counts: toSortedArray(categoryCounts, 6),
    region_counts: toSortedArray(regionCounts, 6),
    keyword_counts: toSortedArray(keywordCounts, 10),
  };
}

async function searchHistory(env, query) {
  const needle = cleanText(query).toLowerCase();
  if (!needle) {
    return { storage_enabled: !!env.REPORTS_KV, items: [], message: "Empty query." };
  }
  if (!env.REPORTS_KV || typeof env.REPORTS_KV.get !== "function") {
    return {
      storage_enabled: false,
      items: [],
      message: "REPORTS_KV not configured. Search is disabled until KV is bound.",
    };
  }

  const historyPayload = await listHistory(env);
  const results = [];
  for (const entry of (historyPayload.items || []).slice(0, 20)) {
    try {
      const raw = await env.REPORTS_KV.get(entry.key, "text");
      if (!raw) continue;
      const report = JSON.parse(raw);
      for (const item of report.items || []) {
        const haystack = [
          item.title,
          item.title_cn,
          item.summary_cn,
          item.original_summary_en,
          item.category,
          item.region,
          item.source_name,
        ].map((value) => cleanText(value)).join(" ").toLowerCase();
        if (!haystack.includes(needle)) continue;
        results.push({
          generated_at: report.generated_at || "",
          snapshot_key: entry.key,
          title: item.title || "",
          title_cn: item.title_cn || "",
          category: item.category || "",
          region: item.region || "",
          source_name: item.source_name || "",
          event_date: item.event_date || "",
          source_url: item.source_url || "",
        });
        if (results.length >= 30) {
          return { storage_enabled: true, items: results };
        }
      }
    } catch (_error) {
      continue;
    }
  }
  return { storage_enabled: true, items: results };
}

function incMap(map, key) {
  map.set(key, (map.get(key) || 0) + 1);
}

function toSortedArray(map, limit) {
  return [...map.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit)
    .map(([name, count]) => ({ name, count }));
}

function tokenizeTitle(title) {
  const stopwords = new Set(["the", "and", "for", "with", "from", "after", "into", "amid", "says", "say", "over", "near", "week", "this", "that", "will", "have", "has", "are", "was", "iran", "israel", "trump", "world", "news"]);
  return cleanText(title)
    .toLowerCase()
    .match(/[a-z]{3,}/g)
    ?.filter((token) => !stopwords.has(token)) || [];
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
    .insight{display:grid;grid-template-columns:1.1fr .9fr;gap:16px;margin-top:18px}
    .search-box{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px}
    .search-box input{flex:1 1 220px;border:1px solid var(--line);border-radius:14px;padding:11px 12px;background:#fff;color:var(--ink)}
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
    .mini-list{display:grid;gap:10px}
    .mini-item{border:1px solid var(--line);border-radius:16px;padding:12px;background:rgba(255,255,255,.72)}
    a{color:var(--accent);text-decoration:none}
    @media (max-width:900px){.summary,.insight{grid-template-columns:1fr}}
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
    <section class="insight">
      <section class="panel">
        <h3>历史搜索</h3>
        <div class="search-box">
          <input id="searchInput" type="search" placeholder="搜索历史标题、摘要、来源，例如 Iran / 芯片 / 美联储">
          <button class="secondary" id="searchBtn">搜索</button>
        </div>
        <div class="mini-list" id="searchList"><div class="mini-item">输入关键词后可搜索历史归档。</div></div>
        <div class="mini-list" id="historyList" style="margin-top:12px;"><div class="mini-item">正在加载...</div></div>
      </section>
      <section class="panel">
        <h3>趋势看板</h3>
        <div class="mini-list" id="trendList"><div class="mini-item">正在加载...</div></div>
      </section>
    </section>
    <section class="cards" id="cards"></section>
    <section class="warning" id="warning" hidden></section>
  </main>
  <script>
    const statusNode = document.getElementById('status');
    const summaryNode = document.getElementById('summary');
    const searchInput = document.getElementById('searchInput');
    const searchBtn = document.getElementById('searchBtn');
    const searchNode = document.getElementById('searchList');
    const historyNode = document.getElementById('historyList');
    const trendNode = document.getElementById('trendList');
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
    async function loadHistory() {
      const response = await fetch('/api/history');
      const payload = await response.json();
      if (!payload.storage_enabled) {
        historyNode.innerHTML = '<div class="mini-item">' + escapeHtml(payload.message || 'History disabled') + '</div>';
        return;
      }
      const items = payload.items || [];
      if (!items.length) {
        historyNode.innerHTML = '<div class="mini-item">历史归档为空。先刷新几次日报或绑定定时触发。</div>';
        return;
      }
      historyNode.innerHTML = items.map((item) => '<div class="mini-item"><strong>' + escapeHtml(item.generated_at || '') + '</strong><div>模式: ' + escapeHtml(item.source_mode || '') + '</div><div>事件数: ' + escapeHtml(String(item.event_count || 0)) + '</div><div>' + escapeHtml((item.top_titles || []).slice(0, 2).join(' / ')) + '</div></div>').join('');
    }
    async function runSearch() {
      const q = (searchInput && searchInput.value || '').trim();
      if (!q) {
        searchNode.innerHTML = '<div class="mini-item">输入关键词后可搜索历史归档。</div>';
        return;
      }
      const response = await fetch('/api/search?q=' + encodeURIComponent(q));
      const payload = await response.json();
      if (!payload.storage_enabled) {
        searchNode.innerHTML = '<div class="mini-item">' + escapeHtml(payload.message || 'Search disabled') + '</div>';
        return;
      }
      const items = payload.items || [];
      if (!items.length) {
        searchNode.innerHTML = '<div class="mini-item">没有匹配到历史事件。</div>';
        return;
      }
      searchNode.innerHTML = items.map((item) => '<div class="mini-item"><strong>' + escapeHtml(item.title_cn || item.title || '') + '</strong><div>' + escapeHtml(item.generated_at || '') + ' | ' + escapeHtml(item.category || '') + ' | ' + escapeHtml(item.region || '') + ' | ' + escapeHtml(item.source_name || '') + '</div><div><a href="' + escapeHtml(item.source_url || '#') + '" target="_blank" rel="noreferrer">原始链接</a></div></div>').join('');
    }
    async function loadTrends() {
      const response = await fetch('/api/trends');
      const payload = await response.json();
      if (!payload.storage_enabled) {
        trendNode.innerHTML = '<div class="mini-item">' + escapeHtml(payload.message || 'Trend storage disabled') + '</div>';
        return;
      }
      trendNode.innerHTML = [
        '<div class="mini-item"><strong>快照数</strong><div>' + escapeHtml(String(payload.snapshot_count || 0)) + '</div></div>',
        '<div class="mini-item"><strong>高频类别</strong><div>' + escapeHtml((payload.category_counts || []).map((x) => x.name + ' ' + x.count).join(' / ')) + '</div></div>',
        '<div class="mini-item"><strong>高频区域</strong><div>' + escapeHtml((payload.region_counts || []).map((x) => x.name + ' ' + x.count).join(' / ')) + '</div></div>',
        '<div class="mini-item"><strong>英文主题词</strong><div>' + escapeHtml((payload.keyword_counts || []).map((x) => x.name + ' ' + x.count).join(' / ')) + '</div></div>'
      ].join('');
    }
    function escapeHtml(value) {
      return String(value || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
    document.getElementById('refreshBtn').addEventListener('click', () => loadReport(true).catch(showError));
    if (searchBtn) searchBtn.addEventListener('click', () => runSearch().catch(() => null));
    if (searchInput) searchInput.addEventListener('keydown', (event) => { if (event.key === 'Enter') runSearch().catch(() => null); });
    function showError(error) {
      statusNode.textContent = '加载失败: ' + String(error && error.message ? error.message : error);
    }
    loadReport(false).catch(showError);
    loadHistory().catch(() => null);
    loadTrends().catch(() => null);
  </script>
</body>
</html>`;
}
