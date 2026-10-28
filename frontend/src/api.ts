// The JSON the service returns (snake_case, as docs/api.md shows it). The UI reads the same
// endpoints agents read; nothing here is computed server-side for the UI only.

export type Pill = 'green' | 'amber' | 'red' | 'grey' | string;

export interface Link {
  kind: string;
  to?: string;
  from?: string;
}

export interface Stamp {
  by: string;
  kind: string;
  at: string;
}

/** Every record, everywhere: lists, detail, nested in pages. */
export interface RecordJson {
  ref: string;
  type: string;
  title: string;
  status: string;
  pill: Pill;
  line: string | null;
  rev: number;
  fields: Record<string, unknown>;
  created_by: string;
  created_at: string;
  updated_by: string;
  updated_at: string;
  // detail only
  links?: { out: Link[]; in: Link[] };
  stamps?: Record<string, Stamp>;
  stale?: string[];
  review_items?: ReviewItem[];
  superseded_by?: string[];
  sourced_acs?: string[];
}

export interface Revision {
  rev: number;
  ref: string;
  title: string;
  status: string;
  fields: Record<string, unknown>;
  links: string[];
  actor: string;
  actor_kind: string;
  batch_id: string;
  note: string;
  because: string[];
  at: string;
}

// ── initiatives ─────────────────────────────────────────────────────────────

export interface DriftSummary {
  changes: number;
  explained: number;
  unexplained: number;
  pending_gaps: number;
  pending_decisions: number;
  other_changes: number;
}

export interface Initiative {
  slug: string;
  title: string;
  work_item_url: string | null;
  created_by: string;
  created_at: string;
  closed_at: string | null;
  snapshot_hash: string;
  phase: string;
  pill: Pill;
  summary: string;
  spec_snapshot?: { requirement: string; work_item_url: string | null; created_by: string; at: string };
}

/** GET /api/initiatives — one row per initiative. */
export interface InitiativeRow extends Initiative {
  dri: string | null;
  engg: string | null;
  counts: { open_gaps: number; open_decisions: number; tasks: number; tasks_done: number; open_review_items: number };
  baseline: string | null;
  drift: DriftSummary | null;
}

export interface Assignment {
  ref: string;
  person: string;
  role: string;
  scope: string[];
  status: string;
}

export interface GateRule {
  name: string;
  passed: boolean;
  failing: string[];
  detail: string;
  args: Record<string, unknown>;
}

export interface Gate {
  gate: string;
  scope: string;
  target: string | null;
  status: 'PASSED' | 'BLOCKED' | string;
  human_role: string | null;
  text: string;
  rules: GateRule[];
  note: string;
  failing_rules: string[];
}

export interface TaskRow extends RecordJson {
  gate_pr: { status: string; failing_rules: string[] };
  drift: DriftSummary;
}

export interface Baseline {
  ref: string;
  label: string;
  status: string;
  approval: string;
  approved_by: string;
  draft_rev: string;
  members: string[] | number;
  created_at: string;
}

export interface CatalogItem {
  item: string;
  phase: string;
  text: string;
  derived: boolean;
  disposition: 'addressed' | 'not_applicable' | 'UNASSESSED' | string;
  note: string;
  refs: string;
}

/** GET /api/initiatives/{slug} (and the body POST /api/initiatives returns). */
export interface InitiativeState {
  initiative: Initiative;
  phase: string;
  assignments: Assignment[];
  gates: Gate[];
  tasks: TaskRow[];
  counts: Record<string, Record<string, number>>;
  open: { decisions: string[]; gaps: string[]; review_items: number };
  stuck: string[];
  baseline: Baseline | null;
  drift: DriftSummary | null;
  stale: string[];
  catalog: Record<string, CatalogItem[]>;
}

/** GET /api/initiatives/{slug}/draft — touchpoint 1. */
export interface DraftPage {
  initiative: Initiative;
  draft: RecordJson | null;
  decisions: RecordJson[];
  criteria: RecordJson[];
  gaps: RecordJson[];
  catalog: CatalogItem[];
  gate: Gate;
  can_approve: boolean;
  approver: string | null;
  approval_blockers: { rule: string; failing: string[]; detail: string }[];
  approvals: RecordJson[];
  baselines: Baseline[];
  review_items: ReviewItem[];
}

// ── drift ───────────────────────────────────────────────────────────────────

export interface DriftEntry {
  id: string;
  kind: string;
  ref: string;
  type: string;
  rev: number;
  at: string;
  actor: string;
  actor_kind: string;
  summary: string;
  what_moved: string[];
  because: string[];
  explained: boolean;
  explanation: { ref: string | null; ok: boolean; why: string }[];
  related: string[];
  detail: Record<string, unknown>;
  in_scope: boolean;
}

export interface SpecDecision {
  ref: string;
  title: string;
  question: string;
  verdict: string;
  level: string;
  status: string;
}

export interface SpecCriterion {
  ref: string;
  text: string;
  level: string;
  manual: string;
  status: string;
}

export interface Spec {
  draft: Record<string, unknown>;
  decisions: SpecDecision[];
  criteria: SpecCriterion[];
}

export interface DriftApproval {
  ref: string;
  by: string;
  status: string;
  at_sha: string;
  drift_digest: string;
  matches_digest: boolean;
  note: string;
  at: string;
}

export interface DriftReport {
  status: 'NO_BASELINE' | 'CLEAN' | 'EXPLAINED' | 'UNEXPLAINED' | string;
  initiative: string;
  task: string | null;
  baseline: (Omit<Baseline, 'members'> & { members: number }) | null;
  until: string | null;
  scope_refs: string[];
  summary: DriftSummary;
  digest: string;
  entries: DriftEntry[];
  unexplained: string[];
  pending_gaps: { ref: string; title?: string; [k: string]: unknown }[];
  pending_decisions: { ref: string; title?: string; [k: string]: unknown }[];
  spec_diff: {
    draft: Record<string, { added: number; removed: number; diff: string }>;
    decisions: {
      added: { ref: string; verdict: string; status: string }[];
      superseded: { old: string; new: string | null; old_verdict: string; new_verdict: string }[];
      changed: { ref: string; old_verdict: string; new_verdict: string }[];
      unchanged: number;
    };
    criteria: {
      added: { ref: string; text: string; level: string; because: string[] }[];
      retired: { ref: string; text: string; retired_because: string }[];
      changed: { ref: string; old: string; new: string }[];
      unchanged: number;
    };
  } | Record<string, never>;
  approved_spec: Spec | Record<string, never>;
  current_spec: Spec | Record<string, never>;
  approvals: DriftApproval[];
}

/** GET /api/initiatives/{slug}/tasks/{ref} — touchpoint 3. */
export interface TaskPage {
  task: RecordJson;
  gate: Gate;
  drift: DriftReport;
  approver: string | null;
  test_runs: RecordJson[];
  findings: RecordJson[];
  deploys: RecordJson[];
}

export interface DeployGuard {
  decision: 'GO' | 'NO-GO' | string;
  initiative: string;
  task: string;
  sha: string;
  environment: string;
  reasons: string[];
  checks: { name: string; passed: boolean; detail: string }[];
}

// ── the human lane ──────────────────────────────────────────────────────────

export interface GapOption {
  key: string;
  label: string;
  consequence?: string;
}

export interface DecisionOption {
  name: string;
  consequences?: string;
  cost_risk?: string;
}

interface InboxBase {
  key: string;
  initiative: string;
  initiative_title: string;
  ref: string;
  route: { person: string | null; role: string | null; domain: string | null; fallback: boolean };
  person: string | null;
  since: string | null;
  age_hours: number;
  sla_hours: number;
  due_at: string | null;
  overdue: boolean;
  priority: number;
  title: string;
}

export interface GapItem extends InboxBase {
  kind: 'gap';
  record: RecordJson;
  question: string;
  context: string;
  options: GapOption[];
  recommendation: string | null;
  recommendation_why: string | null;
  blocks: string[];
  level: string;
}

export interface DecisionItem extends InboxBase {
  kind: 'decision';
  record: RecordJson;
  question: string;
  options: DecisionOption[];
  provisional_verdict: string | null;
  level: string;
  blocks: string[];
}

export interface ApprovalItem extends InboxBase {
  kind: 'approval';
  gate: string;
  role: string;
  target: string;
  draft_status?: string;
  pr_url?: string | null;
  pr_sha?: string | null;
  drift?: DriftSummary;
  digest?: string;
  stale_approvals?: string[];
}

export interface ReviewInboxItem extends InboxBase {
  kind: 'review_item';
  review_item_id: number;
  target: string;
  cause: string;
  what_moved: string;
}

export interface ManualAcItem extends InboxBase {
  kind: 'manual_ac';
  text: string;
  at_sha: string | null;
}

export type InboxItem = GapItem | DecisionItem | ApprovalItem | ReviewInboxItem | ManualAcItem;

export interface Inbox {
  person: string;
  count: number;
  overdue: number;
  counts: Record<string, number>;
  items: InboxItem[];
}

export interface Person {
  person: string;
  roles: { initiative: string; role: string }[];
  inbox: number;
}

export interface WorklistItem {
  key: string;
  kind: string;
  lane: 'human' | 'agent' | string;
  initiative: string;
  ref: string | null;
  title: string;
  why: string;
  person: string | null;
  priority: number;
  overdue?: boolean;
  sla_hours?: number;
  lease: { holder: string; expires_at?: string; [k: string]: unknown } | null;
}

export interface Worklist {
  initiative: string;
  count: number;
  groups: Record<string, WorklistItem[]>;
  items: WorklistItem[];
}

export interface ReviewItem {
  id: number;
  target: string;
  cause: string;
  cause_rev: number;
  what_moved: string;
  path: string;
  status: string;
  route_to: string | null;
  domain: string | null;
  note: string;
  created_by: string;
  created_at: string;
  resolved_by: string | null;
  resolved_at: string | null;
}

export interface ActivityEntry {
  kind: 'revision' | 'review_item' | string;
  at: string;
  ref: string;
  type: string;
  rev?: number;
  action: string;
  title: string;
  status: string;
  actor: string;
  actor_kind: string | null;
  note: string;
  because: string[];
  batch_id?: string;
  review_item_id?: number;
}

/** Every human write returns the write path's result. */
export interface WriteResult {
  ok: boolean;
  batch_id: string;
  results: { index: number; ref: string; type: string; action: string; rev: number; status: string; errors: string[]; warnings: string[] }[];
  minted: Record<string, string>;
  review_items: string[];
  stale: string[];
  gates_changed: string[];
  baseline: string | null;
  replayed: boolean;
}

// ── blueprint ───────────────────────────────────────────────────────────────

export interface Lifecycle {
  phases: string[];
  roles: string[];
  status_rules: Record<string, { rule: string; text: string; field?: string }>;
  catalogs: Record<string, { item: string; phase: string; text: string; derived: boolean }[]>;
  gates: Record<string, { scope: string; human: string | null; text: string; rules: unknown[]; [k: string]: unknown }>;
  deploy_guard: Record<string, unknown>;
  routing: { by_domain: Record<string, string>; gates: Record<string, string>; fallback: string; sla_hours: Record<string, number>; escalate_to: string };
  handoff: Record<string, number>;
}
