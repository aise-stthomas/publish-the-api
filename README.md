# Publish the API

A chat turn with Gemini and the support-ticket triage step go behind an **API gateway**
with a public URL, in your AWS Academy Learner Lab, with a Swagger page to try them
from and a token on the model routes. Every call lands in a **DynamoDB inference
table** and writes a line to the function's **log**. You reach it from your phone, read
the table and the log, and call a classmate's. The deployment you leave running is where
the next project starts.

The system under test is unchanged: `src/system/triage.py` is the same frozen file as in
the project repository, and the harness scores its outputs the same way.

| | |
|---|---|
| **In class** | [LAB.md](LAB.md) — *publish the API*: the API, Swagger, the token, the table, the log |
| **The function** | [src/function/app.py](src/function/app.py) — a FastAPI app, one page; `handler.py` adapts it to Lambda |
| **The golden set** | [data/golden/README.md](data/golden/README.md) |
| **The primer** | *API gateway*, in the course guide's supplemental material |

## What you need

- Python 3.12 or newer, and [`uv`](https://docs.astral.sh/uv/).
- Your Gemini key, in `.env`.
- The AWS CLI (`brew install awscli`, or see *Configuring AWS* in the course guide), and a
  **running Learner Lab session** with its credentials pasted into `~/.aws/credentials`.
  Sessions last about four hours; what you deploy outlives them.

Part 1 needs none of the AWS items. If AWS is not working for you tonight, do Part 1,
then use a classmate's URL for the rest.

## Setup, once

```bash
git clone https://github.com/aise-stthomas/publish-the-api
cd publish-the-api
cp .env.example .env         # paste your Gemini key
uv sync
uv run src/function/handler.py   # the function, through the Lambda path, with the fake provider
```

## The loop

```bash
./deploy.sh                                 # the table, the function, the API in front; prints the URL
./call.sh                                   # one ticket, plain curl: the URL and the token
uv run inferences.py                        # today's rows from the inference table, and a summary
aws logs tail /aws/lambda/triage-api --since 15m --region us-east-1   # the log
```

Also here, from the earlier labs, if you want them: `record.py` runs the golden set over
the API and saves every call, `score.py` scores the recordings, `latency.py` reports the
round trip, and `storm.py` with `./deploy.sh --throttle` shows the gateway's throttle.

## The files

```
record.py             CLI: run the suite, in this process or over HTTP, yours or a classmate's; saves every call
score.py              CLI: reads the fixtures and reports, per slice; never calls a model
latency.py            CLI: the three numbers, per run, from the fixtures
storm.py              CLI: many requests at once; counts 200s and 429s
inferences.py         CLI: read the inference table, by day; a summary per build and route
deploy.sh             creates the inference table, builds the zip, creates or updates the function, creates the HTTP API; --throttle
call.sh               one plain curl to the API
teardown.sh           deletes the API and the function; clears build/ and the URL from .env

src/                  the code
  system/             the system under test, frozen. Deployed as-is.
  function/
    app.py            the FastAPI app: GET / and /docs open · POST /chat and POST /triage behind the token · one row per call to the table
    handler.py        the Lambda entry point: Mangum(app); run it directly to exercise the Lambda path with no AWS
    local_server.py   the same app on http://127.0.0.1:9000 with Swagger at /docs
    sample-event-body.json   the example request
  harness/            golden set loader, fixtures, scorers, the report

data/                 the inputs and the outputs
  golden/             the ten tickets and their accounts
  fixtures/           every recorded call, by condition and run. Committed.
```

## What this is one instance of

An API gateway is the component that faces the internet for a system: the URL, the
routes, the throttle, the access log. Tonight's is an HTTP API on API Gateway in front of
a Lambda function, as of October 2026. What does not change: the public edge never holds
the model key; a caller's contract is the URL and the request shape; and the edge is
where a system first says no.
