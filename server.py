import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import agent


HOST = os.getenv("NEWS_AGENT_HOST", "0.0.0.0")
PORT = int(os.getenv("NEWS_AGENT_PORT", "8008"))
ROOT = Path(__file__).resolve().parent

MANIFEST = {
    "name": "Global News Agent",
    "short_name": "NewsAgent",
    "start_url": "/",
    "display": "standalone",
    "background_color": "#e9e0d0",
    "theme_color": "#17202b",
    "lang": "zh-CN",
    "description": "全球大事智能日报",
}

SERVICE_WORKER = """
self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;
  event.respondWith(fetch(event.request).catch(() => caches.match('/')));
});
""".strip()


class DashboardHandler(BaseHTTPRequestHandler):
    def _send_text(self, body: str, content_type: str = "text/html; charset=utf-8", status: int = 200) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_bytes(self, data: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            latest = ROOT / "reports" / "latest.html"
            if not latest.exists():
                self._generate_report()
            self._send_bytes(latest.read_bytes(), "text/html; charset=utf-8")
            return

        if parsed.path == "/manifest.webmanifest":
            self._send_text(json.dumps(MANIFEST, ensure_ascii=False), "application/manifest+json; charset=utf-8")
            return

        if parsed.path == "/sw.js":
            self._send_text(SERVICE_WORKER, "application/javascript; charset=utf-8")
            return

        if parsed.path == "/api/report":
            latest_json = ROOT / "data" / "latest.json"
            query = parse_qs(parsed.query)
            snapshot_name = query.get("name", [""])[0].strip()
            if snapshot_name:
                snapshot = agent.load_report_snapshot(snapshot_name)
                if snapshot is None:
                    self._send_text("Not Found", "text/plain; charset=utf-8", status=HTTPStatus.NOT_FOUND)
                    return
                self._send_text(json.dumps(snapshot, ensure_ascii=False), "application/json; charset=utf-8")
                return
            if not latest_json.exists():
                self._generate_report()
            self._send_bytes(latest_json.read_bytes(), "application/json; charset=utf-8")
            return

        if parsed.path == "/api/history":
            payload = agent.list_history_reports(limit=24)
            self._send_text(json.dumps(payload, ensure_ascii=False), "application/json; charset=utf-8")
            return

        if parsed.path == "/api/search":
            query = parse_qs(parsed.query)
            keyword = query.get("q", [""])[0]
            payload = agent.search_history_reports(keyword, limit=30)
            self._send_text(json.dumps(payload, ensure_ascii=False), "application/json; charset=utf-8")
            return

        if parsed.path == "/api/trends":
            payload = agent.build_trend_snapshot(limit=90)
            self._send_text(json.dumps(payload, ensure_ascii=False), "application/json; charset=utf-8")
            return

        if parsed.path.startswith("/archive/"):
            archive_name = Path(parsed.path.removeprefix("/archive/")).name
            archive_path = ROOT / "reports" / "archive" / archive_name
            if not archive_name.endswith(".html") or not archive_path.exists():
                self._send_text("Not Found", "text/plain; charset=utf-8", status=HTTPStatus.NOT_FOUND)
                return
            self._send_bytes(archive_path.read_bytes(), "text/html; charset=utf-8")
            return

        if parsed.path == "/api/generate":
            query = parse_qs(parsed.query)
            should_open = query.get("open", ["0"])[0] == "1"
            report_path = self._generate_report()
            payload = {
                "ok": True,
                "report_path": str(report_path),
                "open": should_open,
            }
            self._send_text(json.dumps(payload, ensure_ascii=False), "application/json; charset=utf-8")
            return

        self._send_text("Not Found", "text/plain; charset=utf-8", status=HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args) -> None:
        return

    def _generate_report(self) -> Path:
        agent.ensure_dirs()
        config = agent.load_config()
        report = agent.build_report(config)
        report_path, latest_path = agent.save_outputs(report)
        try:
            agent.send_notifications(report, latest_path, config)
        except Exception:
            pass
        return latest_path


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), DashboardHandler)
    print(f"Dashboard running at http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
