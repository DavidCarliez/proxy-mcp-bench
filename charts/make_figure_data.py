#!/usr/bin/env python3
"""Build the chart inputs from the raw results.

Reads results/caido.json, results/burp.json and results/agents/*.jsonl, and writes:
  results/figure-data.json   normalised scripted results (parts 1-3, memory, cover numbers)
  results/agents/final.jsonl the agent runs used in the figures

Which runs make up the final agent set:
  burp-official   round1.jsonl
  burp-fork       burp-fork-enhanced2.jsonl (1.3.0-enhanced.2, with search_proxy_http_history)
  caido-official  round1.jsonl for A1-A4 and A6; replay-snapshot.jsonl for A5
  caido-fork      caido-fork-final.jsonl for A1-A4 and A6; replay-snapshot.jsonl for A5

The replay task (A5) writes to the history, so its final runs start from one shared
snapshot on both Caido servers (see docs/methodology.md).
"""
import json
import os

from charts import agent_agg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(ROOT, "results")
AGENT_TASKS = ["A1", "A2", "A3", "A4", "A6", "A5"]


def load_jsonl(name):
    with open(os.path.join(RES, "agents", name)) as f:
        return [json.loads(line) for line in f if line.strip()]


def norm(t):
    return {"calls": t.get("n_calls", t.get("calls")), "bytes": t.get("bytes"), "wall": t.get("wall"),
            "correct": t.get("correct"), "strategy": t.get("strategy"), "infeasible": t.get("infeasible", False)}


def human_bytes(b):
    if b < 1000:
        return f"{b} B"
    return f"{b / 1000:.0f} KB" if b >= 10_000 else f"{b / 1000:.1f} KB"


def final_agent_runs():
    round1 = load_jsonl("round1.jsonl")
    runs = [r for r in round1 if r["label"] == "burp-official"]
    runs += [r for r in round1 if r["label"] == "caido-official" and r["task"] != "A5"]
    runs += [dict(r, label="burp-fork") for r in load_jsonl("burp-fork-enhanced2.jsonl")]
    runs += load_jsonl("caido-fork-final.jsonl")
    runs += load_jsonl("replay-snapshot.jsonl")
    return runs


def figure_data(runs):
    with open(os.path.join(RES, "burp.json")) as f:
        burp = json.load(f)
    with open(os.path.join(RES, "caido.json")) as f:
        caido = json.load(f)
    d = {"part1": {}, "part2": {}, "part3": {}, "rss": {}, "meta": {}}

    for label in ("burp-official", "burp-fork"):
        d["part1"][label] = {k: norm(v) for k, v in burp[label]["part1"].items() if k.startswith("T")}
        d["part2"][label] = {k[1:]: {s: norm(v) for s, v in burp[label]["part2"][k]["tasks"].items()}
                             for k in burp[label]["part2"]}
        p3 = burp[label]["part3"]
        size = p3.get("tools_list_json_bytes") or p3.get("toolslist_result_bytes")
        d["part3"][label] = {"tools": p3.get("tools") or p3.get("tool_count"), "bytes": size, "approx_tokens": size // 4}
        d["meta"][label] = {k: burp[label]["meta"].get(k) for k in ("manifest_version", "serverInfo", "approvals")}

    # Part 1 and 3 of the Burp fork come from 1.3.0-enhanced.2; its sweep (part 2) ran on enhanced.1,
    # whose four sweep tasks do not use the search tool that enhanced.2 adds.
    v3 = burp["burp-fork-v3"]
    d["part1"]["burp-fork"] = {k: norm(v) for k, v in v3["part1"].items() if k.startswith("T") and "_" not in k}
    p3 = v3["part3"]
    size = p3.get("tools_list_json_bytes") or p3.get("toolslist_result_bytes")
    d["part3"]["burp-fork"] = {"tools": p3.get("tools") or p3.get("tool_count"), "bytes": size, "approx_tokens": size // 4}

    for label in ("caido-official", "caido-fork"):
        d["part1"][label] = {k: norm(v) for k, v in caido[label]["part1"].items() if not k.endswith("_naive")}
        d["part1"][label + "_naive"] = {k: norm(v) for k, v in caido[label]["part1"].items() if k.endswith("_naive")}
        d["part2"][label] = {k.split("_k")[1]: {s: norm(v) for s, v in caido[label][k].items()}
                             for k in caido[label] if k.startswith("part2_k")}
        d["part3"][label] = caido[label]["part3"]

    d["rss"]["Burp"] = {k[1:]: burp["burp-fork"]["part2"][k]["rss_mb"] for k in burp["burp-fork"]["part2"]}
    d["rss"]["Caido"] = {str(k): v["rss_mb"] for k, v in caido["caido_rss"].items()}
    d["rss_burp_official"] = {k[1:]: burp["burp-official"]["part2"][k]["rss_mb"] for k in burp["burp-official"]["part2"]}

    agg = agent_agg(runs)
    tokens_m = {label: round(sum(agg[(label, t)]["tokens"] for t in AGENT_TASKS) / 1e6, 2)
                for label in ("burp-official", "burp-fork")}
    naive = d["part1"]["caido-official_naive"]["T1_naive"]["calls"]
    newest = d["part1"]["caido-fork"]["T1"]["calls"]
    d["headline"] = [
        ["Find the newest of 20,001 requests · Caido", f"{naive} calls", f"{newest} call" + ("s" if newest != 1 else "")],
        ["Count 554 matching requests · Burp", human_bytes(d["part1"]["burp-official"]["T5"]["bytes"]),
         human_bytes(d["part1"]["burp-fork"]["T5"]["bytes"])],
        ["Six agent tasks, median tokens · Burp", f"{tokens_m['burp-official']:.1f}M", f"{tokens_m['burp-fork']:.2f}M"],
    ]
    return d, agg


def main():
    runs = final_agent_runs()
    with open(os.path.join(RES, "agents", "final.jsonl"), "w") as f:
        for r in runs:
            f.write(json.dumps(r) + "\n")
    data, agg = figure_data(runs)
    with open(os.path.join(RES, "figure-data.json"), "w") as f:
        json.dump(data, f, indent=1)

    print(f"{'server':15} {'scripted':>9} {'calls':>6} {'bytes':>10} | {'agents':>6} {'time':>6} {'tokens':>8} {'cost':>6}")
    for label in ("burp-official", "burp-fork", "caido-official", "caido-fork"):
        p1 = data["part1"][label]
        a = [agg[(label, t)] for t in AGENT_TASKS]
        ok = sum(r["correct"] for r in runs if r["label"] == label)
        n = sum(1 for r in runs if r["label"] == label)
        print(f"{label:15} {sum(v['correct'] for v in p1.values()):>4}/{len(p1):<4} {sum(v['calls'] for v in p1.values()):>6} "
              f"{sum(v['bytes'] or 0 for v in p1.values()):>10} | {ok:>3}/{n:<2} {sum(x['wall'] for x in a):>5.0f}s "
              f"{sum(x['tokens'] for x in a) / 1e6:>7.2f}M {sum(x['cost'] for x in a):>6.2f}")


if __name__ == "__main__":
    main()
