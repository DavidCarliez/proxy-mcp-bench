"""Trigger the extension's approval dialogs once per host before unattended runs.

Usage: warm_approvals.py <host>   (once per vhost, e.g. admin.localhost)

It reads one captured request for the host and replays it with a harmless extra
header, so Burp shows "Always Allow HTTP history" and "Always Allow Host". Click
both; the grant is stored in the project and later calls do not block.
"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp import MCP
c = MCP(); c.init()
host = sys.argv[1]
r = c.call("get_proxy_http_history_filtered", {"host": host, "count": 1, "offset": 0, "newestFirst": False, "fields": ["index", "url"]})
d = json.loads("".join(x["text"] for x in r["result"]["content"]))
idx = d["items"][0]["index"] if d["items"] else None
if idx is None:
    print("no request for", host); sys.exit(0)
r2 = c.call("send_http_request_from_history", {"index": idx, "replaceHeaders": {"X-Warm": "1"}}, timeout=120)
txt = "".join(x["text"] for x in r2["result"]["content"])
print(f"{host} index={idx} ->", txt.splitlines()[0] if txt else "no output")
