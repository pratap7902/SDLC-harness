# The runner, GitHub, and the skills

The record service (`srs`) is the system of record; it never runs a model. The work between
the human touchpoints is done by two runners that both talk to it as **agents** (bearer agent
tokens), using the seven skills in [`skills/`](../skills):

| Runner | Where | Serves |
|---|---|---|
| **Agent SDK runner** ([`runner/`](../runner)) | a long-running worker you deploy (container or VM) | `next_work` kinds `draft` (draft-from-ticket → review-draft), `review` (draft-from-ticket / plan-to-tasks), `plan` (plan-to-tasks), `task` (implement-task), `tests` (write-tests); `python -m runner harvest` on a weekly schedule (harvest-learnings) |
| **claude-code-action** ([`runner/github/review-pr.yml`](../runner/github/review-pr.yml)) | GitHub Actions in each target repo | `pull_request` events → review-pr |

```
             ┌──────────── record service (srs) ─────────────┐
 next_work ◄─┤ /api  REST: next-work, leases, records, repos  │◄── POST /hooks/github (HMAC)
 claim/hb/rel│ /mcp  MCP: read_record, write, drift_report,   │◄── POST …/test-runs/junit (CI)
             │        repos, kb_search, kb_get (Outline) …    │
             └──────▲──────────────────────────▲──────────────┘
                    │ REST (loop) + MCP (agent) │ MCP (agent)
   ┌────────────────┴───────────┐   ┌──────────┴─────────────────────┐
   │ Agent SDK runner           │   │ GitHub Actions: review-pr.yml   │
   │  poll → claim → heartbeat  │   │  claude-code-action, skill from │
   │  → workspace → query()     │   │  the base branch, inline        │
   │  → push as App → PR        │   │  comments + findings @ head sha │
   │  → records → release       │   └────────────────────────────────┘
   └────────────┬───────────────┘
                │ installation token (one repo), HTTPS
                ▼
             GitHub  ── webhooks (pull_request, push) ──► /hooks/github
```

## The worker loop (`runner/worker.py`)

1. `GET /api/next-work?kind=<k>` for each kind it serves (`RUNNER_KINDS`), agent lane only.
2. `POST /api/leases/claim` — 409 means another runner has it: skip. Concurrency is
   `RUNNER_CONCURRENCY` jobs at a time (one asyncio task each).
3. A background heartbeat (`POST /api/leases/{key}/heartbeat` every `RUNNER_HEARTBEAT_S`).
4. Workspace: a scratch dir (record-only skills) or a clone of the task's repository
   (`runner/workspace.py`) on branch `harness/<initiative-id>-<task-ref>`.
5. The skill runs through `claude_agent_sdk.query()` (`runner/agent.py`): `cwd` = the
   workspace; system prompt = Claude Code's preset + the skill's SKILL.md;
   `setting_sources=["project"]` for repo skills (the repo's CLAUDE.md loads); MCP = the
   record service with the runner's agent token (its `kb_search` / `kb_get` are the
   knowledge base) and `strict_mcp_config` so a repo's `.mcp.json` cannot add servers;
   per-skill `allowed_tools` / `disallowed_tools` (`runner/skills.py`) with
   `permission_mode="dontAsk"`; `model` (`RUNNER_MODEL`, default `claude-opus-5-5`),
   `max_turns`, `max_budget_usd`.
6. Records the runner guarantees, whatever the agent did: for `task` / `tests`, commit as
   the App's bot, run the registry's `test_command`, push, open or update the PR (body: task,
   decisions, ACs, rollback, the task's drift report, `srs-task: <id>/<T-n>`), then write
   `pr_url` / `pr_state` / `pr_sha` (with `base_rev`, deterministic batch id). For `draft`,
   it checks the draft exists and runs review-draft once it is submitted.
7. `DELETE /api/leases/{key}` and delete the workspace — always (`finally`).

**Crash safety.** Every runner write has a deterministic `batch_id` (seed + the record's
rev), so a retried job replays rather than doubles; a dead runner's lease expires on read and
the item comes back; PR creation finds the branch's open PR first; branches are pushed, never
force-pushed; an item this process has handled is not retaken for 30 minutes while it is in
the same state (same `why` / rework cause) — a draft waiting on humans or tests waiting on
CI are not re-run in a loop; a changed state is new work.

**Handoff.** A failed local verification, or a RED/ERROR JUnit run at the PR head (which
`next_work` turns into a `rework: ci` item), increments `task.ci_attempts`; a blocker/major
finding at the head (`rework: review`) increments `task.review_rounds`. At 3 (blueprint
`handoff:`) the task derives **STUCK**, `next_work` lists it in the human lane for the engg
assignee, and the runner stops: on local failures it pushes what it has as a **draft** PR so
the human can pick it up.

## Service additions the runner relies on

- **Repo registry** — global `repository` records (`REPO-n`): `name` (owner/repo),
  `default_branch`, `clone_url` (default `https://github.com/<name>.git`), `test_command`
  (**human-only**: the runner executes it), `junit_path`, `templates` (paved-road ids a task
  may name), `owners`, `state`. Write with `POST /api/global/records`; read `GET /api/repos`,
  `GET /api/repos/{owner}/{name}`, MCP `repos`. plan-to-tasks may only name registered repos
  and templates; the runner raises a gap (blocks the task) for an unregistered repo.
- **GitHub webhooks** — `POST /hooks/github`, verified with `X-Hub-Signature-256` (HMAC
  SHA-256 of the raw body with `GITHUB_WEBHOOK_SECRET`; unset → 503). `pull_request`
  (opened, reopened, synchronize, ready_for_review, converted_to_draft, edited, closed/merged)
  and `push` to a `harness/…` branch update the task's `pr_url` / `pr_state` / `pr_sha` as
  `github/webhook` (kind **system**: it cannot write human fields and gets no lease bypass —
  while a runner holds the task's lease the delivery is recorded as `github_sync_deferred`
  and the runner's own post-push write carries the truth). A new head sha makes the engg
  approval STALE and the deploy guard NO-GO by itself. PR → task: the head branch, else
  `srs-task: <id>/<T-n>` in the body, else a task whose `pr_url` is the PR.
- **JUnit ingestion** — `POST /api/initiatives/{id}/test-runs/junit` with
  `{task, sha, level, run_url, junit_xml, environment?}` (agent/CI token) writes one
  `test_run` at that sha; `covers` rows come from AC refs in test names (`AC-3`, `AC_3`,
  `test_AC_3_…`, `testAc3…`; worst outcome per AC; skipped tests count for nothing). GATE_PR,
  GATE_VALIDATED and the deploy guard read only runs at the relevant sha. Add to the target
  repo's CI after the test step:

  ```bash
  jq -n --arg task "$TASK" --arg sha "$GITHUB_SHA" --arg url "$RUN_URL" --rawfile xml reports/junit.xml \
    '{task:$task, sha:$sha, level:"integration", run_url:$url, junit_xml:$xml}' |
  curl -fsS -X POST "$SRS_URL/api/initiatives/$INITIATIVE_ID/test-runs/junit" \
    -H "Authorization: Bearer $SRS_CI_TOKEN" -H 'Content-Type: application/json' --data @-
  ```

  (`TASK` / `INITIATIVE_ID` come from the branch name `harness/<id>-<T-n>`.)

## GitHub App

Create one App for the organisation (Settings → Developer settings → GitHub Apps → New):

- **Repository permissions:** Contents *Read and write* · Pull requests *Read and write* ·
  Checks *Read-only* · Metadata *Read-only* (mandatory).
- **Webhook:** URL `https://<srs host>/hooks/github`, content type `application/json`, a
  random secret → `GITHUB_WEBHOOK_SECRET` on the service. **Events:** *Pull request*,
  *Push* (*Check run* / *Check suite* may be enabled for later use; they are ignored today).
- Install it on the pilot repositories only. Note the App id, its slug, and the installation
  id; generate a private key (PEM).

The runner signs a JWT (RS256, `iss` = App id, 9-minute expiry), exchanges it for an
installation token scoped to the one repository and to `contents:write` +
`pull_requests:write`, keeps it in memory, and hands it to git only through per-command
environment (`GIT_CONFIG_*` → `http.extraHeader`): not in argv, the remote URL, `.git/config`,
or the agent's environment. The agent never sees a GitHub credential and is denied
`git push`, `git remote`, `git config`, `gh`, `curl`, `wget`; the runner pushes.

## Secrets and settings

| Name | Used by | What |
|---|---|---|
| `ANTHROPIC_API_KEY` (or a cloud provider's `CLAUDE_CODE_USE_*` vars) | runner, Actions | Claude API auth (Agent SDK / claude-code-action). Set a spend limit per key. Never a claude.ai login. |
| `CLAUDE_CLI_PATH` (optional) | runner | Claude Code CLI to drive; unset = the one bundled with `claude-agent-sdk` |
| `SRS_URL`, `SRS_TOKEN` | runner | the service and an **agent** token: `make token ACTOR=runner-sdk KIND=agent` |
| `SRS_AGENT_TOKEN`, var `SRS_URL` | Actions | an agent token per repo (`review-pr-<repo>`) |
| `SRS_CI_TOKEN` | target repo CI | an agent token with role `ci` for JUnit uploads |
| `GITHUB_APP_ID`, `GITHUB_APP_SLUG`, `GITHUB_APP_PRIVATE_KEY` (or `…_PATH`), `GITHUB_INSTALLATION_ID` (optional) | runner | the App (the key is removed from the process environment after it is read) |
| `GITHUB_WEBHOOK_SECRET` | service | the App's webhook secret |
| `OUTLINE_URL`, `OUTLINE_API_KEY`, `CF_ACCESS_CLIENT_ID`, `CF_ACCESS_CLIENT_SECRET` | service | the knowledge base behind `kb_search` / `kb_get` (the runner reaches the KB only through the service) |
| `CF_ACCESS_CLIENT_ID`, `CF_ACCESS_CLIENT_SECRET` | Actions (optional) | when the service itself sits behind Cloudflare Access |

Runner tuning: `RUNNER_KINDS` (default `draft,review,plan,task,tests`), `RUNNER_CONCURRENCY`
(2), `RUNNER_POLL_INTERVAL_S` (20), `RUNNER_LEASE_TTL_MIN` (15), `RUNNER_HEARTBEAT_S` (120),
`RUNNER_MODEL` (`claude-opus-5-5`), `RUNNER_MAX_TURNS` (80), `RUNNER_MAX_BUDGET_USD` (15),
`RUNNER_WORK_ROOT`, `RUNNER_SKILLS_DIR`, `RUNNER_EXECUTION_MODE` (`local` | `docker`),
`RUNNER_DOCKER_IMAGE`, `RUNNER_DOCKER_NETWORK`, `RUNNER_EXTRA_MCP_JSON`,
`RUNNER_MAX_CI_ATTEMPTS` / `RUNNER_MAX_REVIEW_ROUNDS` (3), `HARNESS_BRANCH_PREFIX`
(`harness/`), `RUNNER_LOG_LEVEL`. Logs are JSON lines on stderr (`event`, `key`, `kind`,
`skill`, `turns`, `cost_usd`, …); secrets are never logged.

### Claude authentication and the CLI

- **API-key auth only.** The runner authenticates the Agent SDK with `ANTHROPIC_API_KEY`, or
  with one of the documented cloud providers: `CLAUDE_CODE_USE_BEDROCK=1` (+ AWS
  credentials), `CLAUDE_CODE_USE_VERTEX=1` (+ Google Cloud credentials),
  `CLAUDE_CODE_USE_FOUNDRY=1` (+ Azure credentials), or `CLAUDE_CODE_USE_ANTHROPIC_AWS=1` +
  `ANTHROPIC_AWS_WORKSPACE_ID` (Claude Platform on AWS, + AWS credentials). `run`, `once`,
  `harvest` and `exec-job` refuse to start when none is set. There is **no** path that uses a
  claude.ai login or subscription: the Agent SDK documentation states that, unless
  Anthropic has approved it, third-party products built on the SDK must not offer claude.ai
  login. Run the runner under a service account that has no Claude Code login of its own.
- **`CLAUDE_CLI_PATH`** (optional) is passed as `ClaudeAgentOptions(cli_path=…)`. Unset, the
  SDK uses the Claude Code CLI bundled with `claude-agent-sdk` (the default; the platform
  wheel ships it). The worker logs the CLI path, where it came from (`bundled`,
  `CLAUDE_CLI_PATH` or `PATH`), its `--version`, and the auth method at startup
  (`runner_started` / `claude_cli`).

## Deploying the runner (self-hosted)

```bash
make runner-install                          # runner/.venv (separate from the service's venv)
export SRS_URL=https://srs.example.com SRS_TOKEN=srs_… ANTHROPIC_API_KEY=…
export GITHUB_APP_ID=… GITHUB_APP_SLUG=… GITHUB_APP_PRIVATE_KEY_PATH=/secrets/app.pem
runner/.venv/bin/python -m runner check      # what is missing
runner/.venv/bin/python -m runner run        # poll forever (SIGTERM: finish in-flight, release)
runner/.venv/bin/python -m runner once       # cron-style: drain and exit
runner/.venv/bin/python -m runner harvest    # weekly
```

Container: `docker build -f runner/Dockerfile -t sdlc-harness-runner .` (from the repo root:
the image carries `skills/`), then
`docker run -d --env-file runner.env -v /secrets/app.pem:/secrets/app.pem:ro sdlc-harness-runner run`.
The runner needs outbound HTTPS to the Claude API, the service and GitHub; nothing inbound.

### Docker execution mode (recommended)

`RUNNER_EXECUTION_MODE=docker` runs **each skill** in a fresh container
(`docker run --rm --init --user <uid> -v <job dir>:/job sdlc-harness-runner exec-job
/job/job.json`): the job dir holds the clone and the job file; the container gets
`ANTHROPIC_API_KEY`, `SRS_URL`, `SRS_TOKEN` and the model settings — never the GitHub App key
or an installation token (the host process clones and pushes). The agent's Bash then runs in
a throwaway container instead of on the runner host. When the poller itself runs in a
container, give it the Docker socket and a `RUNNER_WORK_ROOT` bind-mounted at the **same
path** on the host, so job dirs resolve for sibling containers. `RUNNER_DOCKER_NETWORK`
restricts the job containers' network (e.g. a network whose egress allows only the Claude API
and the service).

In `local` mode the agent runs as a subprocess on the runner host: it can read the runner's
environment (the App key is scrubbed from it, `ANTHROPIC_API_KEY` and `SRS_TOKEN` are not) —
use it for development and trusted hosts only.

## review-pr in GitHub Actions

[`runner/github/review-pr.yml`](../runner/github/review-pr.yml) uses
`anthropics/claude-code-action@v1.0.247` (a pinned release). To install in a target repo:

1. Copy it to `.github/workflows/harness-review-pr.yml`.
2. Copy `skills/review-pr/SKILL.md` to `.harness/skills/review-pr/SKILL.md` and merge both to
   the default branch. The workflow reads the skill from the PR's **base** commit, so a PR
   cannot change its own review instructions.
3. Repository variable `SRS_URL` (and optionally `HARNESS_MODEL`); secrets
   `ANTHROPIC_API_KEY`, `SRS_AGENT_TOKEN` (`make token ACTOR=review-pr-<repo> KIND=agent`),
   and `CF_ACCESS_CLIENT_ID` / `CF_ACCESS_CLIENT_SECRET` if the service is behind Access.

It runs on non-draft PRs from the same repository (fork PRs get no secrets on
`pull_request`; never switch to `pull_request_target`), writes an MCP config with the
service's URL and token to `$RUNNER_TEMP` (deleted afterwards), and lets the model use only:
Read/Glob/Grep, inline comments (`mcp__github_inline_comment__create_inline_comment`),
`gh pr comment|diff|view`, and the service's read tools plus `write` (findings bound to the
head sha). It uses the workflow's `GITHUB_TOKEN` (`pull-requests: write`).

## What is verified, and what is not

Verified by tests (`make test`, `make test-runner`; no network, no model): the webhook HMAC
and PR/push → task updates and stale approvals; JUnit parsing, AC mapping and the gates
reading it; the registry; the worker loop end to end against a real service process
(SQLite, token auth, real MCP calls from a scripted fake `query`), a local bare repository
standing in for GitHub and an `httpx.MockTransport` GitHub REST API: draft → review-draft →
review item → plan → implement + write-tests on one branch → PR → records; CI-red and review
rework rounds; the 3-attempt handoff to STUCK; crash and lease handling; the token never on
disk; push-rebase over a concurrent push.

**Not verified against the live services:**

- A real Claude model running the skills (prompt quality, turn budgets, cost) — the SDK call
  shape follows the Python Agent SDK reference (`query`, `ClaudeAgentOptions`,
  `ResultMessage`, `ResultError`) for `claude-agent-sdk==0.2.175`, but only a fake ran.
- That `setting_sources=["project"]` plus the `claude_code` preset loads a target repo's
  CLAUDE.md the way we expect, and that `dontAsk` + the allow/deny lists behave exactly as
  documented for every tool.
- GitHub itself: the App JWT → installation-token exchange, `POST /pulls`, the bot identity
  lookup, `http.extraHeader` auth on github.com, real webhook deliveries.
- claude-code-action: the workflow follows the action's v1 documentation (inputs `prompt`,
  `claude_args`, `github_token`; `--mcp-config`, `--allowedTools`), but has not run.
- Docker execution mode (command construction is unit-tested only).
- The knowledge-base tools (`kb_search` / `kb_get`) live in the service and are only
  mock-tested there; the skills assume their documented `kb:outline/<doc-id>` citations.
