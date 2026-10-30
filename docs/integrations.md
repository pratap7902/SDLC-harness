# Integrations: Microsoft Teams, Outline, Azure DevOps Boards, Cloudflare Access

> **Status: none of this is verified against a live tenant.** Every adapter is written
> against the vendors' documented HTTP APIs and tested only with mocked HTTP
> (`httpx.MockTransport`, `tests/fixtures/mock_http.py`; no request leaves the test
> process). Before relying on one, do the smoke test listed in its section against your
> own tenant. Lines marked **(unverified)** are behaviours the docs describe that we could
> not check.

Everything is configured through the environment (`.env`). Nothing tenant-specific
(hostnames, org or project names, tenant ids) is in the code. Secrets are read only from
the environment and are never logged or stored in the database. Each integration is
**off** until its required variables are set.

| Integration | Code | Required env |
|---|---|---|
| People directory | `app/people` | — (always on; fed by Teams) |
| Microsoft Teams | `app/teams` | `TEAMS_TENANT_ID`, `TEAMS_GRAPH_CLIENT_ID`, `TEAMS_GRAPH_CLIENT_SECRET`; for the bot: `TEAMS_BOT_APP_ID`, `TEAMS_BOT_APP_SECRET` |
| Outline | `app/knowledge` | `OUTLINE_URL`, `OUTLINE_API_KEY` (+ optional `OUTLINE_CF_ACCESS_CLIENT_ID` / `_SECRET`) |
| Azure DevOps Boards | `app/azure_devops` | `ADO_ORG`, `ADO_PROJECT`, `ADO_PAT`; for the webhook: `ADO_WEBHOOK_SECRET` |
| Cloudflare Access (web UI identity) | `app/auth/services/cloudflare_access.py` | `CF_ACCESS_TEAM_DOMAIN`, `CF_ACCESS_AUD` |
| Links in messages | — | `PUBLIC_BASE_URL` (the web UI's URL) |

```bash
# .env — placeholders only
PUBLIC_BASE_URL=https://srs.example.com
TEAMS_TENANT_ID=00000000-0000-0000-0000-000000000000
TEAMS_GRAPH_CLIENT_ID=00000000-0000-0000-0000-000000000000
TEAMS_GRAPH_CLIENT_SECRET=...            # from the app registration
TEAMS_BOT_APP_ID=00000000-0000-0000-0000-000000000000
TEAMS_BOT_APP_SECRET=...
# TEAMS_SERVICE_URL=https://smba.trafficmanager.net/teams/   (default)
OUTLINE_URL=https://wiki.example.com
OUTLINE_API_KEY=ol_api_...
OUTLINE_CF_ACCESS_CLIENT_ID=...access    # only when Cloudflare Access fronts the wiki
OUTLINE_CF_ACCESS_CLIENT_SECRET=...
ADO_ORG=your-org
ADO_PROJECT=your-project
ADO_PAT=...
ADO_WEBHOOK_SECRET=...                   # a long random string you also give the service hook
# ADO_DRI_FIELD=System.AssignedTo        (default)  ADO_ENGG_FIELD=Custom.Engineer  (empty = not read)
# ADO_CHILD_TYPE=Task                    (default)
CF_ACCESS_TEAM_DOMAIN=your-team.cloudflareaccess.com
CF_ACCESS_AUD=...                        # the Access application's AUD tag
```

## People: one person across platforms

`people` holds one canonical person per human: `handle` (what assignments name), name,
email. Each platform account is a `person_identities` row (`teams` → the Entra object id).
Roles stay assignments. `/api/people` serves the directory merged with every handle that
holds an assignment (`in_directory: false` marks a handle that has no person row yet). The
UI's "Viewing as" list and the assignment pickers read it.

**Merge rules** (`PeopleService.sync`; the match key is the email, `PEOPLE_MATCH_KEY=email`):

1. An account that is already linked has its email, name and active flag refreshed. If its
   email now belongs to a *different* person, the entry goes to review as a `conflict` (the
   link is kept).
2. An unlinked account whose email matches exactly one person is linked, unless that
   person already has another account on the same platform. In that case it is a
   `conflict`: one human with two accounts.
3. If two accounts in one sync share an email, both are a `conflict` and neither is
   linked.
4. An account with no email, or one whose email no person has, is `unmatched`.

Nothing in review is created automatically. An admin resolves each entry: `link` (to a
handle), `create` (a person from the entry) or `ignore` — `POST
/api/admin/people/review/{id}/resolve`. A later sync updates the open review row; it does
not add a second one. Bootstrap the directory with `POST /api/admin/people` (`handle`,
`name`, `email`) for the people who already hold assignments, then run the sync.

Admin endpoints need the token role `admin` (`make token ACTOR=ops KIND=human ROLES=admin`).
In local header mode, any human counts as admin.

## Microsoft Teams

**Approach.** Users come from **Microsoft Graph**, called app-only with client
credentials. Messages and button clicks go through a **Bot Framework bot** (an Azure Bot
resource on the Teams channel), sending proactive 1:1 messages that carry Adaptive Cards.
This is the documented way for a service to message a user in Teams and get button clicks
back. The Graph `chatMessage` API cannot send as an application outside migration
scenarios, and incoming webhooks / Workflows only post to channels and cannot tell us who
clicked.

### Setup

1. **App registration for Graph** (Entra admin center → App registrations → New):
   - Single tenant.
   - Create a client secret.
   - API permissions → Microsoft Graph → **Application** → `User.Read.All`, then **Grant
     admin consent**.
   - Set `TEAMS_TENANT_ID`, `TEAMS_GRAPH_CLIENT_ID` and `TEAMS_GRAPH_CLIENT_SECRET`.
2. **Azure Bot resource** (Azure portal → Create → Azure Bot):
   - Type **Single Tenant**; this creates or uses an app registration.
   - Create a secret for it, then set `TEAMS_BOT_APP_ID` (the Microsoft App ID) and
     `TEAMS_BOT_APP_SECRET`. These can be the same app as step 1 if you add the bot to it.
   - Messaging endpoint: `https://<your host>/api/teams/messages`.
   - Channels → add **Microsoft Teams**.
3. **Teams app package**:
   - A `manifest.json` with `bots: [{botId: <TEAMS_BOT_APP_ID>, scopes: ["personal"]}]`
     and two icons.
   - Upload it in the Teams admin center.
   - Install it for the people who should get messages, either with a setup policy or
     with Graph `POST /users/{id}/teamwork/installedApps` (permission
     `TeamsAppInstallation.ReadWriteForUser.All`).
   - Proactive 1:1 messages only work once the app is installed for that user.
4. **Directory sync.** Run `make sync-people` (or `POST /api/admin/people/sync`), then
   clear the review list.
5. **Notifications.** Schedule `make notify` every minute (cron or a k8s CronJob), or
   call `POST /api/admin/notifications/run`.

### Notifications

On each run, the dispatcher reads every open human item (the inbox) and notifies the
routed person when they have a Teams identity:

| kind | when | card |
|---|---|---|
| `gap_routed` | a gap is routed to you | question, context, recommendation; one **Answer: <option>** button per option |
| `review_item_queued` | a record you own may no longer hold | what moved; a **Still holds** button |
| `approval_stale` | your PR approval went stale (the head or the drift digest moved) | a link to the task page |
| `overdue` | any of your items passed its SLA (sent once per item) | a link to the inbox |

Every card has an **Open in the web UI** link built from `PUBLIC_BASE_URL`. The
`deliveries` table has one row per (`dedupe_key`, channel):

- a row that was sent is never sent again;
- a failure retries with backoff (2, 4, 8 … minutes) up to `TEAMS_NOTIFY_MAX_ATTEMPTS`
  (default 5), after which the row is `dead`;
- `GET /api/admin/deliveries` lists the rows.

The bot's 1:1 conversation id is cached on the person's Teams identity.

### Inbound actions

`POST /api/teams/messages` is the bot's messaging endpoint. It sits outside bearer-token
auth and authenticates each request itself:

1. **Verify.** The Bot Connector's RS256 JWT must check out:
   - keys from `TEAMS_BOT_JWKS_URL` (default `https://login.botframework.com/v1/.well-known/keys`);
   - `iss` = `https://api.botframework.com`;
   - `aud` = the bot app id;
   - the token's `serviceurl` must equal the activity's `serviceUrl`.

   Anything else gets a 401 and nothing is read.
2. **Map.** `from.aadObjectId` is looked up as the person's `teams` identity. If there is
   none, the reply is "not in the directory" and nothing is written.
3. **Act** as `Actor(<handle>, human, via=teams)` through the same service paths as the
   web UI:
   - `answer_gap` → `InboxService.answer_gap`, which records `answered_by`, the routing,
     and `answered_via: teams` (the web inbox records `web`);
   - `uphold_review` → `ReviewService.resolve(upheld)`.

   Every human-only rule still applies.
4. **Replace the card** with the outcome (a Bot Connector update), so the buttons cannot
   be pressed twice. A second press would be refused anyway, because the gap is no longer
   OPEN.

### Limits and caveats

- **(unverified)** Creating a 1:1 conversation with `members: [{id: <Entra object id>}]`
  and `tenantId` works only after the app is installed for the user. Otherwise the
  delivery fails with 403/404 and retries until `dead`.
- **(unverified)** The JWKS URL and issuer for single-tenant bots. Microsoft documents
  the Bot Connector issuer `https://api.botframework.com` with the keys above for
  channel → bot requests. If your tenant differs, override `TEAMS_BOT_JWKS_URL` and
  `TEAMS_BOT_ISSUER`.
- `Action.Submit` (not `Action.Execute`) is used, so a click arrives as a `message`
  activity whose `value` is the button's data. Universal Actions would need an `invoke`
  handler, which is not built.
- `TEAMS_SERVICE_URL` defaults to the global `https://smba.trafficmanager.net/teams/`.
  Sovereign clouds (GCC, GCC High, DoD) need their own.
- Graph users with no `mail` fall back to the UPN, except guest (`#EXT#`) UPNs; those
  stay unmatched.
- Smoke test: sync one user; run `make notify` with one routed gap; click an option; check
  that `GET /api/initiatives/{id}/records/G-n` shows `answered_via: teams`.

## Outline knowledge base

`OutlineClient` uses Outline's REST API: `POST /api/documents.search` and `POST
/api/documents.info`, with `Authorization: Bearer <OUTLINE_API_KEY>`. When Cloudflare
Access fronts the wiki, it also sends `CF-Access-Client-Id` / `CF-Access-Client-Secret`
from a Cloudflare **service token**. REST was chosen over Outline's `/mcp` because the two
documented reads are all we need, and a stateless REST call is simpler to run and to mock
than an MCP client session.

- **MCP tools.** `kb_search(query, limit)` returns one line per hit, starting with its
  citation, plus a snippet. `kb_get(citation)` returns the document as markdown;
  `#<heading-anchor>` returns only that section. REST equivalents: `GET
  /api/kb/search?q=` and `GET /api/kb/doc?citation=`.
- **Citations.** `kb:outline/<document id>[#<anchor>]`. The anchor is the heading's slug:
  lower-case, with non-alphanumerics turned into `-`. Any `refs` field whose targets
  allow `external` accepts a citation, after a shape check: `decision.cites`, and now
  `finding.cites`.
- **Setup.**
  1. Outline → Settings → API → create an API key (it acts as that user, so use a
     read-only service user); set `OUTLINE_URL` and `OUTLINE_API_KEY`.
  2. If Cloudflare Access protects the wiki: Zero Trust → Access → Service Auth → create
     a service token. Add a **Service Auth** policy that allows it on the wiki's Access
     application. Set `OUTLINE_CF_ACCESS_CLIENT_ID` and `OUTLINE_CF_ACCESS_CLIENT_SECRET`.
- **Caveats.**
  - **(unverified)** The response shapes (`data[].document`, `context` with `<b>`
    highlights) and the heading-slug anchors follow Outline's API docs and UI behaviour.
  - An HTML answer (an Access login page) is reported as an error, never as "no results".
- **Smoke test.** `kb_search` for a known title, then `kb_get` its citation with a
  heading anchor.

## Azure DevOps Boards

Uses the Work Item Tracking REST API (api-version 7.1) with a PAT (`Authorization: Basic
base64(":" + PAT)`). The org and project come only from `ADO_ORG` / `ADO_PROJECT`, and the
host from `ADO_BASE_URL` (default `https://dev.azure.com`).

- **Import.** Starting from a link or an id:
  - `GET …/_apis/wit/workitems/{id}?$expand=all` reads the work item;
  - the title becomes the title;
  - the description and acceptance criteria (HTML) become the requirement markdown;
  - the work item link becomes `work_item_url`;
  - the DRI comes from `ADO_DRI_FIELD` (default `System.AssignedTo`) and engg from
    `ADO_ENGG_FIELD` (empty by default, so it is not read). Each is an identity field
    whose email must be a person in the people directory; the caller can override either.

  It then calls the **same intake** (`IntakeService.start`) as the web form. Where to use
  it:
  - REST: `GET /api/azure-devops/preview?work_item=` (prefill) and `POST
    /api/azure-devops/import`;
  - MCP: `import_work_item`;
  - the Start feature screen, through **Fill from work item**.

  A work item that is already imported gets 409 `ALREADY_IMPORTED`.
- **Webhook.** `POST /api/hooks/azure-devops` receives `workitem.updated` events
  (`workitem.created` is accepted and ignored). The shared secret arrives in the
  `X-SRS-Hook-Secret` header, or as the basic-auth password, and is compared in constant
  time. With no `ADO_WEBHOOK_SECRET` set, every request gets a 401. On a linked work item:
  - an edit to its **description or acceptance criteria** raises a `prd_drift` gap (domain
    product, routed like any gap; it blocks the draft when there is one). The gap asks
    whether to re-snapshot, and **nothing is re-pinned automatically**. While one such
    gap is open, further edits do not add more.
  - an edit to a **pushed child item** sets the task's `tracker_edited: yes`. The worklist
    then shows a `tracker` item for the engg; the record here is never overwritten.
- **Task push** (one-way). `POST /api/initiatives/{id}/azure-devops/push-tasks` creates
  each task that has no `tracker_id` as a child (`ADO_CHILD_TYPE`, default `Task`) of the
  feature's work item, using a `System.LinkTypes.Hierarchy-Reverse` relation. It stores
  `tracker_id` and `tracker_url` through the write path, as the service. Leases bind only
  agents, so a leased task still gets its tracker id. Running it again skips tasks that
  already have one.
- **Setup.**
  1. User settings → Personal access tokens → new token, scoped to the org. Scope **Work
     Items: Read & write** (Read is enough without the push). Set `ADO_ORG`,
     `ADO_PROJECT` and `ADO_PAT`.
  2. Project settings → Service hooks → **+** → **Web Hooks**, created twice:
     - trigger **Work item updated** (optionally filtered to the area path);
     - URL `https://<your host>/api/hooks/azure-devops`;
     - HTTP headers `X-SRS-Hook-Secret: <ADO_WEBHOOK_SECRET>`, or basic auth with that
       password;
     - resource details **All**;
     - optionally the same again for **Work item created**.
- **Caveats.**
  - **(unverified)** A bad PAT can come back as an HTML sign-in page (203) rather than a
    401. We treat any non-JSON answer as an error.
  - **(unverified)** The `workitem.updated` payload shape (`resource.workItemId`,
    `resource.fields.<name>.newValue`).
  - Only fields that change appear in `resource.fields`. That is what drives the drift
    gap and the `tracker_edited` flag.
- **Smoke test.** Import one item. Push its tasks. Edit the parent's description in ADO
  and check that a `prd_drift` gap appears. Edit a child and check that the task shows
  `tracker_edited: yes`.

## Cloudflare Access (web UI identity in production)

With `AUTH_MODE=token` and Cloudflare Access in front of the service:

- `CF_ACCESS_TEAM_DOMAIN` is set to your team domain, for example
  `your-team.cloudflareaccess.com`;
- `CF_ACCESS_AUD` is set to the Access application's **AUD tag**.

Each request's `Cf-Access-Jwt-Assertion` is then checked as an RS256 JWT against
`https://<team>/cdn-cgi/access/certs`, with `iss` = `https://<team>` and `aud` = the AUD
tag. Its `email` is mapped to the canonical person, giving `Actor(<handle>, human)`:

- an email that is not in the directory gets 403 `NOT_IN_DIRECTORY`;
- the `Cf-Access-Authenticated-User-Email` header alone is **never** trusted;
- service tokens carry no email, so they get 403 and should use a bearer token instead.

A human bearer token minted with an email or handle (`scripts/mint_token.py mint --actor
priya@example.com --kind human`) resolves to the same person.

**(unverified)** This follows Cloudflare's documented JWT validation. Check it against your
own Access application before turning off header mode in any shared environment. JWT
verification is pure Python (`app/core/utils/jwt_rs256.py`, RSASSA-PKCS1-v1_5/SHA-256, with
JWKS caching and refetch on an unknown `kid`), so no crypto dependency is added.

## Adding another system later

Each integration is a small package with:

- a client that uses `app.core.utils.http.client()` (mockable through `http.TRANSPORT`);
- a service that writes **only through `RecordService.write`**, as the service
  (`SERVICE.with_agent(...)`) or as the mapped human;
- routes, with webhooks on the public `hooks_router` and each one verifying its own
  signature or secret.

Follow the same shape for GitHub, Jira, Slack and the rest; none is built.
