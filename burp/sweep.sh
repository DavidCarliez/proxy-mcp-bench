#!/usr/bin/env bash
# Scale sweep for one Burp MCP extension (part 2 of docs/methodology.md).
#
# Run it after part 1, on the same project, so the history already holds one corpus
# load. It loads the corpus four more times (40k ... 100k requests) through Burp's
# proxy listener and measures S1-S4 plus Burp's resident memory after each load.
#
# Usage: burp/sweep.sh official|fork <out-dir> [proxy host:port, default 127.0.0.1:18090]
set -eu

which=${1:?official or fork}
out=${2:?output directory}
proxy=${3:-127.0.0.1:18090}
here=$(cd "$(dirname "$0")" && pwd)
root=$(dirname "$here")

case "$which" in
  official) script=measure_official.py ;;
  fork) script=measure_fork.py ;;
  *) echo "usage: $0 official|fork <out-dir> [proxy]" >&2; exit 2 ;;
esac

pid=$(pgrep -f burpsuite.jar | head -1)
rss_mb() { echo $(( $(awk '/VmRSS/{print $2}' "/proc/$pid/status") / 1024 )); }

mkdir -p "$out"
echo "1 $(rss_mb)" > "$out/$which-rss.txt"
for k in 2 3 4 5; do
  echo "=== load k=$k"
  python3 "$root/corpus/gen_traffic.py" --proxy "$proxy" | tail -1
  echo "$k $(rss_mb)" >> "$out/$which-rss.txt"
  python3 "$here/$script" sweep "$k" "$out/$which-k$k.json" | tail -6
done
