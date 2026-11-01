import json, os, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp import MCP

EXP = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "corpus", "expected.json")))

class R:
    def __init__(self):
        self.c = MCP(); self.init = self.c.init(); self.tasks = {}; self.cur = None
    def _do(self, tool, args):
        t0 = time.time(); r = self.c.call(tool, args, timeout=300); dt = time.time() - t0
        res = r.get("result", {}); txt = "".join(x.get("text", "") for x in res.get("content", []))
        return txt, round(dt, 3), len(txt.encode()), res.get("isError")
    def call(self, tool, args, note=""):
        txt, dt, nb, err = self._do(tool, args)
        self.tasks[self.cur]["calls"].append({"tool": tool, "args": args, "wall": dt, "bytes": nb,
                                              "isError": err, "note": note})
        self.tasks[self.cur]["last"] = txt
        return txt
    def alt(self, tool, args, note=""):
        """Measure an alternative strategy without charging it to the task's calls/bytes."""
        txt, dt, nb, err = self._do(tool, args)
        self.tasks[self.cur].setdefault("alt_strategy", []).append(
            {"tool": tool, "args": args, "wall": dt, "bytes": nb, "isError": err, "note": note})
        self.tasks[self.cur]["alt_text"] = txt
        return txt
    def task(self, tid, strategy=""):
        self.cur = tid; self.tasks[tid] = {"id": tid, "calls": [], "strategy": strategy}
    def finish(self, correct, answer, notes=""):
        t = self.tasks[self.cur]
        t["answer"] = answer; t["correct"] = correct; t["notes"] = notes
        t["n_calls"] = len(t["calls"]); t["wall"] = round(sum(c["wall"] for c in t["calls"]), 3)
        t["bytes"] = sum(c["bytes"] for c in t["calls"]); t.pop("last", None); t.pop("alt_text", None)
        print(f"{t['id']:4} calls={t['n_calls']:2} wall={t['wall']:7.3f}s bytes={t['bytes']:7} correct={correct} :: {answer[:110]}", flush=True)

def items(txt):
    out = []
    for chunk in txt.split("\n\n"):
        try: out.append(json.loads(chunk))
        except Exception: pass
    return out

def env(txt):
    try: return json.loads(txt)
    except Exception: return {}

def main():
    r = R()
    out = sys.argv[1]

    r.task("T1", "get_latest_proxy_http_history{count:1}")
    txt = r.call("get_latest_proxy_http_history", {"count": 1})
    r.finish("final=1" in txt, "newest item is GET /api/v1/health?final=1")

    r.task("T2", "get_proxy_http_history_regex{regex:'FLAG..',count:5,fields:[index,method,url,statusCode]} (unchanged); alt = search_proxy_http_history")
    txt = r.call("get_proxy_http_history_regex",
                 {"regex": "FLAG\\{needle-7f3a91\\}", "count": 5, "offset": 0,
                  "newestFirst": False, "fields": ["index", "method", "url", "statusCode"]})
    ok_old = "users/7777" in txt
    alt = r.alt("search_proxy_http_history",
                {"regex": "FLAG\\{needle-7f3a91\\}", "count": 5, "offset": 0},
                note="new tool: item row + match excerpt")
    e = env(alt)
    ok_new = e.get("totalMatches") == 1 and "FLAG{needle-7f3a91}" in alt
    r.finish(ok_old, f"old regex+fields -> 1 item /api/v1/users/7777; new search -> totalMatches={e.get('totalMatches')}, key in context={ok_new}")

    r.task("T3", "search_proxy_http_history{regex:'AKIAQ3EXAMPLEKEY7777'} - returns the hit with context")
    txt = r.call("search_proxy_http_history", {"regex": "AKIAQ3EXAMPLEKEY7777", "count": 5, "offset": 0})
    e = env(txt)
    key_shown = "AKIAQ3EXAMPLEKEY7777" in txt
    rows = e.get("items", [])
    ok = e.get("totalMatches") == EXP["aws_key_in_response"] and key_shown and all("vendor.3c9e.js" in (i.get("path") or "") for i in rows)
    m = rows[0]["matches"][0] if rows and rows[0].get("matches") else {}
    r.finish(ok, f"totalMatches={e.get('totalMatches')}, key visible={key_shown}, offset={m.get('offset')} in {m.get('part')}")

    r.task("T4", "get_proxy_http_history_regex{regex:'X-Debug-Token: dbg-41c2'}")
    txt = r.call("get_proxy_http_history_regex",
                 {"regex": "X-Debug-Token: dbg-41c2", "count": 5, "offset": 0,
                  "newestFirst": False, "fields": ["index", "url"]})
    its = items(txt)
    r.finish(len(its) == 1 and "/product/1" in txt, f"1 item shop /product/1, global index={its[0]['index'] if its else None}")

    r.task("T5", "get_proxy_http_history_filtered{host:admin.localhost,statusCode:403,count:1} -> totalMatches")
    txt = r.call("get_proxy_http_history_filtered",
                 {"host": "admin.localhost", "statusCode": 403, "count": 1, "offset": 0,
                  "newestFirst": False, "fields": ["index"]})
    e = env(txt)
    r.finish(e.get("totalMatches") == EXP["T5_admin_403"], f"totalMatches={e.get('totalMatches')} (expected {EXP['T5_admin_403']})")

    r.task("T6", "get_proxy_http_history_regex{regex:'<svg/onload=omp'} (unchanged); alt = search_proxy_http_history")
    txt = r.call("get_proxy_http_history_regex",
                 {"regex": "<svg/onload=omp", "count": 20, "offset": 0,
                  "newestFirst": False, "fields": ["index", "url"]})
    n_old = len(items(txt))
    alt = r.alt("search_proxy_http_history", {"regex": "<svg/onload=omp", "count": 20, "offset": 0},
                note="new tool")
    e = env(alt); n_new = e.get("totalMatches")
    r.finish(n_old == EXP["reflected_marker_requests"], f"old regex -> {n_old}; new search -> totalMatches={n_new}")

    r.task("T7", "get_proxy_http_history_regex{regex:'(url=|callback=|redirect_uri=)'}")
    txt = r.call("get_proxy_http_history_regex",
                 {"regex": "(url=|callback=|redirect_uri=)", "count": 60, "offset": 0,
                  "newestFirst": False, "fields": ["index", "url"]})
    n = len(items(txt))
    r.finish(n == EXP["ssrf_param_requests"], f"{n} (expected {EXP['ssrf_param_requests']})")

    r.task("T8", "2x get_proxy_http_history_count{regex}")
    a = r.call("get_proxy_http_history_count", {"regex": "Traceback"})
    b = r.call("get_proxy_http_history_count", {"regex": "NullPointerException"})
    r.finish(a.strip() == str(EXP["T8_500_traceback"]) and b.strip() == str(EXP["T8_500_npe"]),
             f"Traceback={a.strip()} NPE={b.strip()}")

    r.task("T9", "page history 500 at a time with fields:[host] (no sitemap tool)")
    txt = r.call("get_proxy_http_history", {"count": 500, "offset": 0, "newestFirst": True, "fields": ["host"]})
    hosts = sorted({i.get("host") for i in items(txt) if i.get("host")})
    off = 500
    while len(hosts) < 6 and off < 4000:
        t2 = r.call("get_proxy_http_history", {"count": 500, "offset": off, "newestFirst": True, "fields": ["host"]})
        hosts = sorted(set(hosts) | {i.get("host") for i in items(t2) if i.get("host")})
        off += 500
    for h in hosts:
        r.call("get_proxy_http_history_count", {"regex": "^Host: " + h.replace(".", "\\.") + "\\r"})
    r.finish(len(hosts) == 6, f"{len(hosts)} hosts: {hosts}")

    r.task("T10", "filtered{pathContains:/big/report.json} then get_proxy_http_history_body{offset:600000,length:2000}")
    txt = r.call("get_proxy_http_history_filtered",
                 {"pathContains": "/big/report.json", "count": 5, "offset": 0,
                  "newestFirst": False, "fields": ["index", "path", "responseContentLength"]})
    idx = env(txt)["items"][0]["index"]
    sl = r.call("get_proxy_http_history_body", {"index": idx, "message": "response", "offset": 600000, "length": 2000})
    raw = urllib.request.urlopen("http://static.localhost:18080/big/report.json?n=0", timeout=15).read()
    truth = raw[600000:602000].decode("utf-8", "replace")
    r.finish(sl == truth, f"index={idx} slice_len={len(sl)} exact_match={sl == truth}")

    r.task("T11", "filtered{method:POST,host:api.localhost,pathContains:/api/v1/orders,count:1} -> totalMatches")
    txt = r.call("get_proxy_http_history_filtered",
                 {"method": "POST", "host": "api.localhost", "pathContains": "/api/v1/orders",
                  "count": 1, "offset": 0, "newestFirst": False, "fields": ["index"]})
    e = env(txt)
    r.finish(e.get("totalMatches") == EXP["T11_post_orders"], f"totalMatches={e.get('totalMatches')}")

    r.task("T12", "count{regex} + regex page of 10")
    cnt = r.call("get_proxy_http_history_count", {"regex": "user\\d+@example\\.test"})
    page = r.call("get_proxy_http_history_regex",
                  {"regex": "user\\d+@example\\.test", "count": 10, "offset": 0,
                   "newestFirst": False, "fields": ["index", "responseContentLength"]})
    r.finish(cnt.strip() == str(EXP["T12_user_email_regex_matches"]), f"count={cnt.strip()}; page -> {len(items(page))}")

    r.task("T13", "filtered 401 -> send_http_request_from_history{replaceHeaders}")
    fx = r.call("get_proxy_http_history_filtered",
                {"host": "api.localhost", "statusCode": 401, "count": 1, "offset": 0,
                 "newestFirst": False, "fields": ["index", "url"]})
    gi = env(fx)["items"][0]["index"]
    add = r.call("send_http_request_from_history", {"index": gi, "replaceHeaders": {"Authorization": "Bearer add-me"}})
    fa = r.call("get_proxy_http_history_filtered",
                {"host": "admin.localhost", "statusCode": 403, "count": 1, "offset": 0,
                 "newestFirst": False, "fields": ["index", "url"]})
    ai = env(fa)["items"][0]["index"]
    rep = r.call("send_http_request_from_history", {"index": ai, "replaceHeaders": {"Cookie": "role=admin"}})
    r.finish(add.startswith("HTTP/1.1 200") and rep.startswith("HTTP/1.1 200"),
             f"add Authorization: {add.splitlines()[0][9:12]}; Cookie role=admin: {rep.splitlines()[0][9:12]}")

    r.task("T14", "filtered{.png} -> body slice, latin-1 round trip")
    f2 = r.call("get_proxy_http_history_filtered",
                {"pathContains": ".png", "count": 1, "offset": 0, "newestFirst": False,
                 "fields": ["index", "path", "responseContentLength", "mimeType"]})
    p = env(f2)["items"][0]; pidx, ppath = p["index"], p["path"]
    body = r.call("get_proxy_http_history_body", {"index": pidx, "message": "response", "offset": 0, "length": 9000})
    raw = urllib.request.urlopen("http://static.localhost:18080" + ppath, timeout=15).read()
    rt = body.encode("latin-1", "strict") == raw
    r.finish(rt, f"index={pidx} bytes={len(body)} sha256_roundtrip_ok={rt}")

    data = {"label": "burp-fork-v3", "serverInfo": r.init["result"]["serverInfo"], "tasks": r.tasks}
    json.dump(data, open(out, "w"), indent=1)
    print("ALL_CORRECT:", all(t["correct"] for t in r.tasks.values()), "->", out, flush=True)

main()
