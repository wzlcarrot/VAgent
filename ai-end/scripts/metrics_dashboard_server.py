#!/usr/bin/env python3
"""Lightweight metrics dashboard for ViewHub AI."""
import urllib.request
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer

BACKEND_URL = "http://localhost:9090/metrics"

def fetch_metrics():
    try:
        with urllib.request.urlopen(BACKEND_URL, timeout=5) as resp:
            return resp.read().decode()
    except Exception:
        return None

def parse_metrics(text):
    metrics = []
    for line in text.splitlines():
        if line.startswith('#') or not line.strip():
            continue
        parts = line.split()
        if len(parts) >= 2:
            name = parts[0]
            value = parts[1]
            if any(x in name for x in ['llm_', 'compact_', 'tool_call_']):
                metrics.append((name, value))
    return metrics

def render_html(metrics, error=None):
    rows = ""
    for name, value in metrics:
        rows += f'<tr><td class="name">{escape(name)}</td><td class="value">{escape(value)}</td></tr>\n'
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>ViewHub AI - Metrics Dashboard</title>
<style>
  body {{ font-family: 'Segoe UI', monospace; background: #1a1a2e; color: #eee; padding: 20px; }}
  h1 {{ color: #4a6cf7; }}
  table {{ width: 100%; border-collapse: collapse; }}
  tr {{ background: #16213e; margin: 5px 0; border-radius: 4px; }}
  td {{ padding: 10px; border-bottom: 1px solid #0f3460; }}
  .name {{ color: #4a6cf7; font-weight: bold; }}
  .value {{ color: #00d9ff; text-align: right; }}
  .error {{ color: #ff6b6b; font-size: 18px; }}
  .refresh {{ color: #888; font-size: 12px; margin-top: 10px; }}
</style>
</head>
<body>
<h1>ViewHub AI Metrics</h1>
<p class="refresh">Auto-refresh every 5s | <a href="http://localhost:9090/metrices" style="color:#4a6cf7;">Raw Metrics</a></p>
{'<p class="error">Backend metrics unavailable: ' + escape(error) + '</p>' if error else f'<table>{rows}</table>'}
</body></html>"""

class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        raw = fetch_metrics()
        if raw is None:
            html = render_html([], error="Cannot connect to backend at localhost:9090")
        else:
            metrics = parse_metrics(raw)
            html = render_html(metrics)
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode())

    def log_message(self, format, *args):
        pass

if __name__ == "__main__":
    port = 9092
    server = HTTPServer(('0.0.0.0', port), DashboardHandler)
    print(f"Metrics dashboard running at http://localhost:{port}")
    server.serve_forever()
