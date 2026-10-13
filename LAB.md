# Lab: publish the API

Tonight your model goes behind a **public URL**. A serverless function in your Learner
Lab holds the Gemini key and two routes, a chat turn and the triage step, and an **API
gateway** in front of it gives the function an address anyone on the internet can reach,
with a Swagger page to try it from. By the end you have **a URL**, **a Swagger page you
can open on your phone**, and **a classmate's URL you have called**. The next project
starts from what you leave running tonight.

**What this lab shows.**

1. **The public edge is a component.** The gateway is what faces the internet: it owns
   the URL, the routes, the throttle and the access log. The function behind it never
   faces anyone directly.
2. **The URL is the contract.** Another team can use your system with nothing but the
   URL, the token, and the request shape on the Swagger page. For the first time, your
   system is a system to someone else.
3. **The key stays inside.** Your Gemini key is in the function's environment, behind
   the gateway. The token at the edge is the only secret a caller ever holds.

## Part 1: run it on your laptop

```bash
cp .env.example .env            # paste your Gemini key
uv sync
uv run src/function/local_server.py   # http://127.0.0.1:9000 · Swagger at /docs
```

Open http://127.0.0.1:9000/docs. Two routes to try from the page:

- `POST /chat`: a message in, the model's reply out. One turn, no memory.
- `POST /triage`: the ticket and account from the earlier labs, the decision out.

Both need the `x-lab-token` header once deployed; locally, with no token set, they are
open.

## Part 2: deploy it

Start a Learner Lab session and paste its credentials into `~/.aws/credentials`
(*Configuring AWS*, section 3). Then:

```bash
./deploy.sh
```

The script builds the package, creates the function, and puts an **HTTP API** in front
of it: one route for every path and method, proxied to the function, so the same app
you ran locally now answers at a public address. It prints the URL and saves it, and a
token, in `.env`.

## Part 3: reach it from anywhere

Open the URL `deploy.sh` printed, with `/docs` on the end, **on your phone**, off the
campus network. That is the point of tonight: nothing between your phone and the model
but the gateway and your function.

On the Swagger page click **Authorize**, paste the `LAB_TOKEN` from your `.env`, and
send a `POST /chat`. Without the token the route answers `401`; that header is the one
secret a caller holds. Then from the terminal:

```bash
./call.sh                    # the sample ticket to POST /triage: the URL and the token, no signature
uv run record.py --provider http --runs 3 && uv run score.py local http && uv run latency.py http
```

## Part 4: call a classmate's

Swap with another team: your URL and your token for theirs. Open their Swagger page,
send them a message with `POST /chat`, then run your golden set against their triage:

```bash
LAB_URL=https://THEIRS.execute-api.us-east-1.amazonaws.com/triage LAB_TOKEN=THEIR_TOKEN ./call.sh
uv run record.py --provider http --runs 1 --name classmate --url https://THEIRS.execute-api.us-east-1.amazonaws.com/triage --token THEIR_TOKEN
uv run score.py http classmate
```

Same tickets, same scorers, a system someone else runs.

## Part 5 (if there is time): the gateway's own dial

```bash
./deploy.sh --throttle 2 5   # 2 requests a second, a burst of 5; give it half a minute to apply
uv run storm.py --n 30       # 30 requests at once to GET /: count the 200s and the 429s
./deploy.sh --throttle off   # also takes a moment
```

Every `429` was answered by the gateway; the function never ran and nothing was spent.
The setting takes a little while to reach the edge in both directions, so if the first
storm is all `200`, wait and storm again.

## Leave it running

The next project builds on this deployment, so leave it up: the function and the API
cost nothing while idle. `./teardown.sh` removes everything if you ever want to.

## Keep

- your URL, and whether `/docs` opened on your phone
- one `/chat` reply, from the Swagger page
- `score.py http classmate`: your deployment and theirs on the same golden set

## Background

An **API gateway** is the general component: one front door for a system, owning the
public URL, routing by path and method, authentication, throttling, and the access log.
Tonight's instance is an HTTP API on API Gateway, in front of a Lambda function, as of
October 2026. What does not change: the thing that faces the internet is never the thing
that holds the model key; the contract a caller sees is the URL and the request shape,
not the implementation; and the edge is where a system first says no.

## If something breaks

| Symptom | Likely cause | What to do |
|---|---|---|
| `deploy.sh`: `sts get-caller-identity failed` | the Learner Lab session expired, or credentials were not pasted | start the session, paste fresh credentials, run it again |
| `/docs` works on the laptop but not on the phone | the phone's network blocks it, or the URL was mistyped | try mobile data; copy the URL from `deploy.sh`'s output and add `/docs` |
| `POST /chat` or `/triage` answers `401` | the token is wrong or missing | the value is `LAB_TOKEN` in `.env`; for a classmate's API use theirs |
| `502` or `503` from `/chat` | the vendor refused: a dead key or a daily cap | check the Gemini key in `.env`, `./deploy.sh` again; `aws logs tail /aws/lambda/triage-api --since 10m` |
| the first call takes seconds | a cold start: the runtime and the SDK loading | call again; the second is warm |
