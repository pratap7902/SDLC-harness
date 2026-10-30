# sdlc-harness-runner

The Agent SDK worker for the SDLC record service. It polls `next_work`, leases an item, runs
the matching skill from [`../skills`](../skills) with the Claude Agent SDK (Python), writes
the records the service needs (`pr_url`, `pr_sha`, attempt counters) and releases the lease.

**Local mode is the default** (`WORKSPACE_MODE=local`): repositories are paths on this host;
the runner works in a sandbox clone on `harness/<id>-<T-n>`, never pushes, records the branch
as `local:<repo>@<branch>` + head sha, posts its own JUnit evidence and runs review-pr on the
branch diff — no GitHub at all. `WORKSPACE_MODE=github` is the optional backend: push and PR
as a GitHub App, review-pr in GitHub Actions. Full design, GitHub App setup, secrets, docker
mode and what is unverified: [`../docs/runner.md`](../docs/runner.md).

It deploys separately from the service (its `claude-agent-sdk` needs a newer `mcp` than the
service pins) and talks to it only over HTTP: REST for the loop, MCP for the agent.

```bash
make runner-install          # runner/.venv
make test-runner             # tests: real service subprocess + fake agent + local git (needs `make install`)
runner/.venv/bin/python -m runner check | run | once | harvest
docker build -f runner/Dockerfile -t sdlc-harness-runner .   # from the repo root
```

| File | |
|---|---|
| `config.py` | settings from the environment; scrubs the App key from `os.environ` |
| `worker.py` | the loop: poll → claim → heartbeat → workspace → skill → records → release |
| `agent.py` | `ClaudeAgentOptions` per skill, `query()`, docker mode |
| `skills.py` | SKILL.md loading, kind → skill, per-skill tool policy |
| `local_workspace.py` | local mode: sandbox (`git clone --local --bare`, push URL `no_push`) + a worktree per job |
| `workspace.py` | GitHub mode: clone / branch / commit / push with an in-memory installation token |
| `github_app.py` | GitHub mode: App JWT → installation token, PR open/update (imported only in GitHub mode) |
| `srs_client.py` | the service's REST API |
| `github/review-pr.yml` | GitHub mode: the claude-code-action workflow template for target repos |
| `tests/` | `fakes.py` (scripted `query`, GitHub REST), end-to-end and unit tests |
