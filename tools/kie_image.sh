#!/usr/bin/env bash
# GPT Image 2 (Kie.ai) — text-to-image, or image-to-image when reference files are given.
# The API key comes from KIE_API_KEY (environment, the project .env, or the file KIE_ENV points to).
# Usage: tools/kie_image.sh <prompt.txt> <out.png> [aspect 16:9|4:5|1:1|3:2|…] [resolution 1K|2K|4K] [ref.png …]
# Defaults: aspect 16:9, resolution 1K (cheapest tier).
# Writes <out>.json beside the image with the model, prompt, task id and credits (provenance).
# Run one at a time: simultaneous uploads fail.
set -euo pipefail
PROMPT_FILE="$1"; OUT="$2"; ASPECT="${3:-16:9}"; RES="${4:-1K}"
shift $(( $# < 4 ? $# : 4 ))
KIE_ENV="${KIE_ENV:-$(dirname "$0")/../.env}"
K="${KIE_API_KEY:-}"
if [[ -z "$K" && -f "$KIE_ENV" ]]; then
  K=$(grep -m1 -E '^\s*KIE_API_KEY\s*=' "$KIE_ENV" | cut -d= -f2- | tr -d '"'"'"' \r')
fi
[[ -n "$K" ]] || { echo "Set KIE_API_KEY (environment, or a KIE_API_KEY= line in .env or in the file KIE_ENV points to)" >&2; exit 1; }
AUTH="Authorization: Bearer $K"

upload() {
  local raw
  raw=$(curl -sS -m 120 -H "$AUTH" -F "file=@$1" -F "uploadPath=site-chat-widget" \
    -F "fileName=$(date +%s)-$RANDOM-$(basename "$1")" https://kieai.redpandaai.co/api/file-stream-upload 2>&1) || true
  printf '%s' "$raw" | python3 -c 'import sys,json; d=json.load(sys.stdin)["data"]; print(d.get("fileUrl") or d.get("downloadUrl"))' 2>/dev/null \
    || { echo "upload failed for $1: ${raw:0:300}" >&2; return 1; }
}

URLS=""
for f in "$@"; do u=$(upload "$f") || exit 1; URLS+="$u"$'\n'; sleep 1; done

BODY=$(PF="$PROMPT_FILE" ASPECT="$ASPECT" RES="$RES" URLS="$URLS" python3 -c '
import json,os
e=os.environ
urls=[u for u in e["URLS"].splitlines() if u]
inp={"prompt":open(e["PF"]).read().strip(),"aspect_ratio":e["ASPECT"],"resolution":e["RES"]}
if urls: inp["input_urls"]=urls
model="gpt-image-2-image-to-image" if urls else "gpt-image-2-text-to-image"
print(json.dumps({"model":model,"input":inp}))')
TASK=$(curl -s -m 60 -H "$AUTH" -H "Content-Type: application/json" -d "$BODY" https://api.kie.ai/api/v1/jobs/createTask \
  | python3 -c 'import sys,json; d=json.load(sys.stdin); t=(d.get("data") or {}).get("taskId"); print(t or ""); t or sys.stderr.write(json.dumps(d)+"\n")')
[[ -n "$TASK" ]] || exit 1
echo "task $TASK (gpt-image-2 $ASPECT $RES)"

for _ in $(seq 1 100); do
  sleep 6
  R=$(curl -s -m 45 -H "$AUTH" "https://api.kie.ai/api/v1/jobs/recordInfo?taskId=$TASK" || true)
  STATE=$(printf '%s' "$R" | python3 -c 'import sys,json
try: print((json.load(sys.stdin).get("data") or {}).get("state") or "")
except Exception: print("")')
  if [[ "$STATE" == "success" ]]; then
    URL=$(printf '%s' "$R" | python3 -c 'import sys,json; d=json.load(sys.stdin)["data"]; r=d["resultJson"]; r=json.loads(r) if isinstance(r,str) else r; print(r["resultUrls"][0])')
    mkdir -p "$(dirname "$OUT")"
    curl -sL -m 300 -o "$OUT" "$URL"
    R="$R" PF="$PROMPT_FILE" OUT="$OUT" ASPECT="$ASPECT" RES="$RES" REFS="$*" python3 -c '
import json,os
e=os.environ
d=json.loads(e["R"])["data"]
json.dump({"generator":"kie.ai gpt-image-2","model":d.get("model"),"taskId":d.get("taskId"),
  "aspect":e["ASPECT"],"resolution":e["RES"],"refs":e["REFS"].split() if e["REFS"] else [],
  "credits":d.get("creditsConsumed"),"prompt":open(e["PF"]).read().strip()},
  open(e["OUT"]+".json","w"),ensure_ascii=False,indent=2)'
    echo "DONE $OUT"; exit 0
  fi
  if [[ "$STATE" == "fail" ]]; then
    echo "FAIL: $(printf '%s' "$R" | python3 -c 'import sys,json; d=json.load(sys.stdin)["data"]; print(d.get("failCode"), d.get("failMsg"))')" >&2
    exit 1
  fi
done
echo "TIMEOUT task $TASK" >&2; exit 1
