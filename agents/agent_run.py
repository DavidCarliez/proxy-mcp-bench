#!/usr/bin/env python3
"""End-to-end agent benchmark: run real Claude Code agents against one MCP server.

Each task in agent_tasks.json is given to a fresh `claude -p` session that only has
the MCP server under test: no shell, no file tools, no web. The harness records what
an operator actually pays:
  wall time, turns, tool calls, bytes of tool output fed back to the model,
  input/output/cache tokens, API-equivalent cost, and whether the answer is correct.

Usage:
  agent_run.py --label caido-fork --server caido --mcp-config cfg.json \
      [--tasks agent_tasks.json] [--only A1,A2] [--model sonnet] [--budget 3] \
      [--timeout 900] --out results.jsonl

The mcp-config file uses the Claude Code format: {"mcpServers": {"<server>": {...}}}.
--server must be the key used in that file; it scopes --allowedTools to mcp__<server>.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time

SYSTEM = ("You are assisting an authorized web penetration test. Answer using only the "
          "tools of the connected proxy MCP server. Be accurate; if you cannot determine "
          "an exact answer, say so instead of guessing.")


def run_task(task, a):
    cwd = tempfile.mkdtemp(prefix="agentrun-")
    cmd = ["claude", "-p", task["prompt"],
           "--output-format", "stream-json", "--verbose",
           "--model", a.model,
           "--strict-mcp-config", "--mcp-config", a.mcp_config,
           "--allowedTools", f"mcp__{a.server}",
           "--restricted", "--no-session-persistence",
           "--max-budget-usd", str(a.budget),
           "--append-system-prompt", SYSTEM]
    t0 = time.time()
    tool_calls, tool_bytes, tool_errors, result = 0, 0, 0, None
    tools_used, trace = {}, []
    timed_out = False
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=a.timeout)
        lines = p.stdout.splitlines()
        stderr = p.stderr[-2000:]
    except subprocess.TimeoutExpired as e:
        timed_out = True
        lines = (e.stdout or b"").decode(errors="replace").splitlines() if isinstance(e.stdout, bytes) else (e.stdout or "").splitlines()
        stderr = "timeout"
    wall = time.time() - t0
    for line in lines:
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = ev.get("message") or {}
        content = msg.get("content")
        for block in content if isinstance(content, list) else []:
            if block.get("type") == "tool_use":
                tool_calls += 1
                name = block.get("name", "?").split("__")[-1]
                tools_used[name] = tools_used.get(name, 0) + 1
                trace.append({"tool": name, "input": json.dumps(block.get("input"))[:300]})
            elif block.get("type") == "tool_result":
                c = block.get("content")
                if trace:
                    text = json.dumps(c) if not isinstance(c, str) else c
                    trace[-1]["result"] = text[:300]
                    trace[-1]["is_error"] = bool(block.get("is_error"))
                if isinstance(c, list):
                    tool_bytes += sum(len(x.get("text", "")) for x in c if isinstance(x, dict))
                elif isinstance(c, str):
                    tool_bytes += len(c)
                if block.get("is_error"):
                    tool_errors += 1
        if ev.get("type") == "result":
            result = ev
    answer = (result or {}).get("result") or ""
    usage = (result or {}).get("usage") or {}
    checks = [bool(re.search(rx, answer, re.I)) for rx in task["checks"]]
    return {
        "label": a.label, "task": task["id"], "model": a.model,
        "correct": all(checks), "checks_passed": sum(checks), "checks_total": len(checks),
        "wall_s": round(wall, 1), "timed_out": timed_out,
        "turns": (result or {}).get("num_turns"),
        "tool_calls": tool_calls, "tool_errors": tool_errors, "tool_output_bytes": tool_bytes,
        "tools_used": tools_used, "trace": trace,
        "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
        "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
        "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
        "cost_usd": (result or {}).get("total_cost_usd"),
        "subtype": (result or {}).get("subtype"), "is_error": (result or {}).get("is_error"),
        "answer": answer[:2000], "stderr_tail": stderr if not result else "",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--server", required=True)
    ap.add_argument("--mcp-config", required=True)
    ap.add_argument("--tasks", default=os.path.join(os.path.dirname(__file__), "agent_tasks.json"))
    ap.add_argument("--only")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--budget", type=float, default=3.0)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    tasks = json.load(open(a.tasks))
    if a.only:
        keep = a.only.split(",")
        tasks = [t for t in tasks if t["id"] in keep]
    for t in tasks:
        r = run_task(t, a)
        with open(a.out, "a") as f:
            f.write(json.dumps(r) + "\n")
        print(json.dumps({k: r[k] for k in ("label", "task", "correct", "wall_s", "tool_calls",
                                            "tool_output_bytes", "cost_usd", "subtype")}), flush=True)


if __name__ == "__main__":
    main()
