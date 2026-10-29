#!/bin/sh
# One relay cycle: step the controller with a recorded reply, then render the next relay text.
# Usage: sh experiments/stage3/relay_cycle.sh RUN_DIR NNN SUBAGENT_ID LATENCY_MS TOKENS TOOL_USES
set -e
cd "$(dirname "$0")/../.."
RUN="$1"; N="$2"
H=$(printf %s "$3" | shasum -a 256 | cut -c1-10)
OUT=$(python3 experiments/stage3/run_experiments.py step --run-dir "$RUN" --reply "$RUN/decisions/reply_$N.txt" \
      --subagent-id "planner-$H" --model sonnet --latency-ms "$4" --total-tokens "$5" --tool-uses "$6")
case "$OUT" in
  *'"terminal"'*) echo "$OUT" | cut -c1-400 ;;
  *) echo "$OUT" | cut -c1-250; echo "-----"; python3 experiments/stage3/render_relay.py "$RUN" ;;
esac
