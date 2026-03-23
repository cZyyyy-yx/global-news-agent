import html
import json
import os
import re
import smtplib
import ssl
import textwrap
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from email.mime.text import MIMEText
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "reports"
DATA_DIR = ROOT / "data"
ARCHIVE_OUTPUT_DIR = OUTPUT_DIR / "archive"
ARCHIVE_DATA_DIR = DATA_DIR / "archive"
CONFIG_PATH = ROOT / "config.json"
TRANSLATION_CACHE_PATH = DATA_DIR / "translation_cache.json"

DEFAULT_CONFIG = {
    "mode": "auto",
    "max_items_per_feed": 12,
    "top_events": 8,
    "report_timezone": "Asia/Shanghai",
    "openai_model": "gpt-5-mini",
    "openai_reasoning_effort": "low",
    "openai_web_search_enabled": True,
    "openai_rss_rewrite_enabled": True,
    "translation_mode": "auto",
    "notification": {
        "email_enabled": False,
        "webhook_enabled": False,
        "chat_webhook_enabled": False,
        "email_subject_prefix": "全球大事智能日报",
    },
    "rss_feeds": [
        {"name": "Reuters World", "url": "https://feeds.reuters.com/Reuters/worldNews"},
        {"name": "BBC World", "url": "http://feeds.bbci.co.uk/news/world/rss.xml"},
        {"name": "AP Top News", "url": "https://apnews.com/hub/ap-top-news?output=rss"},
        {"name": "NPR World", "url": "https://feeds.npr.org/1004/rss.xml"},
        {"name": "The Guardian World", "url": "https://www.theguardian.com/world/rss"},
        {"name": "Al Jazeera", "url": "https://www.aljazeera.com/xml/rss/all.xml"},
        {"name": "DW World", "url": "https://rss.dw.com/rdf/rss-en-world"},
    ],
}

CATEGORY_KEYWORDS = {
    "地缘政治": ["war", "military", "missile", "sanction", "summit", "president", "minister", "conflict", "border", "nato", "iran", "israel", "ukraine"],
    "经济金融": ["economy", "inflation", "rate", "market", "trade", "tariff", "jobs", "oil", "fed", "central bank", "gdp", "bond"],
    "科技产业": ["ai", "chip", "semiconductor", "tech", "cyber", "software", "internet", "data", "cloud", "robot"],
    "气候灾害": ["climate", "storm", "flood", "earthquake", "wildfire", "heat", "emissions", "weather"],
    "公共卫生": ["health", "virus", "outbreak", "vaccine", "hospital", "disease"],
}

REGION_RULES = {
    "中东": ["iran", "israel", "gaza", "syria", "lebanon", "hormuz", "saudi", "uae"],
    "欧洲": ["eu", "europe", "ukraine", "russia", "france", "germany", "britain", "uk"],
    "北美": ["us", "u.s.", "america", "canada", "trump", "fed", "washington"],
    "亚太": ["china", "japan", "korea", "taiwan", "india", "asia", "pacific"],
    "拉美": ["brazil", "mexico", "argentina", "latin"],
    "非洲": ["africa", "sudan", "nigeria", "ethiopia"],
}

TREND_STOPWORDS = {
    "the", "and", "for", "with", "from", "after", "into", "amid", "says", "say", "over",
    "near", "week", "this", "that", "into", "will", "have", "has", "had", "are", "was",
    "were", "about", "their", "they", "them", "more", "than", "what", "when", "where",
    "iran", "israel", "trump", "world", "news", "says", "threatens",
}

OPENAI_REPORT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "generated_at",
        "source_mode",
        "executive_summary",
        "china_brief",
        "market_brief",
        "watchlist",
        "items",
    ],
    "properties": {
        "generated_at": {"type": "string"},
        "source_mode": {"type": "string"},
        "executive_summary": {"type": "string"},
        "china_brief": {"type": "string"},
        "market_brief": {"type": "string"},
        "watchlist": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 5,
        },
        "items": {
            "type": "array",
            "maxItems": 10,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
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
                "properties": {
                    "title": {"type": "string"},
                    "title_cn": {"type": "string"},
                    "category": {"type": "string"},
                    "region": {"type": "string"},
                    "significance": {"type": "integer", "minimum": 1, "maximum": 5},
                    "original_summary_en": {"type": "string"},
                    "summary_cn": {"type": "string"},
                    "impact_cn": {"type": "string"},
                    "economic_impact_cn": {"type": "string"},
                    "asset_impact_cn": {"type": "string"},
                    "china_sector_impact_cn": {"type": "string"},
                    "china_impact_cn": {"type": "string"},
                    "market_impact_cn": {"type": "string"},
                    "watchpoints_cn": {"type": "string"},
                    "event_date": {"type": "string"},
                    "source_name": {"type": "string"},
                    "source_url": {"type": "string"},
                },
            },
        },
    },
}

OPENAI_RSS_REWRITE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["items"],
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "index",
                    "title_cn",
                    "summary_cn",
                    "impact_cn",
                    "economic_impact_cn",
                    "asset_impact_cn",
                    "china_sector_impact_cn",
                    "china_impact_cn",
                    "market_impact_cn",
                    "watchpoints_cn",
                ],
                "properties": {
                    "index": {"type": "integer", "minimum": 0},
                    "title_cn": {"type": "string"},
                    "summary_cn": {"type": "string"},
                    "impact_cn": {"type": "string"},
                    "economic_impact_cn": {"type": "string"},
                    "asset_impact_cn": {"type": "string"},
                    "china_sector_impact_cn": {"type": "string"},
                    "china_impact_cn": {"type": "string"},
                    "market_impact_cn": {"type": "string"},
                    "watchpoints_cn": {"type": "string"},
                },
            },
        }
    },
}


@dataclass
class NewsItem:
    title: str
    link: str
    source: str
    published: str
    summary: str
    category: str
    region: str
    score: int


def ensure_dirs() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True)
    ARCHIVE_OUTPUT_DIR.mkdir(exist_ok=True)
    ARCHIVE_DATA_DIR.mkdir(exist_ok=True)


def build_archive_stamp(report: dict[str, Any]) -> str:
    raw_generated_at = str(report.get("generated_at", "")).strip()
    date_key = raw_generated_at[:10] if raw_generated_at else datetime.now().strftime("%Y-%m-%d")
    safe_date = "".join(char for char in date_key if char.isdigit() or char == "-") or datetime.now().strftime("%Y-%m-%d")
    return f"{safe_date}_{datetime.now().strftime('%H%M%S')}"


def list_history_reports(limit: int = 30) -> list[dict[str, Any]]:
    ensure_dirs()
    history: list[dict[str, Any]] = []
    for json_path in sorted(ARCHIVE_DATA_DIR.glob("daily_report_*.json"), reverse=True):
        try:
            report = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        items = report.get("items", [])
        history.append(
            {
                "name": json_path.name,
                "html_name": json_path.with_suffix(".html").name,
                "generated_at": report.get("generated_at", ""),
                "source_mode": report.get("source_mode", ""),
                "event_count": len(items),
                "top_titles": [item.get("title_cn") or item.get("title", "") for item in items[:3]],
            }
        )
        if len(history) >= limit:
            break
    return history


def load_report_snapshot(name: str) -> dict[str, Any] | None:
    if not name:
        return None
    safe_name = Path(name).name
    if safe_name != name or not safe_name.endswith(".json"):
        return None
    snapshot_path = ARCHIVE_DATA_DIR / safe_name
    if not snapshot_path.exists():
        return None
    try:
        return json.loads(snapshot_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _history_snapshot_iter() -> list[tuple[Path, dict[str, Any]]]:
    ensure_dirs()
    snapshots: list[tuple[Path, dict[str, Any]]] = []
    for json_path in sorted(ARCHIVE_DATA_DIR.glob("daily_report_*.json"), reverse=True):
        try:
            report = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        snapshots.append((json_path, report))
    return snapshots


def search_history_reports(query: str, limit: int = 20) -> list[dict[str, Any]]:
    needle = clean_text(query).lower()
    if not needle:
        return []
    results: list[dict[str, Any]] = []
    for json_path, report in _history_snapshot_iter():
        for item in report.get("items", []):
            haystack = " ".join(
                [
                    item.get("title", ""),
                    item.get("title_cn", ""),
                    item.get("summary_cn", ""),
                    item.get("original_summary_en", ""),
                    item.get("category", ""),
                    item.get("region", ""),
                    item.get("source_name", ""),
                ]
            ).lower()
            if needle not in haystack:
                continue
            results.append(
                {
                    "snapshot_name": json_path.name,
                    "snapshot_html_name": json_path.with_suffix(".html").name,
                    "generated_at": report.get("generated_at", ""),
                    "title": item.get("title", ""),
                    "title_cn": item.get("title_cn", ""),
                    "category": item.get("category", ""),
                    "region": item.get("region", ""),
                    "source_name": item.get("source_name", ""),
                    "event_date": item.get("event_date", ""),
                    "source_url": item.get("source_url", ""),
                }
            )
            if len(results) >= limit:
                return results
    return results


def build_trend_snapshot(limit: int = 60) -> dict[str, Any]:
    snapshots = _history_snapshot_iter()[:limit]
    category_counts: Counter[str] = Counter()
    region_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    keyword_counts: Counter[str] = Counter()
    daily_counts: list[dict[str, Any]] = []
    for _json_path, report in reversed(snapshots):
        items = report.get("items", [])
        daily_counts.append({"date": report.get("generated_at", ""), "event_count": len(items)})
        for item in items:
            category_counts[item.get("category", "综合")] += 1
            region_counts[item.get("region", "全球")] += 1
            source_counts[item.get("source_name", "unknown")] += 1
            title = f"{item.get('title', '')} {item.get('title_cn', '')}".lower()
            for token in re.findall(r"[a-z]{3,}", title):
                if token in TREND_STOPWORDS:
                    continue
                keyword_counts[token] += 1
    return {
        "snapshot_count": len(snapshots),
        "category_counts": [{"name": key, "count": value} for key, value in category_counts.most_common(6)],
        "region_counts": [{"name": key, "count": value} for key, value in region_counts.most_common(6)],
        "source_counts": [{"name": key, "count": value} for key, value in source_counts.most_common(6)],
        "keyword_counts": [{"name": key, "count": value} for key, value in keyword_counts.most_common(10)],
        "daily_counts": daily_counts[-10:],
    }


def load_translation_cache() -> dict[str, str]:
    if TRANSLATION_CACHE_PATH.exists():
        try:
            return json.loads(TRANSLATION_CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_translation_cache(cache: dict[str, str]) -> None:
    TRANSLATION_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def merge_dict(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config() -> dict[str, Any]:
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("r", encoding="utf-8") as fh:
            return merge_dict(DEFAULT_CONFIG, json.load(fh))
    with CONFIG_PATH.open("w", encoding="utf-8") as fh:
        json.dump(DEFAULT_CONFIG, fh, ensure_ascii=False, indent=2)
    return DEFAULT_CONFIG


def clean_text(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def contains_keyword(text: str, keyword: str) -> bool:
    lowered = text.lower()
    needle = keyword.lower().strip()
    if not needle:
        return False
    if re.fullmatch(r"[a-z0-9 .-]+", needle):
        pattern = r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])"
        return re.search(pattern, lowered) is not None
    return needle in lowered


def normalize_title(title: str) -> str:
    title = clean_text(title).lower()
    title = re.sub(r"[^a-z0-9\u4e00-\u9fff ]+", " ", title)
    return re.sub(r"\s+", " ", title).strip()


def categorize(text: str) -> str:
    best = "综合"
    best_score = 0
    for category, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for keyword in keywords if contains_keyword(text, keyword))
        if score > best_score:
            best = category
            best_score = score
    return best


def infer_region(text: str) -> str:
    best = "全球"
    best_score = 0
    for region, keywords in REGION_RULES.items():
        score = sum(1 for keyword in keywords if contains_keyword(text, keyword))
        if score > best_score:
            best = region
            best_score = score
    return best


def score_item(title: str, summary: str, source: str) -> int:
    combined = f"{title} {summary}"
    score = 1
    impact_words = [
        "global", "world", "election", "war", "tariff", "oil", "fed", "economy",
        "sanction", "summit", "ceasefire", "earthquake", "storm", "chip", "ai",
        "hormuz", "missile", "nuclear",
    ]
    score += sum(2 for word in impact_words if contains_keyword(combined, word))
    if source.lower().startswith(("reuters", "ap", "bbc")):
        score += 2
    if len(title) > 55:
        score += 1
    return score


def assess_significance(item: NewsItem) -> int:
    text = f"{item.title} {item.summary}".lower()
    score = item.score

    strategic_keywords = [
        "war", "missile", "nuclear", "ceasefire", "hormuz", "tariff", "sanction",
        "fed", "inflation", "interest rate", "oil", "gas", "earthquake", "summit",
    ]
    market_keywords = [
        "market", "bond", "currency", "trade", "shipping", "chip", "ai",
    ]
    leaders = ["trump", "president", "prime minister", "xi", "putin", "netanyahu"]

    score += sum(2 for word in strategic_keywords if contains_keyword(text, word))
    score += sum(1 for word in market_keywords if contains_keyword(text, word))
    score += sum(1 for word in leaders if contains_keyword(text, word))

    if item.category in {"地缘政治", "经济金融"}:
        score += 2
    if item.region in {"中东", "北美", "欧洲", "亚太"}:
        score += 1
    if item.source.lower().startswith(("reuters", "bbc", "ap", "npr", "dw", "the guardian")):
        score += 1

    if score >= 14:
        return 5
    if score >= 10:
        return 4
    if score >= 7:
        return 3
    if score >= 4:
        return 2
    return 1


def parse_date(value: str) -> str:
    if not value:
        return ""
    try:
        return parsedate_to_datetime(value).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return clean_text(value)


def fetch_url(url: str, timeout: int = 20, headers: dict[str, str] | None = None, data: bytes | None = None, method: str | None = None) -> str:
    base_headers = {"User-Agent": "Mozilla/5.0 global-news-agent/2.0"}
    if headers:
        base_headers.update(headers)
    request = urllib.request.Request(url, headers=base_headers, data=data, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="ignore")


def translate_text(text: str, cache: dict[str, str], mode: str = "auto") -> str:
    cleaned = clean_text(text)
    if not cleaned:
        return ""
    if any("\u4e00" <= char <= "\u9fff" for char in cleaned):
        return cleaned
    if cleaned in cache:
        return cache[cleaned]
    if mode == "off":
        return cleaned

    endpoints = [
        (
            "https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=zh-CN&dt=t&q="
            + urllib.parse.quote(cleaned),
            "google",
        ),
        (
            "https://api.mymemory.translated.net/get?q="
            + urllib.parse.quote(cleaned)
            + "&langpair=en|zh-CN",
            "mymemory",
        ),
    ]

    for url, kind in endpoints:
        try:
            raw = fetch_url(url, timeout=20)
            if kind == "google":
                parsed = json.loads(raw)
                translated = "".join(part[0] for part in parsed[0] if part and part[0]).strip()
            else:
                parsed = json.loads(raw)
                translated = clean_text(parsed.get("responseData", {}).get("translatedText", ""))
            if translated:
                cache[cleaned] = translated
                return translated
        except Exception:
            continue

    return cleaned


def polish_cn_title(text: str) -> str:
    value = clean_text(text)
    if not value:
        return ""
    value = re.sub(r"^中文标题[:：]\s*", "", value)
    value = re.sub(r"\s*\(([^()]*)\)", "", value)
    value = re.sub(r"\s+", " ", value).strip(" .;；，,")
    value = value.replace("直播：", "")
    value = value.replace("现场直播：", "")
    value = value.replace("直播", "")
    value = re.sub(r"\s+", " ", value).strip(" .;；，,")
    return value.strip()


def polish_cn_summary(text: str, original_title: str = "") -> str:
    value = clean_text(text)
    if not value:
        return polish_cn_title(original_title)

    value = re.sub(r"继续阅读[\.。…]*", "", value, flags=re.IGNORECASE).strip()
    value = re.sub(r"Continue reading[\.。…]*", "", value, flags=re.IGNORECASE).strip()
    value = re.sub(r"^我们了解[^，。:：]*[，。:：]\s*", "", value)
    value = re.sub(r"^最新消息[，。:：]\s*", "", value)
    value = re.sub(r"^直播[：:]\s*", "", value)
    value = re.sub(r"\s*\(([^()]*)\)", "", value)
    value = re.sub(r"\s+", " ", value).strip(" .;；，,")

    parts = [part.strip() for part in re.split(r"[。！？]", value) if part.strip()]
    dedup_parts: list[str] = []
    seen: set[str] = set()
    for part in parts:
        normalized = re.sub(r"\s+", "", part)
        if len(normalized) < 8:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        dedup_parts.append(part)
    if dedup_parts:
        value = "。".join(dedup_parts[:2]).strip(" .;；，,")
        if value and not re.search(r"[。！？]$", value):
            value += "。"

    segments = re.split(r"(?<=[。！？])\s+|\s{2,}", value)
    cleaned_segments: list[str] = []
    seen: set[str] = set()
    for segment in segments:
        segment = segment.strip(" ;；，,")
        if not segment:
            continue
        normalized = re.sub(r"\s+", "", segment)
        if normalized in seen:
            continue
        seen.add(normalized)
        cleaned_segments.append(segment)
        if len(cleaned_segments) >= 2:
            break

    value = " ".join(cleaned_segments) if cleaned_segments else value
    if len(value) > 88 and "。" in value:
        first_sentence = value.split("。", 1)[0].strip()
        if first_sentence:
            value = first_sentence + "。"
    value = value.strip()
    if not value:
        return polish_cn_title(original_title)
    return value


def normalize_report_item_text(item: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(item)
    normalized["title_cn"] = polish_cn_title(normalized.get("title_cn", "") or normalized.get("title", ""))
    normalized["summary_cn"] = polish_cn_summary(normalized.get("summary_cn", "") or normalized.get("title_cn", ""), normalized.get("title", ""))
    for field in [
        "impact_cn",
        "economic_impact_cn",
        "asset_impact_cn",
        "china_sector_impact_cn",
        "china_impact_cn",
        "market_impact_cn",
        "watchpoints_cn",
    ]:
        normalized[field] = clean_text(normalized.get(field, ""))
    return normalized


def parse_feed(feed_name: str, content: str, max_items: int) -> list[NewsItem]:
    root = ET.fromstring(content)
    items: list[NewsItem] = []
    if root.tag.endswith("feed"):
        ns = {"a": "http://www.w3.org/2005/Atom"}
        entries = root.findall("a:entry", ns)
        for entry in entries[:max_items]:
            title = clean_text(entry.findtext("a:title", default="", namespaces=ns))
            summary = clean_text(entry.findtext("a:summary", default="", namespaces=ns))
            published = clean_text(entry.findtext("a:updated", default="", namespaces=ns))
            link = ""
            link_node = entry.find("a:link", ns)
            if link_node is not None:
                link = link_node.attrib.get("href", "")
            combined = f"{title} {summary}"
            items.append(
                NewsItem(
                    title=title,
                    link=link,
                    source=feed_name,
                    published=parse_date(published),
                    summary=summary,
                    category=categorize(combined),
                    region=infer_region(combined),
                    score=score_item(title, summary, feed_name),
                )
            )
        return items

    channel = root.find("channel")
    if channel is None:
        return items
    for item in channel.findall("item")[:max_items]:
        title = clean_text(item.findtext("title", default=""))
        summary = clean_text(item.findtext("description", default=""))
        link = clean_text(item.findtext("link", default=""))
        published = parse_date(item.findtext("pubDate", default=""))
        combined = f"{title} {summary}"
        items.append(
            NewsItem(
                title=title,
                link=link,
                source=feed_name,
                published=published,
                summary=summary,
                category=categorize(combined),
                region=infer_region(combined),
                score=score_item(title, summary, feed_name),
            )
        )
    return items


def collect_news(config: dict[str, Any]) -> tuple[list[NewsItem], list[str]]:
    dedup: dict[str, NewsItem] = {}
    errors: list[str] = []
    for feed in config["rss_feeds"]:
        try:
            content = fetch_url(feed["url"])
            for item in parse_feed(feed["name"], content, config["max_items_per_feed"]):
                key = normalize_title(item.title)
                if not key:
                    continue
                existing = dedup.get(key)
                if existing is None or item.score > existing.score:
                    dedup[key] = item
        except (urllib.error.URLError, ET.ParseError, TimeoutError) as exc:
            errors.append(f"{feed['name']}: {exc}")
    ranked = sorted(dedup.values(), key=lambda item: (item.score, item.published, item.source), reverse=True)
    return ranked[: config["top_events"]], errors


def fallback_analysis(item: NewsItem, cache: dict[str, str], translation_mode: str) -> dict[str, str]:
    text = f"{item.title} {item.summary}".lower()
    has_energy = any(contains_keyword(text, word) for word in ["oil", "gas", "energy", "hormuz", "shipping"])
    has_policy = any(contains_keyword(text, word) for word in ["fed", "rate", "inflation", "tariff", "sanction", "policy", "shutdown"])
    has_tech = any(contains_keyword(text, word) for word in ["ai", "chip", "semiconductor", "cyber", "software", "data"])
    has_conflict = any(contains_keyword(text, word) for word in ["war", "missile", "military", "strike", "nuclear", "conflict"])
    has_consumption = any(contains_keyword(text, word) for word in ["airport", "travel", "consumer", "concert", "tourism"])

    if item.category == "地缘政治":
        impact_parts = ["事件会先影响区域安全预期。"]
        if has_energy:
            impact_parts.append("若波及能源运输，全球风险资产和通胀预期会一起受扰动。")
        else:
            impact_parts.append("后续要看是否外溢到制裁、航运或外交升级。")
        china_parts = ["中国层面主要看能源进口、航运安全和外交平衡。"]
        if item.region in {"中东", "欧洲"}:
            china_parts.append("若冲突持续，相关原材料和远洋链路的稳定性会更关键。")
        market_parts = ["市场通常先交易避险情绪。"]
        if has_energy:
            market_parts.append("原油、黄金与航运链条更容易成为第一反应资产。")
        else:
            market_parts.append("汇率、黄金和国防链弹性可能更明显。")
        economic_parts = ["宏观上要看能源、贸易和运价是否被重新定价。"]
        if has_policy:
            economic_parts.append("如果伴随制裁升级，外贸和资本流向也会受影响。")
        asset_parts = ["资产层面偏利多避险资产和上游资源。"]
        if has_conflict:
            asset_parts.append("航空、可选消费和高估值成长板块相对承压。")
        china_sector_parts = ["中国行业链条重点看油气、航运、化工和外贸制造。"]
        if has_tech:
            china_sector_parts.append("若牵涉技术限制，电子和通信链也要防二次冲击。")
    elif item.category == "经济金融":
        impact_parts = ["事件更容易改变利率预期、汇率走势和跨境资本流向。"]
        if has_energy:
            impact_parts.append("如果能源价格同步波动，全球通胀路径会更复杂。")
        china_parts = ["中国主要看外需、人民币汇率和政策对冲空间。"]
        if has_policy:
            china_parts.append("出口链和稳增长政策的节奏可能需要重新评估。")
        market_parts = ["股债汇商品会围绕政策预期重新定价。"]
        economic_parts = ["核心观察点是增长、通胀、利率和贸易条件是否同时发生变化。"]
        asset_parts = ["美元、美债、黄金、工业品和权益风格切换是主要交易线索。"]
        china_sector_parts = ["中国相关行业重点看出口制造、金融地产、大宗原材料和高股息资产。"]
    elif item.category == "科技产业":
        impact_parts = ["事件会先影响 AI、芯片、网络安全和关键供应链预期。"]
        if has_policy:
            impact_parts.append("若伴随监管或出口限制，全球科技链会更快重估。")
        china_parts = ["中国重点看技术管制、国产替代和产业链再配置。"]
        market_parts = ["科技股估值、半导体和算力链对消息面最敏感。"]
        economic_parts = ["宏观上传导到资本开支、生产率预期和科技投资周期。"]
        asset_parts = ["半导体、云计算、AI 应用与网络安全板块波动会更明显。"]
        china_sector_parts = ["中国受影响方向主要是算力、芯片设备、工业软件和国产替代链条。"]
    elif item.category == "气候灾害":
        impact_parts = ["事件会冲击局部供应链、物流和保险成本。"]
        if has_energy:
            impact_parts.append("若波及港口或能源产区，影响会明显放大。")
        china_parts = ["中国要看进口原料、航运时效和制造交付是否受牵连。"]
        market_parts = ["能源、航运、保险和公用事业相关资产更敏感。"]
        economic_parts = ["宏观影响通常体现为供给收缩、物流受阻和重建支出抬升。"]
        asset_parts = ["商品、航运、保险和公用事业板块更容易出现相对收益。"]
        china_sector_parts = ["相关产业链重点看上游原料、港口物流和制造排产。"]
    elif item.category == "公共卫生":
        impact_parts = ["事件会影响公共卫生政策、跨境流动和服务消费预期。"]
        china_parts = ["中国重点观察跨境流动、医疗物资和风险沟通节奏。"]
        market_parts = ["旅游、消费和医药板块容易出现分化交易。"]
        economic_parts = ["宏观上传导到服务消费恢复、劳动力供给和出行活动。"]
        asset_parts = ["医药、航空、酒店和可选消费更容易出现分化。"]
        china_sector_parts = ["中国相关方向主要是医疗供应链、出行消费和跨境商务活动。"]
    else:
        impact_parts = ["短期内重点看事件是否继续扩散到政策、贸易或市场层面。"]
        if has_consumption:
            impact_parts.append("如果影响居民出行或消费，服务业预期会更快反映。")
        china_parts = ["与中国的直接关联暂时有限，但要持续看贸易、舆情和外交层面变化。"]
        market_parts = ["市场初期更多受情绪驱动，后续取决于政策和基本面确认。"]
        economic_parts = ["宏观影响仍需观察是否演变为增长、成本或监管变量。"]
        asset_parts = ["资产价格会先做情绪定价，再看基本面是否跟进。"]
        china_sector_parts = ["对中国行业的传导还不清晰，先看供应链、贸易和监管信号。"]

    impact = " ".join(impact_parts)
    china_impact = " ".join(china_parts)
    market_impact = " ".join(market_parts)
    economic_impact = " ".join(economic_parts)
    asset_impact = " ".join(asset_parts)
    china_sector_impact = " ".join(china_sector_parts)

    watchpoints = []
    if any(contains_keyword(text, word) for word in ["oil", "gas", "hormuz", "sanction", "tariff"]):
        watchpoints.append("关注能源价格、航运路线和制裁措施是否升级。")
    if any(contains_keyword(text, word) for word in ["fed", "rate", "inflation", "jobs", "bond"]):
        watchpoints.append("关注后续数据和央行表态是否修正利率预期。")
    if any(contains_keyword(text, word) for word in ["chip", "ai", "cyber", "software"]):
        watchpoints.append("关注技术出口限制、企业财报与监管动作。")
    if not watchpoints:
        watchpoints.append("关注官方声明、二次传播和市场反馈。")

    significance = assess_significance(item)
    title_cn = polish_cn_title(translate_text(item.title, cache, translation_mode))
    summary_cn_raw = polish_cn_summary(translate_text(item.summary or item.title, cache, translation_mode), item.title)
    return {
        "title_cn": title_cn,
        "original_summary_en": item.summary or item.title,
        "summary_cn": summary_cn_raw if summary_cn_raw else polish_cn_title(item.title),
        "impact_cn": impact,
        "economic_impact_cn": economic_impact,
        "asset_impact_cn": asset_impact,
        "china_sector_impact_cn": china_sector_impact,
        "china_impact_cn": china_impact,
        "market_impact_cn": market_impact,
        "watchpoints_cn": " ".join(watchpoints),
        "significance": str(significance),
    }


def parse_response_output_text(raw: dict[str, Any]) -> str:
    output_text = raw.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    chunks: list[str] = []
    for item in raw.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            text_value = content.get("text")
            if isinstance(text_value, str):
                chunks.append(text_value)
    return "".join(chunks).strip()


def call_openai_responses(payload: dict[str, Any], timeout: int = 90) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    raw = fetch_url(
        "https://api.openai.com/v1/responses",
        timeout=timeout,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
    )
    return json.loads(raw)


def build_openai_report_payload(config: dict[str, Any]) -> dict[str, Any]:
    today = datetime.now().strftime("%Y-%m-%d")
    instructions = textwrap.dedent(
        f"""
        你是国际时政与宏观研究员。请搜索并筛选最近24小时内最重要的全球事件，
        生成适合中国用户阅读的中文日报。重点关注：
        1. 地缘冲突与外交升级
        2. 全球市场、利率、能源与贸易
        3. 科技产业、AI、芯片、网络安全
        4. 重大灾害和公共卫生

        输出必须符合 JSON Schema。
        要求：
        - 全部使用简体中文。
        - 只保留真正值得日报展示的 6 到 8 条事件。
        - significance 代表重要程度，5 为最高。
        - title 保留英文原始标题，title_cn 提供准确中文翻译。
        - original_summary_en 保留 1 到 3 句英文原文摘要。
        - event_date 尽量写成 YYYY-MM-DD 或 YYYY-MM-DD HH:MM。
        - source_name/source_url 必须对应可点击的新闻来源。
        - source_url 尽量使用权威媒体原始链接，不要使用二次聚合页。
        - executive_summary、china_brief、market_brief 都要简明具体，避免空话。
        - impact_cn 讲全球影响，economic_impact_cn 重点讲宏观经济与贸易，asset_impact_cn 讲资产价格与行业链条，china_sector_impact_cn 讲对中国行业影响。
        - watchlist 提供 3 到 5 条后续观察重点。
        - generated_at 使用 {today}。
        - source_mode 固定写 openai_web_search。
        """
    ).strip()

    return {
        "model": config["openai_model"],
        "reasoning": {"effort": config["openai_reasoning_effort"]},
        "tools": [
            {
                "type": "web_search",
                "user_location": {
                    "type": "approximate",
                    "country": "US",
                    "timezone": config["report_timezone"],
                },
            }
        ],
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": instructions}],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "请生成今天的全球大事日报，并突出对中国和全球市场的影响。",
                    }
                ],
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "global_news_report",
                "strict": True,
                "schema": OPENAI_REPORT_SCHEMA,
            }
        },
    }


def build_openai_analysis_payload(items: list[NewsItem], config: dict[str, Any]) -> dict[str, Any]:
    brief_items = [
        {
            "title": item.title,
            "summary": item.summary[:360],
            "source": item.source,
            "published": item.published,
            "category": item.category,
            "region": item.region,
            "score": item.score,
            "link": item.link,
        }
        for item in items
    ]
    instructions = textwrap.dedent(
        """
        你是国际新闻研究员。请基于输入新闻生成一份中文日报 JSON。
        不要杜撰不存在的事实，source_url 优先使用输入里的 link。
        保留英文原始标题 title，并提供中文翻译 title_cn。
        original_summary_en 保留英文原文摘要；summary_cn 提供中文翻译或准确中文概述。
        对经济相关事件，请细化宏观、资产、行业三个层面的影响。
        输出必须符合 JSON Schema，source_mode 固定写 rss_plus_openai。
        """
    ).strip()
    return {
        "model": config["openai_model"],
        "reasoning": {"effort": config["openai_reasoning_effort"]},
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": instructions}],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": json.dumps(brief_items, ensure_ascii=False)}],
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "global_news_report",
                "strict": True,
                "schema": OPENAI_REPORT_SCHEMA,
            }
        },
    }


def build_openai_rss_rewrite_payload(items: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    compact_items = []
    for idx, item in enumerate(items):
        compact_items.append(
            {
                "index": idx,
                "title": item.get("title", ""),
                "title_cn": item.get("title_cn", ""),
                "category": item.get("category", ""),
                "region": item.get("region", ""),
                "source_name": item.get("source_name", ""),
                "event_date": item.get("event_date", ""),
                "original_summary_en": item.get("original_summary_en", ""),
                "summary_cn": item.get("summary_cn", ""),
                "impact_cn": item.get("impact_cn", ""),
                "economic_impact_cn": item.get("economic_impact_cn", ""),
                "asset_impact_cn": item.get("asset_impact_cn", ""),
                "china_sector_impact_cn": item.get("china_sector_impact_cn", ""),
                "china_impact_cn": item.get("china_impact_cn", ""),
                "market_impact_cn": item.get("market_impact_cn", ""),
                "watchpoints_cn": item.get("watchpoints_cn", ""),
            }
        )

    prompt = textwrap.dedent(
        """
        你是中文财经与国际新闻编辑。请在不改动事实、不补充新事实的前提下，
        对给定 RSS 回退结果做轻量润色，目标是减少模板感和翻译腔。

        要求：
        - 输出必须符合 JSON Schema。
        - 只能改写指定字段，不要新增字段。
        - 保持每条 item 的 index 不变。
        - title_cn 要像自然中文标题，避免“中文标题：”这类字样。
        - summary_cn、impact_cn、economic_impact_cn、asset_impact_cn、china_sector_impact_cn、
          china_impact_cn、market_impact_cn、watchpoints_cn 都要更自然、更具体，但不能捏造信息。
        - 每个字段尽量 1 到 2 句，避免空话、套话和重复表述。
        - 如果原文信息不足，可以保守改写，但不要扩展到原文没有支持的判断。
        """
    ).strip()

    return {
        "model": config["openai_model"],
        "reasoning": {"effort": config["openai_reasoning_effort"]},
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": prompt}],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": json.dumps({"items": compact_items}, ensure_ascii=False)}],
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "rss_rewrite",
                "strict": True,
                "schema": OPENAI_RSS_REWRITE_SCHEMA,
            }
        },
    }


def maybe_rewrite_rss_items_with_openai(items: list[dict[str, Any]], config: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    if not items:
        return items, None
    if not config.get("openai_rss_rewrite_enabled", True):
        return items, None
    if not os.getenv("OPENAI_API_KEY"):
        return items, None
    try:
        payload = build_openai_rss_rewrite_payload(items, config)
        raw = call_openai_responses(payload, timeout=60)
        parsed = json.loads(parse_response_output_text(raw))
        rewritten = [dict(item) for item in items]
        for patch in parsed.get("items", []):
            idx = patch.get("index")
            if not isinstance(idx, int) or idx < 0 or idx >= len(rewritten):
                continue
            target = rewritten[idx]
            for field in [
                "title_cn",
                "summary_cn",
                "impact_cn",
                "economic_impact_cn",
                "asset_impact_cn",
                "china_sector_impact_cn",
                "china_impact_cn",
                "market_impact_cn",
                "watchpoints_cn",
            ]:
                value = clean_text(patch.get(field, ""))
                if value:
                    target[field] = value
        return rewritten, None
    except Exception as exc:
        return items, f"OpenAI 轻量润色未成功执行，已保留本地规则文案: {exc}"


def fetch_report_with_openai_web_search(config: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    warnings: list[str] = []
    if not os.getenv("OPENAI_API_KEY"):
        return None, warnings
    try:
        payload = build_openai_report_payload(config)
        raw = call_openai_responses(payload, timeout=120)
        parsed = json.loads(parse_response_output_text(raw))
        return parsed, warnings
    except Exception as exc:
        warnings.append(f"OpenAI web_search 未成功执行，已回退到 RSS 模式: {exc}")
        return None, warnings


def report_from_items(
    items: list[NewsItem],
    warnings: list[str],
    source_mode: str,
    translation_mode: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cache = load_translation_cache()
    enriched_items = []
    for item in items:
        analysis = fallback_analysis(item, cache, translation_mode)
        enriched_items.append(
            {
                "title": item.title,
                "title_cn": analysis["title_cn"],
                "category": item.category,
                "region": item.region,
                "significance": int(analysis["significance"]),
                "original_summary_en": analysis["original_summary_en"],
                "summary_cn": analysis["summary_cn"],
                "impact_cn": analysis["impact_cn"],
                "economic_impact_cn": analysis["economic_impact_cn"],
                "asset_impact_cn": analysis["asset_impact_cn"],
                "china_sector_impact_cn": analysis["china_sector_impact_cn"],
                "china_impact_cn": analysis["china_impact_cn"],
                "market_impact_cn": analysis["market_impact_cn"],
                "watchpoints_cn": analysis["watchpoints_cn"],
                "event_date": item.published or datetime.now().strftime("%Y-%m-%d"),
                "source_name": item.source,
                "source_url": item.link,
            }
        )

    if config:
        enriched_items, rewrite_warning = maybe_rewrite_rss_items_with_openai(enriched_items, config)
        if rewrite_warning:
            warnings = list(warnings)
            warnings.append(rewrite_warning)

    enriched_items = [normalize_report_item_text(item) for item in enriched_items]

    top_categories = Counter(item["category"] for item in enriched_items).most_common(3)
    top_regions = Counter(item["region"] for item in enriched_items).most_common(2)
    executive_summary = "今日全球重点集中在"
    executive_summary += "、".join(category for category, _ in top_categories) if top_categories else "多领域事件"
    executive_summary += "，需同时关注政策表态与市场定价。"
    china_brief = "中国相关观察重点在"
    china_brief += "、".join(region for region, _ in top_regions) if top_regions else "外部需求与供应链"
    china_brief += "的外溢影响。"
    market_brief = "市场层面优先留意能源、汇率、避险资产与科技板块的联动。"
    watchlist = [
        "主要经济体最新政策表态",
        "能源价格与航运扰动是否扩大",
        "全球股债汇是否出现二次定价",
        "科技与安全监管是否加码",
    ]
    if warnings:
        watchlist.append("关注新闻源缺口是否影响事件覆盖面")

    save_translation_cache(cache)

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d"),
        "source_mode": source_mode,
        "executive_summary": executive_summary,
        "china_brief": china_brief,
        "market_brief": market_brief,
        "watchlist": watchlist[:5],
        "items": enriched_items,
        "warnings": warnings,
    }


def maybe_upgrade_rss_report_with_openai(items: list[NewsItem], config: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    if not os.getenv("OPENAI_API_KEY"):
        return report_from_items(items, warnings, "rss_fallback", config.get("translation_mode", "auto"), config)
    try:
        payload = build_openai_analysis_payload(items, config)
        raw = call_openai_responses(payload, timeout=90)
        parsed = json.loads(parse_response_output_text(raw))
        parsed["warnings"] = warnings
        return parsed
    except Exception as exc:
        warnings = list(warnings)
        warnings.append(f"OpenAI 深度分析未成功执行，已使用本地规则分析: {exc}")
        return report_from_items(items, warnings, "rss_fallback", config.get("translation_mode", "auto"), config)


def build_report(config: dict[str, Any]) -> dict[str, Any]:
    warnings: list[str] = []
    mode = config["mode"].lower()
    if mode in {"auto", "openai_web_search"} and config.get("openai_web_search_enabled", True):
        report, openai_warnings = fetch_report_with_openai_web_search(config)
        warnings.extend(openai_warnings)
        if report:
            report["warnings"] = warnings + report.get("warnings", [])
            return report
        if mode == "openai_web_search":
            return {
                "generated_at": datetime.now().strftime("%Y-%m-%d"),
                "source_mode": "openai_web_search_failed",
                "executive_summary": "OpenAI 搜索模式执行失败。",
                "china_brief": "请检查 OPENAI_API_KEY、模型权限与网络连通性。",
                "market_brief": "当前未生成有效的市场影响分析。",
                "watchlist": ["检查 API Key", "检查网络权限", "确认模型可用"],
                "items": [],
                "warnings": warnings,
            }

    items, rss_errors = collect_news(config)
    warnings.extend(rss_errors)
    return maybe_upgrade_rss_report_with_openai(items, config, warnings)


def build_metrics(report: dict[str, Any]) -> dict[str, Any]:
    items = report.get("items", [])
    category_counts = Counter(item.get("category", "综合") for item in items)
    region_counts = Counter(item.get("region", "全球") for item in items)
    avg_significance = 0
    if items:
        avg_significance = round(sum(item.get("significance", 0) for item in items) / len(items), 1)
    top_category = category_counts.most_common(1)[0][0] if category_counts else "无"
    top_region = region_counts.most_common(1)[0][0] if region_counts else "无"
    return {
        "event_count": len(items),
        "avg_significance": avg_significance,
        "top_category": top_category,
        "top_region": top_region,
    }


def render_pills(values: Counter[str] | dict[str, int], css_class: str) -> str:
    return "".join(
        f'<button class="{css_class}" data-value="{html.escape(key)}">{html.escape(key)} <span>{value}</span></button>'
        for key, value in values.items()
    )


def build_plaintext_digest(report: dict[str, Any]) -> str:
    lines = [
        f"全球大事智能日报 | {report.get('generated_at', '')}",
        f"模式: {report.get('source_mode', '')}",
        "",
        f"总览: {report.get('executive_summary', '')}",
        f"中国视角: {report.get('china_brief', '')}",
        f"市场视角: {report.get('market_brief', '')}",
        "",
        "观察清单:",
    ]
    for point in report.get("watchlist", []):
        lines.append(f"- {point}")
    lines.append("")
    lines.append("重点事件:")
    for idx, item in enumerate(report.get("items", []), start=1):
        lines.append(f"{idx}. {item.get('title', '')}")
        lines.append(f"   中文: {item.get('title_cn', '')}")
        lines.append(f"   类别: {item.get('category', '')} | 区域: {item.get('region', '')} | 重要度: {item.get('significance', '')}/5")
        lines.append(f"   原文摘要: {item.get('original_summary_en', '')}")
        lines.append(f"   摘要: {item.get('summary_cn', '')}")
        lines.append(f"   宏观经济: {item.get('economic_impact_cn', '')}")
        lines.append(f"   资产影响: {item.get('asset_impact_cn', '')}")
        lines.append(f"   中国行业: {item.get('china_sector_impact_cn', '')}")
        lines.append(f"   对中国: {item.get('china_impact_cn', '')}")
        lines.append(f"   市场影响: {item.get('market_impact_cn', '')}")
        lines.append(f"   原文: {item.get('source_url', '')}")
    if report.get("warnings"):
        lines.append("")
        lines.append("告警:")
        for warning in report["warnings"]:
            lines.append(f"- {warning}")
    return "\n".join(lines)


def post_json(url: str, payload: dict[str, Any], timeout: int = 30) -> None:
    fetch_url(
        url,
        timeout=timeout,
        headers={"Content-Type": "application/json"},
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
    )


def send_email_notification(report: dict[str, Any], latest_path: Path, config: dict[str, Any]) -> str:
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "465"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    smtp_to = os.getenv("SMTP_TO")
    if not all([smtp_host, smtp_user, smtp_password, smtp_to]):
        raise RuntimeError("SMTP 环境变量不完整。需要 SMTP_HOST、SMTP_USER、SMTP_PASSWORD、SMTP_TO。")

    prefix = config.get("notification", {}).get("email_subject_prefix", "全球大事智能日报")
    subject = f"{prefix} {report.get('generated_at', '')}"
    body = build_plaintext_digest(report) + f"\n\n本地报告: {latest_path}"

    message = MIMEText(body, "plain", "utf-8")
    message["Subject"] = subject
    message["From"] = smtp_user
    message["To"] = smtp_to

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context) as server:
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_user, [addr.strip() for addr in smtp_to.split(",") if addr.strip()], message.as_string())
    return f"Email sent to {smtp_to}"


def send_webhook_notification(report: dict[str, Any], latest_path: Path) -> str:
    webhook_url = os.getenv("NEWS_WEBHOOK_URL")
    if not webhook_url:
        raise RuntimeError("NEWS_WEBHOOK_URL 未设置。")
    payload = {
        "title": f"全球大事智能日报 {report.get('generated_at', '')}",
        "summary": report.get("executive_summary", ""),
        "china_brief": report.get("china_brief", ""),
        "market_brief": report.get("market_brief", ""),
        "watchlist": report.get("watchlist", []),
        "items": report.get("items", []),
        "warnings": report.get("warnings", []),
        "local_report_path": str(latest_path),
    }
    post_json(webhook_url, payload)
    return f"Webhook posted to {webhook_url}"


def send_chat_webhook_notification(report: dict[str, Any], latest_path: Path) -> str:
    webhook_url = os.getenv("CHAT_WEBHOOK_URL")
    webhook_kind = os.getenv("CHAT_WEBHOOK_KIND", "generic").lower()
    if not webhook_url:
        raise RuntimeError("CHAT_WEBHOOK_URL 未设置。")

    top_items = report.get("items", [])[:5]
    lines = [
        f"全球大事智能日报 {report.get('generated_at', '')}",
        report.get("executive_summary", ""),
        "",
    ]
    for idx, item in enumerate(top_items, start=1):
        lines.append(f"{idx}. {item.get('title_cn', '')}")
        lines.append(f"原文: {item.get('title', '')}")
        lines.append(f"宏观: {item.get('economic_impact_cn', '')}")
        lines.append(f"市场: {item.get('asset_impact_cn', '')}")
        lines.append(f"链接: {item.get('source_url', '')}")
        lines.append("")
    lines.append(f"本地报告: {latest_path}")
    text = "\n".join(lines)

    if webhook_kind == "feishu":
        payload = {"msg_type": "text", "content": {"text": text}}
    elif webhook_kind == "wecom":
        payload = {"msgtype": "text", "text": {"content": text}}
    elif webhook_kind == "dingtalk":
        payload = {"msgtype": "text", "text": {"content": text}}
    else:
        payload = {"text": text, "report": report, "local_report_path": str(latest_path)}
    post_json(webhook_url, payload)
    return f"Chat webhook posted to {webhook_url}"


def send_notifications(report: dict[str, Any], latest_path: Path, config: dict[str, Any]) -> list[str]:
    messages: list[str] = []
    notification_config = config.get("notification", {})
    if notification_config.get("email_enabled"):
        messages.append(send_email_notification(report, latest_path, config))
    if notification_config.get("webhook_enabled"):
        messages.append(send_webhook_notification(report, latest_path))
    if notification_config.get("chat_webhook_enabled"):
        messages.append(send_chat_webhook_notification(report, latest_path))
    return messages


def build_html(report: dict[str, Any]) -> str:
    date_str = report.get("generated_at", datetime.now().strftime("%Y-%m-%d"))
    warnings = report.get("warnings", [])
    items = report.get("items", [])
    metrics = build_metrics(report)
    category_counts = Counter(item.get("category", "综合") for item in items)
    region_counts = Counter(item.get("region", "全球") for item in items)
    category_filters = render_pills(category_counts, "filter filter-category")
    region_filters = render_pills(region_counts, "filter filter-region")

    timeline_html = []
    ordered_items = sorted(items, key=lambda entry: (entry.get("event_date", ""), entry.get("significance", 0)), reverse=True)
    for idx, item in enumerate(ordered_items, start=1):
        stars = "★" * int(item.get("significance", 1))
        timeline_html.append(
            f"""
            <article class="card news-card" data-category="{html.escape(item.get('category', '综合'))}" data-region="{html.escape(item.get('region', '全球'))}">
              <div class="card-top">
                <div>
                  <div class="eyebrow">#{idx:02d} | {html.escape(item.get('event_date', ''))}</div>
                  <h2>{html.escape(item.get('title_cn', ''))}</h2>
                  <div class="original-title">{html.escape(item.get('title', ''))}</div>
                </div>
                <div class="score">
                  <span>{stars}</span>
                  <small>重要度 {item.get('significance', 1)}/5</small>
                </div>
              </div>
              <div class="meta-row">
                <span class="tag">{html.escape(item.get('category', '综合'))}</span>
                <span class="tag alt">{html.escape(item.get('region', '全球'))}</span>
                <span class="source">{html.escape(item.get('source_name', ''))}</span>
              </div>
              <div class="original-summary">
                <div class="section-label">英文原文摘要</div>
                <p>{html.escape(item.get('original_summary_en', ''))}</p>
              </div>
              <p><strong>事件摘要</strong>{html.escape(item.get('summary_cn', ''))}</p>
              <p><strong>全球影响</strong>{html.escape(item.get('impact_cn', ''))}</p>
              <p><strong>宏观经济</strong>{html.escape(item.get('economic_impact_cn', ''))}</p>
              <p><strong>资产价格</strong>{html.escape(item.get('asset_impact_cn', ''))}</p>
              <p><strong>中国行业</strong>{html.escape(item.get('china_sector_impact_cn', ''))}</p>
              <p><strong>对中国</strong>{html.escape(item.get('china_impact_cn', ''))}</p>
              <p><strong>市场影响</strong>{html.escape(item.get('market_impact_cn', ''))}</p>
              <p><strong>后续观察</strong>{html.escape(item.get('watchpoints_cn', ''))}</p>
              <div class="link-row">
                <a class="read-more" href="{html.escape(item.get('source_url', ''))}" target="_blank" rel="noreferrer">权威原帖</a>
              </div>
            </article>
            """.strip()
        )

    watch_html = "".join(f"<li>{html.escape(point)}</li>" for point in report.get("watchlist", []))
    warning_html = ""
    if warnings:
        warning_html = "<section class='warning-box'><h3>抓取/分析告警</h3><ul>"
        warning_html += "".join(f"<li>{html.escape(text)}</li>" for text in warnings)
        warning_html += "</ul></section>"

    major_html = "".join(
        f'<div class="brief-chip"><span>{html.escape(item.get("category", "综合"))}</span><strong>{html.escape(item.get("title_cn", ""))}</strong></div>'
        for item in ordered_items[:4]
    )

    footer_meta = html.escape(
        json.dumps(
            {
                "generated_at": report.get("generated_at"),
                "source_mode": report.get("source_mode"),
                "event_count": metrics["event_count"],
                "avg_significance": metrics["avg_significance"],
                "top_category": metrics["top_category"],
                "top_region": metrics["top_region"],
            },
            ensure_ascii=False,
        )
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="theme-color" content="#17202b">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <title>全球大事智能日报 - {html.escape(date_str)}</title>
  <link rel="manifest" href="/manifest.webmanifest">
  <style>
    :root {{
      --bg: #e9e0d0;
      --paper: #fffaf2;
      --ink: #17202b;
      --muted: #5b6472;
      --line: rgba(23,32,43,0.12);
      --accent: #b14a22;
      --accent-2: #1f5c4d;
      --card-shadow: 0 22px 44px rgba(49, 31, 13, 0.09);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
      background:
        radial-gradient(circle at top right, rgba(177,74,34,0.12), transparent 28%),
        radial-gradient(circle at left 20%, rgba(31,92,77,0.12), transparent 26%),
        linear-gradient(180deg, #f1e4cf 0%, var(--bg) 44%, #efe7db 100%);
    }}
    .page {{ width: min(1220px, calc(100% - 28px)); margin: 0 auto; padding: 28px 0 48px; }}
    .hero {{
      display: grid;
      gap: 18px;
      grid-template-columns: 1.3fr 0.9fr;
      background: linear-gradient(135deg, rgba(23,32,43,0.97), rgba(57,37,25,0.93));
      color: white;
      border-radius: 28px;
      padding: 28px;
      box-shadow: var(--card-shadow);
    }}
    .hero h1 {{ margin: 8px 0 12px; font-size: clamp(30px, 5vw, 56px); line-height: 1.02; letter-spacing: 1px; }}
    .hero p {{ margin: 8px 0; color: rgba(255,255,255,0.82); line-height: 1.72; }}
    .mode {{ display: inline-flex; gap: 8px; align-items: center; background: rgba(255,255,255,0.12); border: 1px solid rgba(255,255,255,0.14); padding: 8px 12px; border-radius: 999px; font-size: 13px; }}
    .metric-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }}
    .metric {{ background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.1); border-radius: 18px; padding: 14px; }}
    .metric .label {{ color: rgba(255,255,255,0.65); font-size: 13px; }}
    .metric .value {{ margin-top: 6px; font-size: 28px; font-weight: 700; }}
    .summary-grid {{ margin-top: 20px; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }}
    .brief-strip {{ margin-top: 18px; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }}
    .brief-chip {{ background: rgba(255,250,242,0.82); border: 1px solid var(--line); border-radius: 18px; padding: 14px; box-shadow: var(--card-shadow); }}
    .brief-chip span {{ display: inline-block; font-size: 12px; color: var(--accent); margin-bottom: 8px; }}
    .brief-chip strong {{ display: block; line-height: 1.55; }}
    .panel {{ background: var(--paper); border: 1px solid var(--line); border-radius: 22px; padding: 18px; box-shadow: var(--card-shadow); }}
    .panel h3 {{ margin: 0 0 12px; font-size: 16px; color: var(--accent); }}
    .panel p, .panel li {{ margin: 0; line-height: 1.74; }}
    .panel ul {{ padding-left: 18px; margin: 0; }}
    .history-strip {{ margin-top: 20px; }}
    .history-head {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }}
    .history-list {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }}
    .history-item {{ display: block; text-decoration: none; color: var(--ink); background: white; border: 1px solid var(--line); border-radius: 18px; padding: 14px; }}
    .history-item strong {{ display: block; margin-bottom: 6px; color: var(--accent); }}
    .history-item span {{ display: block; color: var(--muted); font-size: 13px; line-height: 1.6; }}
    .history-empty {{ color: var(--muted); font-size: 14px; }}
    .insight-grid {{ margin-top: 20px; display: grid; grid-template-columns: 1.1fr 0.9fr; gap: 16px; }}
    .search-box {{ display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }}
    .search-box input {{ flex: 1 1 220px; border: 1px solid var(--line); border-radius: 14px; padding: 11px 12px; background: white; color: var(--ink); }}
    .mini-list {{ display: grid; gap: 10px; }}
    .mini-item {{ border: 1px solid var(--line); border-radius: 16px; padding: 12px; background: rgba(255,255,255,0.8); }}
    .mini-item strong {{ display: block; margin-bottom: 6px; color: var(--accent); }}
    .mini-item span {{ display: block; color: var(--muted); font-size: 13px; line-height: 1.6; }}
    .trend-group {{ margin-bottom: 14px; }}
    .trend-group h4 {{ margin: 0 0 8px; font-size: 14px; color: var(--accent); }}
    .trend-chips {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .trend-chip {{ display: inline-flex; gap: 6px; align-items: center; padding: 7px 10px; border-radius: 999px; background: white; border: 1px solid var(--line); font-size: 13px; }}
    .trend-chip span {{ color: var(--muted); }}
    .toolbar {{ margin-top: 20px; background: rgba(255,250,242,0.75); border: 1px solid var(--line); border-radius: 22px; padding: 16px 18px; backdrop-filter: blur(12px); position: sticky; top: 12px; z-index: 10; }}
    .toolbar h3 {{ margin: 0 0 10px; font-size: 15px; }}
    .toolbar-head {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }}
    .toolbar-actions {{ display: flex; gap: 10px; flex-wrap: wrap; }}
    .action-btn {{ border: 1px solid var(--line); background: #17202b; color: white; border-radius: 999px; padding: 9px 14px; cursor: pointer; font-size: 13px; }}
    .action-btn.secondary {{ background: white; color: var(--ink); }}
    .filter-row {{ display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 12px; }}
    .filter {{ border: 1px solid var(--line); background: white; color: var(--ink); border-radius: 999px; padding: 8px 12px; cursor: pointer; font-size: 13px; }}
    .filter.active {{ background: var(--accent); color: white; border-color: transparent; }}
    .filter span {{ opacity: .66; margin-left: 4px; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 18px; margin-top: 20px; }}
    .news-card {{ background: linear-gradient(180deg, var(--paper) 0%, #fffcf8 100%); border: 1px solid var(--line); border-radius: 24px; padding: 20px; box-shadow: var(--card-shadow); }}
    .card-top {{ display: flex; gap: 12px; justify-content: space-between; align-items: start; }}
    .eyebrow {{ font-size: 12px; letter-spacing: 1px; color: var(--muted); text-transform: uppercase; }}
    .news-card h2 {{ margin: 8px 0 0; font-size: 24px; line-height: 1.3; }}
    .original-title {{ margin-top: 8px; color: var(--muted); font-size: 14px; line-height: 1.55; }}
    .score {{ min-width: 92px; text-align: right; color: var(--accent); font-weight: 700; }}
    .score small {{ display: block; color: var(--muted); margin-top: 4px; font-weight: 400; }}
    .meta-row {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 14px 0; }}
    .tag {{ padding: 6px 10px; border-radius: 999px; background: #f4dfcf; color: var(--accent); font-size: 12px; }}
    .tag.alt {{ background: #dcece7; color: var(--accent-2); }}
    .source {{ align-self: center; color: var(--muted); font-size: 13px; }}
    .news-card p {{ line-height: 1.74; margin: 10px 0; }}
    .news-card strong {{ display: inline-block; min-width: 72px; color: var(--accent); }}
    .original-summary {{ padding: 12px 14px; background: rgba(23,32,43,0.04); border-radius: 16px; margin: 12px 0; }}
    .section-label {{ font-size: 12px; letter-spacing: .8px; color: var(--muted); text-transform: uppercase; }}
    .link-row {{ display: flex; gap: 12px; flex-wrap: wrap; margin-top: 10px; }}
    .read-more {{ display: inline-block; margin-top: 8px; color: var(--accent); text-decoration: none; font-weight: 700; }}
    .warning-box {{ margin-top: 20px; padding: 18px; border: 1px solid rgba(177,74,34,0.24); background: rgba(177,74,34,0.08); border-radius: 20px; }}
    .warning-box h3 {{ margin: 0 0 10px; color: var(--accent); }}
    .empty {{ display: none; margin-top: 18px; padding: 18px; border-radius: 20px; background: rgba(31,92,77,0.08); border: 1px solid rgba(31,92,77,0.2); }}
    footer {{ margin-top: 18px; color: var(--muted); font-size: 13px; }}
    @media (max-width: 980px) {{ .hero, .summary-grid, .brief-strip {{ grid-template-columns: 1fr; }} }}
    @media (max-width: 640px) {{
      .page {{ width: min(100%, calc(100% - 20px)); }}
      .cards {{ grid-template-columns: 1fr; }}
      .news-card h2 {{ font-size: 21px; }}
    }}
    @media (max-width: 980px) {{ .insight-grid {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <div>
        <div class="mode">GLOBAL INTELLIGENCE | {html.escape(report.get("source_mode", "unknown"))}</div>
        <h1>全球大事智能日报</h1>
        <p>{html.escape(date_str)} 自动生成。面向中文用户，聚焦全球事件本身、对中国的外溢影响，以及市场层面的短期定价线索。</p>
        <p>{html.escape(report.get("executive_summary", ""))}</p>
      </div>
      <div class="metric-grid">
        <div class="metric"><div class="label">事件数量</div><div class="value">{metrics['event_count']}</div></div>
        <div class="metric"><div class="label">平均重要度</div><div class="value">{metrics['avg_significance']}</div></div>
        <div class="metric"><div class="label">主导类别</div><div class="value">{html.escape(metrics['top_category'])}</div></div>
        <div class="metric"><div class="label">主导区域</div><div class="value">{html.escape(metrics['top_region'])}</div></div>
      </div>
    </section>
    <section class="brief-strip">{major_html}</section>
    <section class="summary-grid">
      <article class="panel"><h3>中国视角</h3><p>{html.escape(report.get("china_brief", ""))}</p></article>
      <article class="panel"><h3>市场视角</h3><p>{html.escape(report.get("market_brief", ""))}</p></article>
      <article class="panel"><h3>观察清单</h3><ul>{watch_html}</ul></article>
    </section>
    <section class="panel history-strip">
      <div class="history-head">
        <h3>历史归档</h3>
        <span class="history-empty" id="historyStatus">正在加载最近生成记录...</span>
      </div>
      <div class="history-list" id="historyList"></div>
    </section>
    <section class="insight-grid">
      <section class="panel">
        <h3>历史搜索</h3>
        <div class="search-box">
          <input id="searchInput" type="search" placeholder="搜索历史标题、摘要、来源，例如 Iran / 芯片 / 美联储">
          <button class="action-btn secondary" id="searchBtn" type="button">搜索</button>
        </div>
        <div class="mini-list" id="searchResults">
          <div class="history-empty">输入关键词后可回看历史事件快照。</div>
        </div>
      </section>
      <section class="panel">
        <h3>趋势看板</h3>
        <div class="mini-list" id="trendBoard">
          <div class="history-empty">正在汇总历史类别、区域和高频主题...</div>
        </div>
      </section>
    </section>
    <section class="toolbar">
      <div class="toolbar-head">
        <h3>筛选事件</h3>
        <div class="toolbar-actions">
          <button class="action-btn" id="refreshBtn" type="button">重新生成</button>
          <button class="action-btn secondary" id="installBtn" type="button" hidden>安装到桌面</button>
        </div>
      </div>
      <div class="filter-row"><button class="filter active" data-kind="all" data-value="全部">全部</button>{category_filters}</div>
      <div class="filter-row"><button class="filter active" data-kind="region-all" data-value="全部区域">全部区域</button>{region_filters}</div>
    </section>
    <section class="cards" id="cards">{"".join(timeline_html)}</section>
    <section class="empty" id="empty">当前筛选条件下没有事件。</section>
    {warning_html}
    <footer>数据摘要：{footer_meta}</footer>
  </main>
  <script>
    (() => {{
      const cards = [...document.querySelectorAll('.news-card')];
      const empty = document.getElementById('empty');
      const refreshBtn = document.getElementById('refreshBtn');
      const installBtn = document.getElementById('installBtn');
      const historyList = document.getElementById('historyList');
      const historyStatus = document.getElementById('historyStatus');
      const searchInput = document.getElementById('searchInput');
      const searchBtn = document.getElementById('searchBtn');
      const searchResults = document.getElementById('searchResults');
      const trendBoard = document.getElementById('trendBoard');
      let category = '全部';
      let region = '全部';
      let deferredPrompt = null;
      const renderTrendGroup = (title, values) => {{
        if (!values || !values.length) return '';
        return `
          <div class="trend-group">
            <h4>${{title}}</h4>
            <div class="trend-chips">
              ${{values.map((item) => `<div class="trend-chip">${{item.name}} <span>${{item.count}}</span></div>`).join('')}}
            </div>
          </div>
        `;
      }};
      const renderHistory = async () => {{
        if (!historyList || !historyStatus) return;
        try {{
          const response = await fetch('/api/history');
          if (!response.ok) throw new Error('history failed');
          const snapshots = await response.json();
          historyList.innerHTML = '';
          if (!snapshots.length) {{
            historyStatus.textContent = '还没有历史归档，先生成一次日报。';
            return;
          }}
          historyStatus.textContent = '点击可打开对应时间点的归档页面。';
          snapshots.forEach((snapshot) => {{
            const link = document.createElement('a');
            link.className = 'history-item';
            link.href = `/archive/${{encodeURIComponent(snapshot.html_name)}}`;
            link.innerHTML = `
              <strong>${{snapshot.generated_at || '未命名快照'}}</strong>
              <span>模式: ${{snapshot.source_mode || 'unknown'}}</span>
              <span>事件数: ${{snapshot.event_count || 0}}</span>
              <span>${{(snapshot.top_titles || []).slice(0, 2).join(' / ') || '无摘要'}}</span>
            `;
            historyList.appendChild(link);
          }});
        }} catch (error) {{
          historyStatus.textContent = '历史归档加载失败。';
        }}
      }};
      const runSearch = async () => {{
        if (!searchResults || !searchInput) return;
        const q = searchInput.value.trim();
        if (!q) {{
          searchResults.innerHTML = '<div class="history-empty">输入关键词后可回看历史事件快照。</div>';
          return;
        }}
        searchResults.innerHTML = '<div class="history-empty">搜索中...</div>';
        try {{
          const response = await fetch(`/api/search?q=${{encodeURIComponent(q)}}`);
          if (!response.ok) throw new Error('search failed');
          const results = await response.json();
          if (!results.length) {{
            searchResults.innerHTML = '<div class="history-empty">没有匹配到历史事件。</div>';
            return;
          }}
          searchResults.innerHTML = results.map((item) => `
            <a class="mini-item" href="/archive/${{encodeURIComponent(item.snapshot_html_name)}}" style="text-decoration:none;color:inherit;">
              <strong>${{item.title_cn || item.title}}</strong>
              <span>${{item.generated_at}} | ${{item.category}} | ${{item.region}} | ${{item.source_name}}</span>
              <span>${{item.title}}</span>
            </a>
          `).join('');
        }} catch (error) {{
          searchResults.innerHTML = '<div class="history-empty">历史搜索失败。</div>';
        }}
      }};
      const renderTrends = async () => {{
        if (!trendBoard) return;
        try {{
          const response = await fetch('/api/trends');
          if (!response.ok) throw new Error('trend failed');
          const data = await response.json();
          const daily = (data.daily_counts || []).map((item) => `<div class="trend-chip">${{item.date}} <span>${{item.event_count}}</span></div>`).join('');
          trendBoard.innerHTML = `
            <div class="mini-item">
              <strong>已归档快照 ${{data.snapshot_count || 0}} 份</strong>
              <span>基于历史快照汇总最近的事件类别、区域、来源和英文高频主题。</span>
            </div>
            ${{renderTrendGroup('高频类别', data.category_counts)}}
            ${{renderTrendGroup('高频区域', data.region_counts)}}
            ${{renderTrendGroup('高频来源', data.source_counts)}}
            ${{renderTrendGroup('英文主题词', data.keyword_counts)}}
            <div class="trend-group">
              <h4>最近日报事件数</h4>
              <div class="trend-chips">${{daily || '<div class="history-empty">暂无历史数据。</div>'}}</div>
            </div>
          `;
        }} catch (error) {{
          trendBoard.innerHTML = '<div class="history-empty">趋势汇总失败。</div>';
        }}
      }};
      const sync = () => {{
        let shown = 0;
        cards.forEach((card) => {{
          const hitCategory = category === '全部' || card.dataset.category === category;
          const hitRegion = region === '全部' || card.dataset.region === region;
          const visible = hitCategory && hitRegion;
          card.style.display = visible ? '' : 'none';
          if (visible) shown += 1;
        }});
        empty.style.display = shown ? 'none' : 'block';
      }};
      document.querySelectorAll('.filter').forEach((button) => {{
        button.addEventListener('click', () => {{
          const row = button.parentElement;
          row.querySelectorAll('.filter').forEach((node) => node.classList.remove('active'));
          button.classList.add('active');
          if (button.classList.contains('filter-category') || button.dataset.kind === 'all') {{
            category = button.dataset.value === '全部' ? '全部' : button.dataset.value;
          }} else {{
            region = button.dataset.value === '全部区域' ? '全部' : button.dataset.value;
          }}
          sync();
        }});
      }});
      if (refreshBtn) {{
        refreshBtn.addEventListener('click', async () => {{
          refreshBtn.disabled = true;
          refreshBtn.textContent = '生成中...';
          try {{
            await fetch('/api/generate');
            window.location.reload();
          }} catch (error) {{
            refreshBtn.textContent = '生成失败';
            setTimeout(() => {{
              refreshBtn.disabled = false;
              refreshBtn.textContent = '重新生成';
            }}, 1500);
          }}
        }});
      }}
      window.addEventListener('beforeinstallprompt', (event) => {{
        event.preventDefault();
        deferredPrompt = event;
        if (installBtn) installBtn.hidden = false;
      }});
      if (installBtn) {{
        installBtn.addEventListener('click', async () => {{
          if (!deferredPrompt) return;
          deferredPrompt.prompt();
          await deferredPrompt.userChoice;
          deferredPrompt = null;
          installBtn.hidden = true;
        }});
      }}
      if ('serviceWorker' in navigator) {{
        navigator.serviceWorker.register('/sw.js').catch(() => null);
      }}
      if (searchBtn) searchBtn.addEventListener('click', runSearch);
      if (searchInput) {{
        searchInput.addEventListener('keydown', (event) => {{
          if (event.key === 'Enter') runSearch();
        }});
      }}
      renderHistory();
      renderTrends();
      sync();
    }})();
  </script>
</body>
</html>
"""


def save_outputs(report: dict[str, Any]) -> tuple[Path, Path]:
    date_key = report.get("generated_at", datetime.now().strftime("%Y-%m-%d"))
    report_path = OUTPUT_DIR / f"daily_report_{date_key}.html"
    latest_path = OUTPUT_DIR / "latest.html"
    json_path = DATA_DIR / f"daily_report_{date_key}.json"
    latest_json_path = DATA_DIR / "latest.json"
    archive_stamp = build_archive_stamp(report)
    archive_report_path = ARCHIVE_OUTPUT_DIR / f"daily_report_{archive_stamp}.html"
    archive_json_path = ARCHIVE_DATA_DIR / f"daily_report_{archive_stamp}.json"

    html_content = build_html(report)
    report_path.write_text(html_content, encoding="utf-8")
    latest_path.write_text(html_content, encoding="utf-8")
    archive_report_path.write_text(html_content, encoding="utf-8")
    json_payload = json.dumps(report, ensure_ascii=False, indent=2)
    json_path.write_text(json_payload, encoding="utf-8")
    latest_json_path.write_text(json_payload, encoding="utf-8")
    archive_json_path.write_text(json_payload, encoding="utf-8")
    return report_path, latest_path


def main() -> None:
    ensure_dirs()
    config = load_config()
    report = build_report(config)
    report_path, latest_path = save_outputs(report)
    notifications: list[str] = []
    try:
        notifications = send_notifications(report, latest_path, config)
    except Exception as exc:
        report.setdefault("warnings", []).append(f"通知发送失败: {exc}")
        report_path, latest_path = save_outputs(report)
    print(f"HTML report: {report_path}")
    print(f"Latest report: {latest_path}")
    print(f"Items: {len(report.get('items', []))}")
    print(f"Mode: {report.get('source_mode')}")
    for note in notifications:
        print(note)
    if report.get("warnings"):
        print("Warnings:")
        for warning in report["warnings"]:
            print(f"- {warning}")


if __name__ == "__main__":
    main()
