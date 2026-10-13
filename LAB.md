# Lab: publish the API

Tonight your model goes behind a **public URL**. A serverless function in your Learner
Lab holds the Gemini key and two routes, a chat turn and the triage step. An **API
gateway** in front of it gives the function an address anyone can reach, with a Swagger
page to try it from. A **token** protects the two model routes. Every call lands as one
row in a **DynamoDB table**, and every call writes a line to the function's **log**.

By the end you have five things: **a URL**, **a Swagger page open on your phone**, **a
reply from your model**, **a row in the table**, and **the log line for that same call**.
The next project starts from what you leave running tonight.

**What this lab shows.**

1. **The public edge is a component.** The gateway owns the URL and the routes. The
   function behind it never faces the internet directly.
2. **The key stays inside.** Your Gemini key is in the function's environment, behind
   the gateway. The token at the edge is the only secret a caller holds.
3. **Every inference is a row.** The function writes what happened on every call, never
   what was said, to a table that outlives the request.
4. **The log is where you look first.** Every call also writes one line to CloudWatch,
   and that line is how you find out what the function did when the row does not say.

## Part 1: run it on your laptop

```bash
cp .env.example .env            # paste your Gemini key
uv sync
uv run src/function/local_server.py   # http://127.0.0.1:9000 · Swagger at /docs
```

Open http://127.0.0.1:9000/docs and try both routes from the page:

- `POST /chat`: a message in, the model's reply out. One turn, no memory.
- `POST /triage`: a ticket and an account in, the decision out.

Locally, with no token set, both are open.

## Part 2: deploy it

Start a Learner Lab session and paste its credentials into `~/.aws/credentials`
(*Configuring AWS*, section 3). Then:

```bash
./deploy.sh
```

The script creates the **inference table** in DynamoDB, builds the package, creates the
function, and puts an **HTTP API** in front of it, so the same app you ran locally now
answers at a public address. It prints the URL and saves it, with a token, in `.env`.

## Part 3: reach it from anywhere

Open the URL `deploy.sh` printed, with `/docs` on the end, **on your phone**, off the
campus network. Click **Authorize**, paste the `LAB_TOKEN` from your `.env`, and send a
`POST /chat`. Without the token the route answers `401`.

From the terminal:

```bash
./call.sh                        # the sample ticket to POST /triage: the URL and the token, no signature
```

## Part 4: the inference table

Every call you just made is a row. Read them back:

```bash
uv run inferences.py             # today's rows, in order, then a summary per route
uv run inferences.py --json      # the rows as JSON lines
```

A row holds what happened, never what was said: the time, the route, the build that
answered, cold start, latency, the action, the amount, whether the output parsed, any
error. The partition key is the day and the sort key is the time, so one day is one
query. The same rows two other ways:

- **The console.** DynamoDB → Tables → `triage-inferences` → *Explore table items*.
- **The CLI.**

  ```bash
  aws dynamodb query --table-name triage-inferences --region us-east-1 \
    --key-condition-expression "#d = :d" --expression-attribute-names '{"#d":"day"}' \
    --expression-attribute-values "{\":d\":{\"S\":\"$(date -u +%Y-%m-%d)\"}}" --output table
  ```

Find the row for the call you made from your phone.

## Part 5: the logs

```bash
aws logs tail /aws/lambda/triage-api --since 15m --region us-east-1
```

Every call wrote a line beginning `INFERENCE`, the same fields as the row. Around it:
the platform's own `START`, `END` and `REPORT` lines, with the billed duration and, on
the first call into a new sandbox, the init duration. Find the `INFERENCE` line for your
phone's call and the `REPORT` line that follows it.

In the console: CloudWatch → Log groups → `/aws/lambda/triage-api`.

## Part 6: call a classmate's

Swap with another team: your URL and token for theirs. Open their Swagger page,
authorize with their token, and send them a message with `POST /chat`. Then one ticket
from the terminal:

```bash
LAB_URL=https://THEIRS.execute-api.us-east-1.amazonaws.com/triage LAB_TOKEN=THEIR_TOKEN ./call.sh
```

Then check: your call is a row in *their* table and a line in *their* log, not yours.

## Part 7 (optional): the gateway's throttle

```bash
./deploy.sh --throttle 2 5       # 2 requests a second, a burst of 5
uv run storm.py --n 30           # 30 requests at once to GET /: count the 200s and the 429s
./deploy.sh --throttle off
```

A `429` is answered by the gateway; the function never ran. The setting takes minutes to
reach the edge and is applied on a best-effort basis, so a storm right after the change
is usually all `200`. Set it, come back later, storm again.

## Leave it running

The next project builds on this deployment, so leave it up: the function, the API and
the table cost nothing while idle. `./teardown.sh` removes the function and the API if
you ever want to; the table stays unless you add `--table`.

## Keep

- your URL, and whether `/docs` opened on your phone
- one `/chat` reply
- one row from the table, and the `INFERENCE` and `REPORT` log lines for the same call

## Background

An **API gateway** is the general component: one front door for a system, owning the
public URL, the routes, authentication, throttling, and the access log. Tonight's
instance is an HTTP API on API Gateway in front of a Lambda function, as of October
2026, with DynamoDB as the table and CloudWatch as the log. What does not change: the
thing that faces the internet is never the thing that holds the model key; a caller's
contract is the URL and the request shape, not the implementation; every inference is
recorded somewhere that outlives the request.

## If something breaks

| Symptom | Likely cause | What to do |
|---|---|---|
| `deploy.sh`: `sts get-caller-identity failed` | the Learner Lab session expired, or credentials were not pasted | start the session, paste fresh credentials, run it again |
| `/docs` works on the laptop but not on the phone | the phone's network blocks it, or the URL was mistyped | try mobile data; copy the URL from `deploy.sh`'s output and add `/docs` |
| `POST /chat` or `/triage` answers `401` | the token is wrong or missing | the value is `LAB_TOKEN` in `.env`; for a classmate's API use theirs |
| `502` or `503` from `/chat` | the vendor refused: a dead key or a daily cap | check the Gemini key in `.env`, `./deploy.sh` again; look at the log |
| the first call takes seconds | a cold start: the runtime and the SDK loading | call again; the second is warm |
| `inferences.py` shows no rows | the write failed, or it is after midnight UTC | the log will say `inference_table`; try `--days 2` |
