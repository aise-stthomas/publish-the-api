#!/usr/bin/env bash
# Remove everything the lab created, in AWS and here.
#
#   ./teardown.sh            the API, the function; the build directory; the LAB_URL and
#                            LAB_TOKEN lines in .env (your Gemini key stays). The CloudWatch
#                            log group is kept: it costs nothing, and it is your record of
#                            every call the function handled.
#   ./teardown.sh --keep-env leave .env untouched
#   ./teardown.sh --table    also delete the inference table (it is your data; by default it stays)
#
# You may not want to run this tonight: the next project starts from this deployment.
set -uo pipefail
cd "$(dirname "$0")"
FN="${FUNCTION_NAME:-triage-api}"; API="${API_NAME:-triage-api}"
export AWS_DEFAULT_REGION=us-east-1 AWS_PAGER=""
KEEP_ENV=0; DROP_TABLE=0
for a in "$@"; do [ "$a" = "--keep-env" ] && KEEP_ENV=1; [ "$a" = "--table" ] && DROP_TABLE=1; done
TABLE="${INFERENCES_TABLE:-triage-inferences}"

if command -v aws >/dev/null && aws sts get-caller-identity >/dev/null 2>&1; then
  ID="$(aws apigatewayv2 get-apis --query "Items[?Name=='${API}'].ApiId | [0]" --output text 2>/dev/null)"
  if [ -n "$ID" ] && [ "$ID" != "None" ] && aws apigatewayv2 delete-api --api-id "$ID" >/dev/null 2>&1; then echo "deleted the API $API ($ID)"; else echo "the API $API was not there"; fi
  if aws lambda delete-function --function-name "$FN" >/dev/null 2>&1; then echo "deleted the function $FN"; else echo "the function $FN was not there"; fi
  if [ "$DROP_TABLE" = 1 ]; then aws dynamodb delete-table --table-name "$TABLE" >/dev/null 2>&1 && echo "deleted the table $TABLE"; else echo "kept the table $TABLE (your inferences; --table deletes it)"; fi
  echo "kept the log group /aws/lambda/$FN (free; aws logs tail /aws/lambda/$FN --since 1d to read it)"
else
  echo "no AWS session (aws sts get-caller-identity failed): skipping the AWS side."
  echo "start a Learner Lab session, paste credentials, and run this again to delete the API and the function."
fi

rm -rf build && echo "removed build/"
if [ "$KEEP_ENV" = 0 ] && [ -f .env ]; then
  sed -i.bak '/^LAB_URL=/d; /^LAB_TOKEN=/d' .env && rm -f .env.bak
  echo "removed LAB_URL and LAB_TOKEN from .env (your Gemini key is still there)"
fi
