#!/usr/bin/env python3
"""Render the blog figures as self-contained dark SVG cards (no external deps).

Inputs: caido-blog-results.json, burp-blog-results.json, agent-results.jsonl, burp-results.json (v1).
Output: one SVG per figure in --out.
"""
import argparse
import collections
import html
import json
import math
import os
import statistics as st

BG0, BG1, BG2 = "#070b16", "#0b1222", "#10192b"
TEXT, MUTED, FAINT, GRID = "#e2e8f0", "#94a3b8", "#64748b", "#1e293b"
OK, BAD = "#34d399", "#f87171"
COLORS = {
    "burp-official": "#b45309",
    "burp-fork": "#fbbf24",
    "caido-official": "#0e7490",
    "caido-fork": "#22d3ee",
}
NAMES = {
    "burp-official": "Burp · official MCP",
    "burp-fork": "Burp · burp-mcp-enhanced",
    "caido-official": "Caido · upstream MCP",
    "caido-fork": "Caido · forked MCP",
}
LABELS = list(COLORS)
FONT = "Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MONO = "'Roboto Mono', ui-monospace, SFMono-Regular, Menlo, monospace"


def esc(s):
    return html.escape(str(s), quote=True)


class SVG:
    def __init__(self, w, h, title, desc):
        self.w, self.h, self.parts = w, h, []
        self.head = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
                     f'role="img" aria-labelledby="t d"><title id="t">{esc(title)}</title><desc id="d">{esc(desc)}</desc>'
                     f'<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{BG0}"/>'
                     f'<stop offset="0.55" stop-color="{BG1}"/><stop offset="1" stop-color="{BG2}"/></linearGradient>'
                     f'<pattern id="grid" width="34" height="34" patternUnits="userSpaceOnUse"><path d="M34 0H0V34" fill="none" '
                     f'stroke="#7dd3fc" stroke-opacity="0.045"/></pattern></defs>'
                     f'<rect width="{w}" height="{h}" rx="22" fill="url(#bg)"/><rect width="{w}" height="{h}" rx="22" fill="url(#grid)"/>')

    def text(self, x, y, s, size=14, fill=TEXT, anchor="start", weight=400, mono=False, opacity=1):
        self.parts.append(f'<text x="{x:.1f}" y="{y:.1f}" font-family="{MONO if mono else FONT}" font-size="{size}" '
                          f'font-weight="{weight}" fill="{fill}" fill-opacity="{opacity}" text-anchor="{anchor}">{esc(s)}</text>')

    def rect(self, x, y, w, h, fill, rx=4, stroke=None, sw=1, opacity=1):
        st_ = f' stroke="{stroke}" stroke-width="{sw}"' if stroke else ""
        self.parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(w,0):.1f}" height="{max(h,0):.1f}" rx="{rx}" '
                          f'fill="{fill}" fill-opacity="{opacity}"{st_}/>')

    def line(self, x1, y1, x2, y2, stroke=GRID, sw=1, dash=None, opacity=1):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.parts.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{stroke}" '
                          f'stroke-width="{sw}" stroke-opacity="{opacity}"{d}/>')

    def poly(self, pts, stroke, sw=3):
        d = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        self.parts.append(f'<polyline points="{d}" fill="none" stroke="{stroke}" stroke-width="{sw}" '
                          f'stroke-linejoin="round" stroke-linecap="round"/>')

    def circle(self, x, y, r, fill, stroke=None):
        st_ = f' stroke="{stroke}" stroke-width="2"' if stroke else ""
        self.parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}"{st_}/>')

    def header(self, title, subtitle):
        self.text(48, 62, title, 30, TEXT, weight=700)
        self.text(48, 92, subtitle, 16, MUTED)

    def legend(self, x, y, labels=LABELS, gap=28):
        for i, l in enumerate(labels):
            self.rect(x, y + i * gap - 11, 14, 14, COLORS[l], rx=3)
            self.text(x + 22, y + i * gap + 1, NAMES[l], 14, TEXT)

    def save(self, path):
        with open(path, "w") as f:
            f.write(self.head + "".join(self.parts) + "</svg>\n")


def human_bytes(b):
    if b is None:
        return "–"
    if b < 1000:
        return f"{b} B"
    if b < 1_000_000:
        return f"{b/1000:.1f} KB" if b < 10_000 else f"{b/1000:.0f} KB"
    return f"{b/1_000_000:.1f} MB"


def heat(b):
    """bytes -> fill color (green ... amber ... red) on a log scale 100 B .. 2 MB."""
    if b is None:
        return "#1f2937"
    t = (math.log10(max(b, 100)) - 2) / (math.log10(2_000_000) - 2)
    t = min(max(t, 0), 1)
    stops = [(0, (16, 185, 129)), (0.45, (234, 179, 8)), (0.75, (249, 115, 22)), (1, (239, 68, 68))]
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if t <= t1:
            f = (t - t0) / (t1 - t0)
            c = tuple(int(a + (b_ - a) * f) for a, b_ in zip(c0, c1))
            return "#%02x%02x%02x" % c
    return "#ef4444"


# ------------------------------------------------------------------ figures
def fig_task_grid(p1, out):
    rows = [("T1", "Newest request"), ("T2", "String in a response body"), ("T3", "Leaked key: find and show it"),
            ("T4", "Request-header needle"), ("T5", "Count 554 admin 403s"), ("T6", "Reflected XSS candidates"),
            ("T7", "SSRF-style parameters"), ("T8", "500s by stack trace (×2)"), ("T9", "List hosts / sitemap"),
            ("T10", "2 KB slice of a 1.3 MB body"), ("T11", "Count 598 POSTs"), ("T12", "Count 5,211 regex hits"),
            ("T13", "Replay with a modified header"), ("T14", "Binary PNG, byte-exact")]
    W, top, left, colw, rowh = 1280, 190, 380, 210, 46
    H = top + rowh * len(rows) + 110
    s = SVG(W, H, "MCP tool calls and output per task at 20,001 requests",
            "A grid of 14 proxy-history tasks against four MCP servers, showing tool calls and bytes returned to the model; color encodes bytes on a log scale, a red mark means a wrong answer.")
    s.header("Same 14 questions, four MCP servers", "20,001 requests · tool calls · bytes returned to the model (colour = bytes, log scale)")
    for j, l in enumerate(LABELS):
        cx = left + j * colw + colw / 2
        s.rect(left + j * colw + 8, top - 58, colw - 16, 6, COLORS[l], rx=3)
        s.text(cx, top - 30, NAMES[l].split(" · ")[0], 13, MUTED, "middle", 600)
        s.text(cx, top - 12, NAMES[l].split(" · ")[1], 15, TEXT, "middle", 700)
    for i, (tid, name) in enumerate(rows):
        y = top + i * rowh
        s.text(48, y + 29, tid, 14, FAINT, mono=True)
        s.text(96, y + 29, name, 15, TEXT)
        for j, l in enumerate(LABELS):
            c = (p1.get(l) or {}).get(tid)
            x = left + j * colw + 8
            if not c:
                s.rect(x, y + 6, colw - 16, rowh - 10, "#111827", rx=8, stroke="#334155")
                s.text(x + (colw - 16) / 2, y + 30, "no tool", 13, FAINT, "middle")
                continue
            infeasible = c.get("infeasible")
            fill = heat(c.get("bytes")) if not infeasible else "#7f1d1d"
            s.rect(x, y + 6, colw - 16, rowh - 10, fill, rx=8, opacity=0.28 if c.get("correct") else 0.18,
                   stroke=BAD if not c.get("correct") else fill, sw=2 if not c.get("correct") else 1)
            label = f"{c['calls']} call{'s' if c['calls'] != 1 else ''} · {human_bytes(c.get('bytes'))}"
            if infeasible:
                label = "infeasible"
            s.text(x + 14, y + 30, label, 14, TEXT, mono=True, weight=600)
            if not c.get("correct"):
                s.text(x + colw - 34, y + 31, "✗", 18, BAD, "middle", 700)
    # colour key
    ky = H - 58
    s.text(48, ky + 4, "bytes:", 13, MUTED)
    for k, b in enumerate([100, 1_000, 10_000, 100_000, 1_000_000]):
        s.rect(110 + k * 120, ky - 10, 26, 16, heat(b), rx=4, opacity=0.6)
        s.text(142 + k * 120, ky + 3, human_bytes(b), 13, MUTED)
    s.text(760, ky + 3, "✗ = wrong answer or corrupted data", 13, BAD)
    s.save(os.path.join(out, "task-grid.svg"))


def fig_scale(p2, out):
    W, H = 1280, 660
    s = SVG(W, H, "How cost grows with history size",
            "Two log-scale line charts from 20k to 100k requests: tool calls needed to find the newest request, and bytes returned to count matches, for each MCP.")
    s.header("What happens as the history grows", "same corpus loaded 1–5 times (20k → 100k requests) · log scale")
    panels = [("S1", "calls", "Find the newest request · tool calls"),
              ("S2", "bytes", "Count matching requests · bytes to the model")]
    for pi, (task, metric, title) in enumerate(panels):
        x0, y0, pw, ph = 100 + pi * 600, 160, 420, 360
        s.text(x0, y0 - 20, title, 17, TEXT, weight=600)
        series = []
        for l in LABELS:
            for variant, dash in ((task, None), (task + "_naive", "7 6")):
                pts = [(int(k) * 20, (p2[l][k].get(variant) or {}).get(metric)) for k in sorted(p2.get(l) or {}, key=int)]
                pts = [(n, v) for n, v in pts if v is not None]
                if pts:
                    series.append((l, dash, pts))
        allv = [v for _, _, pts in series for _, v in pts]
        lo = 10 ** math.floor(math.log10(max(min(allv), 1)))
        hi = 10 ** math.ceil(math.log10(max(allv)))
        fy = lambda v: y0 + ph - (math.log10(max(v, lo)) - math.log10(lo)) / (math.log10(hi) - math.log10(lo)) * ph
        fx = lambda n: x0 + (n - 20) / 80 * pw
        for e in range(int(math.log10(lo)), int(math.log10(hi)) + 1):
            t = 10 ** e
            s.line(x0, fy(t), x0 + pw, fy(t), GRID)
            s.text(x0 - 10, fy(t) + 4, human_bytes(t) if metric == "bytes" else f"{t:,}", 12, FAINT, "end", mono=True)
        for n in (20, 40, 60, 80, 100):
            s.text(fx(n), y0 + ph + 24, f"{n}k", 12, FAINT, "middle", mono=True)
        ends = collections.OrderedDict()
        for l, dash, pts in series:
            d = " ".join(f"{fx(n):.1f},{fy(v):.1f}" for n, v in pts)
            extra = f' stroke-dasharray="{dash}"' if dash else ""
            s.parts.append(f'<polyline points="{d}" fill="none" stroke="{COLORS[l]}" stroke-width="3" '
                           f'stroke-linejoin="round" stroke-linecap="round"{extra}/>')
            for n, v in pts:
                s.circle(fx(n), fy(v), 4.5, COLORS[l], stroke=BG0)
            if dash:
                (n0, v0), (n1, v1) = pts[0], pts[-1]
                s.text(fx(40), fy(v1) - 14, f"naive paging: {v0:,} → {v1:,} calls", 12, COLORS[l], mono=True, weight=600)
                continue
            n, v = pts[-1]
            ends.setdefault(round(fy(v)), []).append((l, v))
        for y, items in ends.items():
            l, v = items[0]
            lab = human_bytes(v) if metric == "bytes" else f"{v:,}"
            if len(items) > 1:
                lab += " (both forks)" if all(i[0].endswith("fork") for i in items) else ""
            s.text(fx(100) + 10, y + 4, lab, 12, COLORS[items[-1][0]], mono=True, weight=600)
    s.legend(100, H - 70, labels=LABELS[:2], gap=26)
    s.legend(520, H - 70, labels=LABELS[2:], gap=26)
    s.text(900, H - 70, "dashed = naive paging", 13, MUTED)
    s.text(900, H - 44, "solid = best strategy available", 13, MUTED)
    s.save(os.path.join(out, "scale.svg"))


def agent_agg(recs):
    agg = collections.defaultdict(list)
    for r in recs:
        agg[(r["label"], r["task"])].append(r)
    out = {}
    for (l, t), rs in agg.items():
        tok = [(r.get("input_tokens") or 0) + (r.get("cache_creation_input_tokens") or 0) +
               (r.get("cache_read_input_tokens") or 0) + (r.get("output_tokens") or 0) for r in rs]
        out[(l, t)] = {"n": len(rs), "ok": sum(r["correct"] for r in rs),
                       "wall": st.median(r["wall_s"] for r in rs), "tokens": st.median(tok),
                       "cost": st.median(r.get("cost_usd") or 0 for r in rs),
                       "calls": st.median(r["tool_calls"] for r in rs),
                       "bytes": st.median(r["tool_output_bytes"] for r in rs)}
    return out


def fig_agents(recs, out):
    agg = agent_agg(recs)
    tasks = [("A1", "Newest request"), ("A2", "Count admin 403s"), ("A3", "Find leaked AWS key"),
             ("A4", "SSRF candidates"), ("A6", "Requests per host"), ("A5", "Replay without auth")]
    W, H = 1280, 790
    s = SVG(W, H, "Real agent runs: tokens and correctness per task",
            "Grouped bars of median tokens processed by a Claude Sonnet agent per task for each MCP, with correctness out of three runs.")
    s.header("Real agents, same questions", "Claude Code (Sonnet) · MCP tools only · median of 3 runs · tokens processed per task (input + cache + output)")
    x0, y0, pw, ph = 90, 150, 1120, 400
    allv = [a["tokens"] for a in agg.values()] or [1]
    hi = max(allv) * 1.12
    step = next(s_ for s_ in (50_000, 100_000, 250_000, 500_000, 1_000_000) if hi / s_ <= 8)
    for t in range(0, int(hi) + 1, step):
        y = y0 + ph - t / hi * ph
        s.line(x0, y, x0 + pw, y, GRID)
        s.text(x0 - 10, y + 4, f"{t/1e6:.1f}M" if step >= 250_000 else f"{t//1000}k", 12, FAINT, "end", mono=True)
    gw = pw / len(tasks)
    bw = (gw - 40) / len(LABELS)
    for i, (tid, name) in enumerate(tasks):
        gx = x0 + i * gw + 20
        s.text(gx + (gw - 40) / 2, y0 + ph + 26, name, 14, TEXT, "middle", 600)
        for j, l in enumerate(LABELS):
            a = agg.get((l, tid))
            if not a:
                continue
            h = a["tokens"] / hi * ph
            x = gx + j * bw
            s.rect(x + 2, y0 + ph - h, bw - 4, h, COLORS[l], rx=3, opacity=0.9)
            mark, col = (f"{a['ok']}/{a['n']}", OK if a["ok"] == a["n"] else BAD)
            s.text(x + bw / 2, y0 + ph - h - 8, mark, 11, col, "middle", 700, mono=True)
    # summary table
    ty = y0 + ph + 70
    cols = [("label", 90), ("correct", 470), ("median time", 640), ("tokens", 820), ("cost", 980), ("tool calls", 1110)]
    for name, x in cols[1:]:
        s.text(x, ty, name, 13, MUTED, "end" if name != "label" else "start", 600)
    for r, l in enumerate(LABELS):
        rs = [agg[(l, t)] for t, _ in tasks if (l, t) in agg]
        if not rs:
            continue
        y = ty + 28 + r * 26
        s.rect(90, y - 12, 12, 12, COLORS[l], rx=3)
        s.text(110, y, NAMES[l], 14, TEXT)
        ok = sum(a["ok"] for a in rs)
        n = sum(a["n"] for a in rs)
        s.text(470, y, f"{ok}/{n}", 14, OK if ok == n else BAD, "end", 700, mono=True)
        s.text(640, y, f"{sum(a['wall'] for a in rs):.0f} s", 14, TEXT, "end", mono=True)
        s.text(820, y, f"{sum(a['tokens'] for a in rs)/1e6:.2f} M", 14, TEXT, "end", mono=True)
        s.text(980, y, f"${sum(a['cost'] for a in rs):.2f}", 14, TEXT, "end", mono=True)
        s.text(1110, y, f"{sum(a['calls'] for a in rs):.0f}", 14, TEXT, "end", mono=True)
    s.text(90, H - 20, "Totals are the sum over the six tasks of each task's median.", 12, FAINT)
    s.save(os.path.join(out, "agents.svg"))
    return agg


def fig_context(p3, out):
    W, H = 1280, 420
    s = SVG(W, H, "Context tax of tool definitions",
            "Horizontal bars of the tool-definition size each MCP adds to every model request.")
    s.header("The context tax: tool definitions ride along on every turn", "size of tools/list in tokens (≈ bytes / 4) and number of tools")
    x0, y0, pw = 360, 150, 680
    hi = max(v["approx_tokens"] for v in p3.values()) * 1.15
    for i, l in enumerate(LABELS):
        v = p3.get(l)
        if not v:
            continue
        y = y0 + i * 56
        s.text(48, y + 22, NAMES[l], 16, TEXT)
        w = v["approx_tokens"] / hi * pw
        s.rect(x0, y + 4, w, 28, COLORS[l], rx=6, opacity=0.9)
        s.text(x0 + w + 12, y + 24, f"{v['approx_tokens']:,} tokens · {v['tools']} tools", 14, TEXT, mono=True)
    s.save(os.path.join(out, "context-tax.svg"))


def fig_memory(rss, out):
    W, H = 1280, 520
    s = SVG(W, H, "Proxy memory as history grows", "Resident memory of Burp and Caido while holding 20k to 100k requests.")
    s.header("Memory held by the proxy itself", "resident set size after each 20k load (same corpus) · Burp's JVM grows its heap in steps")
    x0, y0, pw, ph = 110, 150, 900, 280
    allv = [v for ser in rss.values() for v in ser.values()] or [1]
    hi = max(allv) * 1.15
    fx = lambda n: x0 + (n - 20) / 80 * pw
    fy = lambda v: y0 + ph - v / hi * ph
    for t in range(0, int(hi) + 1, 1000 if hi > 4000 else 500):
        s.line(x0, fy(t), x0 + pw, fy(t), GRID)
        s.text(x0 - 10, fy(t) + 4, f"{t/1000:.1f} GB", 12, FAINT, "end", mono=True)
    for n in (20, 40, 60, 80, 100):
        s.text(fx(n), y0 + ph + 24, f"{n}k", 12, FAINT, "middle", mono=True)
    cols = {"Burp": COLORS["burp-fork"], "Caido": COLORS["caido-fork"]}
    for name, ser in rss.items():
        pts = [(int(k) * 20, v) for k, v in sorted(ser.items(), key=lambda kv: int(kv[0]))]
        s.poly([(fx(n), fy(v)) for n, v in pts], cols[name])
        for n, v in pts:
            s.circle(fx(n), fy(v), 4.5, cols[name], stroke=BG0)
        n, v = pts[-1]
        s.text(fx(n) + 12, fy(v) + 5, f"{name} · {v/1000:.1f} GB", 14, cols[name], weight=700)
    s.save(os.path.join(out, "memory.svg"))


def fig_cover(headline, out):
    W, H = 1280, 720
    s = SVG(W, H, "Agentic pentesting: making MCP servers efficient",
            "Cover image summarising the benchmark: tool calls, bytes and tokens before and after fixing the Burp and Caido MCP servers.")
    s.text(64, 104, "AGENTIC PENTESTING · MCP BENCHMARK", 18, "#67e8f9", weight=700, mono=True)
    s.text(64, 166, "The MCP server sets your agent's speed", 46, TEXT, weight=800)
    s.text(64, 210, "and your token bill. Same questions, before and after fixing the tools.", 20, MUTED)
    y = 300
    for i, (what, before, after) in enumerate(headline):
        yy = y + i * 128
        s.text(64, yy, what, 19, MUTED, weight=600)
        s.text(64, yy + 60, before, 50, BAD, weight=800, mono=True)
        ax = 64 + 31 * len(before) + 36
        s.text(ax, yy + 58, "→", 46, FAINT, weight=700)
        s.text(ax + 76, yy + 60, after, 50, OK, weight=800, mono=True)
    s.text(64, H - 36, "Burp & Caido · official vs improved MCP servers · 20k–100k requests · 72 real agent runs", 16, FAINT)
    s.save(os.path.join(out, "cover.svg"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.join(ROOT, "results", "figure-data.json"))
    ap.add_argument("--agents", default=os.path.join(ROOT, "results", "agents", "final.jsonl"))
    ap.add_argument("--out", default=os.path.join(ROOT, "figures"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    d = json.load(open(a.data))
    recs = [json.loads(l) for l in open(a.agents)]
    fig_task_grid(d["part1"], a.out)
    fig_scale(d["part2"], a.out)
    fig_context(d["part3"], a.out)
    fig_memory(d["rss"], a.out)
    fig_cover(d["headline"], a.out)
    agg = fig_agents(recs, a.out)
    print(json.dumps({f"{k[0]}:{k[1]}": v for k, v in sorted(agg.items())}, indent=1)[:3000])


if __name__ == "__main__":
    main()
