import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp import MCP

EXP = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "corpus", "expected.json")))
PAGE = 500

class R:
    def __init__(self):
        self.c = MCP(); self.init = self.c.init(); self.tasks = {}; self.cur = None
    def call(self, tool, args, note=""):
        t0 = time.time(); r = self.c.call(tool, args, timeout=600); dt = time.time() - t0
        res = r.get("result", {}); txt = "".join(x.get("text", "") for x in res.get("content", []))
        self.tasks[self.cur]["calls"].append({"tool": tool, "args": {k: (v if not isinstance(v, str) or len(v) < 200 else v[:120] + "...") for k, v in args.items()},
            "wall": round(dt, 3), "bytes": len(txt.encode()), "isError": res.get("isError"), "note": note})
        self.tasks[self.cur]["last"] = txt
        return txt
    def task(self, tid, strategy=""):
        self.cur = tid; self.tasks[tid] = {"id": tid, "calls": [], "strategy": strategy}
    def finish(self, correct, answer, notes=""):
        t = self.tasks[self.cur]
        t["answer"] = answer; t["correct"] = correct; t["notes"] = notes
        t["n_calls"] = len(t["calls"]); t["wall"] = round(sum(c["wall"] for c in t["calls"]), 3)
        t["bytes"] = sum(c["bytes"] for c in t["calls"]); t.pop("last", None)
        print(f"{t['id']:8} calls={t['n_calls']:2} wall={t['wall']:7.3f}s bytes={t['bytes']:8} correct={correct} :: {answer}", flush=True)

def items(txt):
    out = []
    for chunk in txt.split("\n\n"):
        try:
            o = json.loads(chunk)
            if isinstance(o, dict): out.append(o)
        except Exception: pass
    return out

def hist(r, offset, count):
    return r.call("get_proxy_http_history", {"count": count, "offset": offset})

def rx(r, pat, offset, count):
    return r.call("get_proxy_http_history_regex", {"regex": pat, "count": count, "offset": offset})

def count_matches(r, pat, page=PAGE, max_calls=40):
    n = 0; off = 0; calls = 0
    while calls < max_calls:
        t = rx(r, pat, off, page); calls += 1
        if t.strip() == "Reached end of items": break
        k = len(items(t)); n += k
        if k < page: break
        off += page
    return n, calls

def newest_item(r):
    """Exponential + binary search on offset with count=1; returns (item_text, offset, calls)."""
    t = hist(r, 0, 1)
    if t.strip() == "Reached end of items": return None, None
    lo, off, last = 0, 1, t
    while off < 400000:
        t = hist(r, off, 1)
        if t.strip() == "Reached end of items": break
        lo, last = off, t; off *= 2
    hi = off
    while hi - lo > 1:
        mid = (lo + hi) // 2
        t = hist(r, mid, 1)
        if t.strip() == "Reached end of items": hi = mid
        else: lo, last = mid, t
    return last, lo

def part1(r):
    r.task("T1", "no newest-first: exponential+binary search on offset with count=1, then keep the last valid item")
    txt, off = newest_item(r)
    r.finish(txt is not None and "final=1" in txt, f"newest at offset {off} (history has {off+1} items)", "~2*log2(N)+1 calls")

    r.task("T2", "get_proxy_http_history_regex{regex:'FLAG\\\\{needle-7f3a91\\\\}',count:100,offset:0}")
    txt = rx(r, "FLAG\\{needle-7f3a91\\}", 0, 100)
    r.finish("users/7777" in txt and len(items(txt)) == 1, f"{len(items(txt))} item /api/v1/users/7777")

    r.task("T3", "get_proxy_http_history_regex{regex:'AKIAQ3EXAMPLEKEY7777'} (items truncated at 5000 chars)")
    txt = rx(r, "AKIAQ3EXAMPLEKEY7777", 0, 100)
    n = len(items(txt))
    r.finish(n == EXP["aws_key_in_response"] and "vendor.3c9e.js" in txt, f"{n} items /assets/vendor.3c9e.js")

    r.task("T4", "get_proxy_http_history_regex{regex:'X-Debug-Token: dbg-41c2'}")
    txt = rx(r, "X-Debug-Token: dbg-41c2", 0, 100)
    r.finish("/product/1" in txt and len(items(txt)) == 1, f"{len(items(txt))} item shop /product/1")

    r.task("T5", "no count/filter: page get_proxy_http_history_regex{regex:'^HTTP/1.1 403'} in 500-item pages and count")
    n, calls = count_matches(r, "^HTTP/1.1 403")
    r.finish(n == EXP["T5_admin_403"], f"{n} matches (expected {EXP['T5_admin_403']}) in {calls} pages of {PAGE}")

    r.task("T6", "get_proxy_http_history_regex{regex:'<svg/onload=omp'}")
    txt = rx(r, "<svg/onload=omp", 0, 100)
    n = len(items(txt))
    r.finish(n == EXP["reflected_marker_requests"], f"{n} (expected {EXP['reflected_marker_requests']})")

    r.task("T7", "get_proxy_http_history_regex{regex:'(url=|callback=|redirect_uri=)'}")
    txt = rx(r, "(url=|callback=|redirect_uri=)", 0, 100)
    n = len(items(txt))
    r.finish(n == EXP["ssrf_param_requests"], f"{n} (expected {EXP['ssrf_param_requests']})")

    r.task("T8", "2x get_proxy_http_history_regex count by paging")
    a, _ = count_matches(r, "Traceback")
    b, _ = count_matches(r, "NullPointerException")
    r.finish(a == EXP["T8_500_traceback"] and b == EXP["T8_500_npe"], f"Traceback={a} NPE={b}")

    r.task("T9", "no sitemap/no fields: one 500-item page, parse 'Host:' out of each item")
    txt = hist(r, 0, PAGE)
    hosts = set()
    for it in items(txt):
        m = None
        req = it.get("request") or ""
        for line in req.split("\n"):
            if line.lower().startswith("host:"):
                m = line.split(":", 1)[1].strip(); break
        if m: hosts.add(m)
    r.finish(len(hosts) >= 6, f"{len(hosts)} hosts from 500 items: {sorted(hosts)}")

    r.task("T10", "no slicing tool: regex for the path, then read the item (5,000-char per-item cap)")
    txt = rx(r, "/big/report.json", 0, 5)
    its = items(txt)
    body_len = max((len(i.get("response") or "") for i in its), default=0)
    ok = any("600000" in json.dumps(i) for i in its)  # never true; slicing impossible
    r.finish(False, f"{len(its)} matching items, longest response string={body_len} chars, truncated",
             "the item JSON is cut at 5,000 chars, so bytes 600000-602000 of a 1.30 MB body are unreachable: infeasible")

    r.task("T11", "page get_proxy_http_history_regex{regex:'POST /api/v1/orders'} and count")
    n, calls = count_matches(r, "POST /api/v1/orders")
    r.finish(n == EXP["T11_post_orders"], f"{n} (expected {EXP['T11_post_orders']}) in {calls} pages")

    r.task("T12", "page get_proxy_http_history_regex{regex:'user\\\\d+@example\\\\.test'} and count items")
    n, calls = count_matches(r, "user\\d+@example\\.test")
    r.finish(n == EXP["T12_user_email_regex_matches"], f"{n} items in {calls} pages of {PAGE}",
             "no count primitive: 5,211 matches must be paged out to be counted")

    r.task("T13", "regex to fetch the raw request, edit a header, send_http1_request")
    txt = rx(r, "GET /api/v1/users/", 0, 3)
    its = items(txt)
    raw = None
    for it in its:
        req = (it.get("request") or "").replace("\r\n", "\n")
        if req.startswith("GET /api/v1/users/"):
            raw = req; break
    if raw:
        raw = raw.replace("User-Agent: Mozilla/5.0 bench", "User-Agent: burp-official-replay")
        resp = r.call("send_http1_request", {"content": raw, "targetHostname": "api.localhost",
                                             "targetPort": 18080, "usesHttps": False})
        r.finish(resp.startswith("HTTP/1.1 200"), f"replayed with edited User-Agent -> {resp.splitlines()[0]}")
    else:
        r.finish(False, "no raw request recovered from the item")

    r.task("T14", "regex for the .png item, read its bytes (5,000-char per-item cap)")
    txt = rx(r, "\\.png", 0, 5)
    its = items(txt)
    resp = its[0].get("response") if its else ""
    ok = bool(resp) and "truncated" not in resp and len((resp or "").encode("latin-1", "ignore")) >= 8008
    r.finish(ok, f"response string={len(resp or '')} chars for an 8,008-byte PNG",
             "binary body cannot be recovered: per-item 5,000-char cap, no byte/slice tool")

def sweep(r, k):
    r.task("S1", "exponential+binary offset search, count=1 pages")
    txt, off = newest_item(r)
    r.finish(txt is not None and "final=1" in txt, f"newest at offset {off} (history {off+1})")
    r.task("S2", "page get_proxy_http_history_regex{regex:'^HTTP/1.1 403'} and count")
    n, calls = count_matches(r, "^HTTP/1.1 403", page=PAGE, max_calls=40)
    r.finish(n == 554 * k, f"{n} matches expected {554*k} in {calls} pages of {PAGE}")
    r.task("S3", "get_proxy_http_history_regex{regex:'FLAG...'} count by paging")
    n, calls = count_matches(r, "FLAG\\{needle-7f3a91\\}")
    r.finish(n == k, f"{n} expected {k} in {calls} pages")
    r.task("S4", "one 500-item page, parse hosts")
    txt = hist(r, 0, PAGE)
    hosts = set()
    for it in items(txt):
        for line in (it.get("request") or "").split("\n"):
            if line.lower().startswith("host:"):
                hosts.add(line.split(":", 1)[1].strip()); break
    r.finish(len(hosts) >= 6, f"{len(hosts)} hosts from 500 items")

def main():
    mode, k, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    r = R()
    data = {"label": "burp-official", "serverInfo": r.init["result"]["serverInfo"], "k": k, "tasks": {}}
    if mode == "part1":
        part1(r); sweep(r, k)
    else:
        sweep(r, k)
    data["tasks"] = r.tasks
    json.dump(data, open(out, "w"), indent=1)
    print("ALL_CORRECT:", all(t["correct"] for t in data["tasks"].values()), "->", out, flush=True)

main()
