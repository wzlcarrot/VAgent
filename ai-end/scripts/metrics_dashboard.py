#!/usr/bin/env python3
"""Simple metrics dashboard - fetches /metrics from backend and displays key metrics."""
import urllib.request
from html import escape

BACKEND_URL = "http://localhost:9090/metrics"

def fetch_metrics():
    try:
        with urllib.request.urlopen(BACKEND_URL, timeout=5) as resp:
            return resp.read().decode()
    except Exception as e:
        return f"Error: {e}"

def parse_metrics(text):
    metrics = {}
    for line in text.splitlines():
        if line.startswith('#') or not line.strip():
            continue
        parts = line.split()
        if len(parts) >= 2:
            name = parts[0]
            value = parts[1]
            metrics[name] = value
    return metrics

def render_dashboard(metrics):
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>ViewHub AI - Metrics Dashboard</title>
<style>
  body { font-family: monospace; background: #1a1a2e; color: #eee; padding: 20px; }
  h1 { color: #4a6cf7; }
  .metric { background: #16213e; padding: 10px; margin: 5px 0; border-radius: 4px; }
  .name { color: #4a6cf7; font-weight: bold; }
  .value { color: #00d9ff; }
  .error { color: #ff6b6b; }
</style>
</head>
<body>
<h1>ViewHub AI Metrics</h1>
"""
    if isinstance(metrics, str) and metrics.startswith("Error"):
        html += f'<p class="error">{escape(metrics)}</p>'
    else:
        for name, value in sorted(metrics.items()):
            if any(x in name for x in ['llm_', 'compact_', 'tool_call_']):
                html += f'<div class="metric"><span class="name">{escape(name)}</span> = <span class="value">{escape(value)}</span></div>\n'
    html += "</body></html>"
    return html

if __name__ == "__main__":
    raw = fetch_metrics()
    metrics = parse_metrics(raw)
    print(render_dashboard(metrics))
