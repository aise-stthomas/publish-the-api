#!/usr/bin/env bash
# Deploy the triage step as a function with an API gateway in front of it, in the AWS Academy Learner Lab.
#
#   ./deploy.sh                      build the package, create or update the function and the API, print the URL
#   ./deploy.sh --timeout 3          the same, with a 3-second time limit on the function
#   ./deploy.sh --memory 1024        more memory, which on Lambda is also more CPU
#   ./deploy.sh --throttle 2 5       set the API's throttle: 2 requests a second, a burst of 5 (Part 4)
#   ./deploy.sh --throttle off       remove the throttle
#   ./deploy.sh --recycle            no rebuild: force every sandbox cold, so the next call is a cold start
#
# What it assumes: the AWS CLI with a live Learner Lab session pasted into ~/.aws/credentials
# (Configuring AWS, section 3), uv, and your Gemini key in .env. It uses the pre-created
# LabRole, never creates IAM anything, and stays in us-east-1.
set -euo pipefail
cd "$(dirname "$0")"

FN="${FUNCTION_NAME:-triage-api}"
API="${API_NAME:-triage-api}"
export AWS_DEFAULT_REGION=us-east-1 AWS_PAGER=""
TIMEOUT=30; MEMORY=512; RECYCLE=0; THROTTLE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --timeout)  TIMEOUT="$2"; shift 2 ;;
    --memory)   MEMORY="$2"; shift 2 ;;
    --recycle)  RECYCLE=1; shift ;;
    --throttle) if [ "$2" = "off" ]; then THROTTLE="off"; shift 2; else THROTTLE="$2 $3"; shift 3; fi ;;
    *) echo "unknown option $1"; exit 2 ;;
  esac
done

# --- what we need ---------------------------------------------------------------------
command -v aws >/dev/null || { echo "aws CLI not found: brew install awscli (or see Configuring AWS)"; exit 1; }
command -v uv  >/dev/null || { echo "uv not found: see the README"; exit 1; }
[ -f .env ] || { echo "no .env: cp .env.example .env and paste your Gemini key"; exit 1; }
set -a; . ./.env; set +a
: "${GEMINI_API_KEY:?GEMINI_API_KEY is not set in .env}"
if [ -z "${LAB_TOKEN:-}" ]; then
  LAB_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
  printf '\nLAB_TOKEN=%s\n' "$LAB_TOKEN" >> .env
  echo "made a LAB_TOKEN and saved it in .env (POST /triage checks it on every request; GET / is open)"
fi

ACCOUNT="$(aws sts get-caller-identity --query Account --output text 2>/dev/null)" \
  || { echo "aws sts get-caller-identity failed: start a Learner Lab session and paste fresh credentials"; exit 1; }
ROLE="arn:aws:iam::${ACCOUNT}:role/LabRole"
ENV_VARS="Variables={GEMINI_API_KEY=${GEMINI_API_KEY},LAB_TOKEN=${LAB_TOKEN},DEPLOYED_AT=$(date +%s)}"

api_id() { aws apigatewayv2 get-apis --query "Items[?Name=='${API}'].ApiId | [0]" --output text 2>/dev/null; }

# --- throttle only: the gateway's own dial, no rebuild -----------------------------------
if [ -n "$THROTTLE" ]; then
  ID="$(api_id)"; [ -n "$ID" ] && [ "$ID" != "None" ] || { echo "no API called $API yet: run ./deploy.sh first"; exit 1; }
  if [ "$THROTTLE" = "off" ]; then
    aws apigatewayv2 update-stage --api-id "$ID" --stage-name '$default' --default-route-settings '{}' >/dev/null
    echo "throttle removed from $API (the account default applies: 10,000 a second, burst 5,000)"
  else
    set -- $THROTTLE
    aws apigatewayv2 update-stage --api-id "$ID" --stage-name '$default' \
      --default-route-settings "ThrottlingRateLimit=$1,ThrottlingBurstLimit=$2" >/dev/null
    echo "throttle on $API: $1 requests a second, burst $2. Over that, the gateway answers 429 and the function never runs."
  fi
  exit 0
fi

# --- recycle: a config change alone replaces every warm sandbox ------------------------
if [ "$RECYCLE" = 1 ]; then
  aws lambda update-function-configuration --function-name "$FN" --environment "$ENV_VARS" >/dev/null
  aws lambda wait function-updated --function-name "$FN"
  echo "recycled: the next call to $FN is a cold start"
  exit 0
fi

# --- build: the dependencies for Lambda's Linux, plus the system and the handler -------
echo "building the package..."
rm -rf build && mkdir -p build/pkg
uv pip install --quiet --target build/pkg \
  --python-platform x86_64-manylinux_2_28 --python-version 3.12 \
  "google-genai>=2.23" "python-dotenv>=1.0" "fastapi>=0.115" "mangum>=0.17"
cp -R src build/pkg/src
find build/pkg/src -name "__pycache__" -type d -prune -exec rm -rf {} +
( cd build/pkg && zip -qr ../function.zip . -x '*.pyc' -x '*/__pycache__/*' )
echo "  $(du -h build/function.zip | cut -f1) zipped, $(du -sh build/pkg | cut -f1) unpacked"

# --- the function: create or update ----------------------------------------------------
if aws lambda get-function --function-name "$FN" >/dev/null 2>&1; then
  echo "updating the function $FN..."
  aws lambda update-function-code --function-name "$FN" --zip-file "fileb://build/function.zip" >/dev/null
  aws lambda wait function-updated --function-name "$FN"
  aws lambda update-function-configuration --function-name "$FN" --handler src.function.handler.handler \
    --runtime python3.12 --timeout "$TIMEOUT" --memory-size "$MEMORY" --environment "$ENV_VARS" >/dev/null
  aws lambda wait function-updated --function-name "$FN"
else
  echo "creating the function $FN as $ROLE..."
  aws lambda create-function --function-name "$FN" \
    --runtime python3.12 --architectures x86_64 --handler src.function.handler.handler \
    --role "$ROLE" --zip-file "fileb://build/function.zip" \
    --timeout "$TIMEOUT" --memory-size "$MEMORY" --environment "$ENV_VARS" >/dev/null
  aws lambda wait function-active --function-name "$FN"
fi
FN_ARN="$(aws lambda get-function --function-name "$FN" --query Configuration.FunctionArn --output text)"

# --- the API: an HTTP API in front of the function. One route, every path and method, --
# --- proxied to the function with the same event shape a function URL would send, so -
# --- the handler does not change. Public: no IAM signature; the function checks the token.
ID="$(api_id)"
if [ -z "$ID" ] || [ "$ID" = "None" ]; then
  echo "creating the API $API..."
  ID="$(aws apigatewayv2 create-api --name "$API" --protocol-type HTTP --target "$FN_ARN" --query ApiId --output text)"
else
  echo "the API $API exists ($ID); keeping it"
fi
URL="$(aws apigatewayv2 get-api --api-id "$ID" --query ApiEndpoint --output text)"
# the gateway needs permission to invoke the function; tolerated if it is already there
aws lambda add-permission --function-name "$FN" --statement-id "apigw-${ID}" --action lambda:InvokeFunction \
  --principal apigateway.amazonaws.com --source-arn "arn:aws:execute-api:us-east-1:${ACCOUNT}:${ID}/*" >/dev/null 2>&1 || true

# remember the URL for record.py and call.sh
if grep -q '^LAB_URL=' .env; then
  sed -i.bak "s|^LAB_URL=.*|LAB_URL=${URL}/triage|" .env && rm -f .env.bak
else
  printf 'LAB_URL=%s\n' "${URL}/triage" >> .env
fi

echo
echo "deployed: $FN   timeout ${TIMEOUT}s   memory ${MEMORY} MB   behind the API $API ($ID)"
echo "url:      ${URL}/triage   (saved to .env as LAB_URL)"
echo "health:   ${URL}/        open to anyone: try it from your phone"
echo
echo "try it:   ./call.sh src/function/sample-event-body.json      (plain curl: the URL and the token)"
echo "record:   uv run record.py --provider http --runs 3"
echo "logs:     aws logs tail /aws/lambda/$FN --follow"
