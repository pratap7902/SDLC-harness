import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import type { AdoPreview, InitiativeState } from '../api';
import { ApiError, getJson, postJson, useRefresh } from '../lib/api';
import { ROLE_LABEL, nm } from '../lib/format';
import { usePersona } from '../lib/persona';
import { useToast } from '../lib/toast';
import { Banner, Card, Field } from '../components/ui';
import { PageHeader } from '../components/PageHeader';

const OTHER = '__other__';

/** A person: the people the service knows (anyone with an assignment), or a new handle. */
function PersonPicker({ id, value, onChange, required, hint, label }: { id: string; value: string; onChange: (v: string) => void; required?: boolean; hint: string; label: string }) {
  const { people } = usePersona();
  const known = people.some((p) => p.person === value);
  const [other, setOther] = useState(false);
  const showInput = other || (!!value && !known);
  return (
    <Field label={label} htmlFor={id} required={required} hint={hint}>
      <select
        id={id}
        className="input"
        value={showInput ? OTHER : value}
        onChange={(e) => {
          if (e.target.value === OTHER) {
            setOther(true);
            onChange('');
          } else {
            setOther(false);
            onChange(e.target.value);
          }
        }}
      >
        <option value="">{required ? 'Choose…' : 'Not needed'}</option>
        {people.map((p) => (
          <option key={p.person} value={p.person}>
            {p.name && p.name !== p.person ? `${p.name} (${p.person})` : nm(p.person)}
            {p.roles.length ? ` · ${Array.from(new Set(p.roles.map((r) => ROLE_LABEL[r.role] || r.role))).join(', ')}` : ''}
          </option>
        ))}
        <option value={OTHER}>Someone else…</option>
      </select>
      {showInput && (
        <input aria-label={`${label}: handle`} className="input font-mono" placeholder="their handle, e.g. arjun" value={value} onChange={(e) => onChange(e.target.value.trim().toLowerCase())} />
      )}
    </Field>
  );
}

export default function NewFeaturePage() {
  const navigate = useNavigate();
  const say = useToast();
  const { bump } = useRefresh();
  const [form, setForm] = useState({ title: '', requirement: '', work_item_url: '', dri: '', engg: '', product: '', design: '', qa: '' });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [ado, setAdo] = useState({ ref: '', busy: false, note: '' });
  const set = (k: keyof typeof form) => (v: string) => {
    setForm((f) => ({ ...f, [k]: v }));
    setError('');
  };

  // Paste an Azure DevOps link or id: the service reads the work item and fills the form
  // (title, requirement from description + acceptance criteria, link, DRI / engg when they
  // are in the people directory). Starting still goes through the same intake.
  const prefill = async () => {
    if (!ado.ref.trim()) return;
    setAdo((a) => ({ ...a, busy: true, note: '' }));
    try {
      const p = await getJson<AdoPreview>(`/api/azure-devops/preview?work_item=${encodeURIComponent(ado.ref.trim())}`);
      setForm((f) => ({
        ...f,
        title: p.title || f.title,
        requirement: p.requirement,
        work_item_url: p.work_item_url,
        dri: p.people.dri || f.dri,
        engg: p.people.engg || f.engg,
      }));
      const unmatched = Object.entries(p.unmatched).map(([role, email]) => `${ROLE_LABEL[role] || role}: ${email} is not in the people directory`);
      const already = p.already_imported.length ? [`already imported as feature ${p.already_imported.join(', ')}`] : [];
      setAdo({ ref: ado.ref, busy: false, note: [`Filled from work item ${p.work_item_id} (rev ${p.rev}).`, ...already, ...unmatched].join(' · ') });
      setError('');
    } catch (err) {
      setAdo((a) => ({ ...a, busy: false, note: '' }));
      setError((err as Error).message);
    }
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const miss: string[] = [];
    if (!form.title.trim()) miss.push('a title');
    if (!form.requirement.trim()) miss.push('the requirement');
    if (!form.dri) miss.push('a DRI');
    if (!form.engg) miss.push('an engineering owner');
    if (miss.length) {
      setError(`Add ${miss.join(', ')} to start.`);
      return;
    }
    if (form.work_item_url.trim() && !/^https?:\/\/\S+$/.test(form.work_item_url.trim())) {
      setError('The work item must be a link (https://dev.azure.com/…), or left empty.');
      return;
    }
    setBusy(true);
    try {
      const body: Record<string, string> = { title: form.title.trim(), requirement: form.requirement.trim(), dri: form.dri, engg: form.engg };
      if (form.work_item_url.trim()) body.work_item_url = form.work_item_url.trim();
      for (const k of ['product', 'design', 'qa'] as const) if (form[k]) body[k] = form[k];
      const state = await postJson<InitiativeState>('/api/initiatives', body);
      say(`Feature started as ${state.initiative.slug}. The drafting agent will route its questions to the people you chose.`);
      bump();
      navigate(`/features/${state.initiative.id}`);
    } catch (err) {
      const errors = err instanceof ApiError ? ((err.data.errors as string[] | undefined) || []) : [];
      setError([(err as Error).message, ...errors.filter((x) => !(err as Error).message.includes(x))].join(' · '));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader title="Start a feature">
        <p className="m-0 text-ink-muted max-w-[72ch]">
          Describe what you want. An agent writes the draft (HLD, LLD and acceptance criteria) and asks the right people when it's unsure. The DRI approves the draft before any code is written.
        </p>
      </PageHeader>
      <div className="flex flex-wrap gap-[22px] items-start">
        <form className="card flex-[999_1_560px] min-w-0 flex flex-col gap-4 px-6 py-[22px]" onSubmit={submit} noValidate>
          <Field label="Start from Azure DevOps" htmlFor="fadoref" optional="optional" hint="A work item link or id fills the form below.">
            <div className="flex gap-2">
              <input
                id="fadoref"
                className="input font-mono flex-1"
                value={ado.ref}
                onChange={(e) => setAdo({ ...ado, ref: e.target.value })}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    prefill();
                  }
                }}
                placeholder="https://dev.azure.com/your-org/your-project/_workitems/edit/1234 or 1234"
              />
              <button type="button" className="btn" onClick={prefill} disabled={ado.busy || !ado.ref.trim()}>
                {ado.busy ? 'Reading…' : 'Fill from work item'}
              </button>
            </div>
            {ado.note && <span className="small">{ado.note}</span>}
          </Field>
          <Field label="Title" htmlFor="ftitle" required>
            <input id="ftitle" className="input" type="text" value={form.title} onChange={(e) => set('title')(e.target.value)} placeholder="e.g. Order events for downstream consumers" />
          </Field>
          <Field label="Requirement" htmlFor="freq" required>
            <span className="small" id="freq-help">
              What users need and what done looks like. Markdown. Paste the PRD text if you have one.
            </span>
            <textarea id="freq" className="input min-h-[150px]" aria-describedby="freq-help" value={form.requirement} onChange={(e) => set('requirement')(e.target.value)} />
          </Field>
          <Field label="Azure DevOps work item" htmlFor="fado" optional="optional" hint="Linked for reference. The requirement above is what gets pinned.">
            <input
              id="fado"
              className="input font-mono"
              type="url"
              value={form.work_item_url}
              onChange={(e) => set('work_item_url')(e.target.value)}
              placeholder="https://dev.azure.com/your-org/your-project/_workitems/edit/1234"
            />
          </Field>
          <fieldset className="border-0 p-0 m-0">
            <legend className="font-semibold text-[13px] mb-2.5">People</legend>
            <div className="grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(170px,1fr))]">
              <PersonPicker id="fdri" label="DRI" required value={form.dri} onChange={set('dri')} hint="Approves the draft" />
              <PersonPicker id="fengg" label="Engineering" required value={form.engg} onChange={set('engg')} hint="Engineering calls, PR reviews" />
              <PersonPicker id="fprod" label="Product" value={form.product} onChange={set('product')} hint="Scope questions" />
              <PersonPicker id="fdesign" label="Design" value={form.design} onChange={set('design')} hint="UX questions" />
              <PersonPicker id="fqa" label="QA" value={form.qa} onChange={set('qa')} hint="Signs manual criteria" />
            </div>
          </fieldset>
          {error && (
            <Banner tone="bad" role="alert">
              {error}
            </Banner>
          )}
          <div className="flex flex-wrap gap-3 items-center">
            <button type="submit" className="btn btn-primary btn-lg" disabled={busy}>
              {busy ? 'Starting…' : 'Start feature'}
            </button>
            <Link to="/" className="btn btn-link no-underline">
              Cancel
            </Link>
          </div>
        </form>
        <Card as="aside" className="flex-[1_1_300px] min-w-0 px-[18px] py-4 flex flex-col gap-3">
          <h2 className="text-[17px]">What happens next</h2>
          <ol className="m-0 pl-5 flex flex-col gap-2.5 text-[13px] list-decimal">
            <li>
              <strong>Draft.</strong> An agent writes HLD, LLD, decisions and acceptance criteria from your requirement and the knowledge base.
            </li>
            <li>
              <strong>Questions.</strong> Anything it can't answer goes to the right person: scope to product, trade-offs to engineering.
            </li>
            <li>
              <strong>Approval.</strong> The DRI approves the draft once. That's the spec the build is checked against.
            </li>
            <li>
              <strong>Build.</strong> Agents split it into tasks, write code and tests, and raise PRs. Changes of plan come back as questions.
            </li>
            <li>
              <strong>Review.</strong> Each PR review shows only what changed since approval, and why.
            </li>
          </ol>
        </Card>
      </div>
    </>
  );
}
