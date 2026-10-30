"""Azure DevOps Boards ↔ the record service.

Import   a work item (id or link) → StartFeature → IntakeService.start (the same intake the
         web form and MCP create_initiative use). Title → title; description and
         acceptance criteria → the requirement markdown; the work item link →
         work_item_url; the DRI / engg from the configured identity fields when their email
         is a person in the people directory (the caller can override either).
Webhook  workitem.updated on a LINKED item whose description / acceptance criteria moved →
         a `prd_drift` gap routed to the DRI ("re-snapshot the requirement?"). Nothing is
         re-pinned automatically. An update to a task's pushed child item → the task's
         `tracker_edited: yes` (the record here still wins; the worklist asks someone to
         reconcile).
Push     one-way: each task with no tracker_id becomes a child work item of the
         initiative's work item; tracker_id / tracker_url are written back through the
         write path (as the service). Never pulled back."""

import hmac
from base64 import b64decode
from typing import Dict, List, Mapping, Optional

from sqlalchemy.orm import Session

from app.azure_devops.services.client import AdoClient, html_to_markdown, work_item_id
from app.core.utils.actor import SERVICE, Actor
from app.exceptions import ConflictException, UnauthorizedException, ValidationException
from app.initiatives.schemas.write import WriteOp
from app.initiatives.services.initiative_service import InitiativeService, StartFeature
from app.initiatives.services.record_service import RecordService
from app.people.services.people_service import PeopleService
from config.settings import settings

ADO_ACTOR = SERVICE.with_agent("azure-devops")
DRIFT_FIELDS = ("System.Description", "Microsoft.VSTS.Common.AcceptanceCriteria")
ASKED_BY = "azure-devops"


def _identity_email(value) -> Optional[str]:
    """An ADO identity field value → its email (`uniqueName`, or "Name <email>")."""
    if isinstance(value, dict):
        return (value.get("uniqueName") or value.get("mailAddress") or "").strip() or None
    if isinstance(value, str) and "<" in value and value.endswith(">"):
        return value[value.rindex("<") + 1 : -1].strip() or None
    return None


class BoardsService:
    def __init__(self, db: Session, client: Optional[AdoClient] = None):
        self.db = db
        self.records = RecordService(db)
        self.client = client or AdoClient()
        self.people = PeopleService(db)

    # ── import ───────────────────────────────────────────────────────────

    def preview(self, ref) -> dict:
        """What an import would start (the Start feature form prefills from this)."""
        item_id = work_item_id(ref)
        item = self.client.get(item_id)
        fields = item.get("fields") or {}
        title = (fields.get("System.Title") or "").strip()
        description = html_to_markdown(fields.get("System.Description"))
        criteria = html_to_markdown(fields.get("Microsoft.VSTS.Common.AcceptanceCriteria"))
        parts = [f"# {title}"]
        if description:
            parts.append(description)
        if criteria:
            parts.append("## Acceptance criteria\n\n" + criteria)
        parts.append(f"_Imported from Azure DevOps work item {item_id} (rev {item.get('rev', '?')})._")
        out = {
            "work_item_id": item_id,
            "work_item_type": fields.get("System.WorkItemType"),
            "rev": item.get("rev"),
            "title": title,
            "requirement": "\n\n".join(parts),
            "work_item_url": ((item.get("_links") or {}).get("html") or {}).get("href") or self.client.web_url(item_id),
            "people": {},
            "unmatched": {},
            "already_imported": self._linked(item_id),
        }
        s = settings.azure_devops
        for role, field_name in (("dri", s.ADO_DRI_FIELD), ("engg", s.ADO_ENGG_FIELD)):
            if not field_name:
                continue
            email = _identity_email(fields.get(field_name))
            handle = self.people.resolve_handle(email) if email else None
            if handle:
                out["people"][role] = handle
            elif email:
                out["unmatched"][role] = email
        return out

    def import_item(self, ref, actor: Actor, overrides: Optional[Dict[str, Optional[str]]] = None) -> dict:
        preview = self.preview(ref)
        if preview["already_imported"]:
            raise ConflictException(
                message=f"work item {preview['work_item_id']} is already initiative {preview['already_imported'][0]}",
                error_code="ALREADY_IMPORTED",
            )
        overrides = {k: v for k, v in (overrides or {}).items() if v}
        people = {**preview["people"], **{k: overrides[k] for k in ("dri", "engg", "product", "design", "qa") if k in overrides}}
        missing = [r for r in ("dri", "engg") if not people.get(r)]
        if missing:
            hint = "; ".join(f"{r}: {preview['unmatched'][r]} is not in the people directory" for r in missing if r in preview["unmatched"])
            raise ValidationException(
                message=f"{' and '.join(missing)} not set by the work item — pass {', '.join(missing)}" + (f" ({hint})" if hint else ""),
                error_data={"preview": preview},
            )
        req = StartFeature(
            title=preview["title"] or f"Work item {preview['work_item_id']}",
            requirement=preview["requirement"],
            dri=people["dri"],
            engg=people["engg"],
            slug=overrides.get("slug"),
            work_item_url=preview["work_item_url"],
            product=people.get("product"),
            design=people.get("design"),
            qa=people.get("qa"),
        )
        return InitiativeService(self.records).start(req, actor)

    def _linked(self, item_id: int) -> List[int]:
        out = []
        for i in self.records.initiatives.list_ordered():
            try:
                if i.work_item_url and work_item_id(i.work_item_url) == item_id:
                    out.append(i.id)
            except ValidationException:
                continue
        return out

    # ── push tasks ───────────────────────────────────────────────────────

    def push_tasks(self, initiative_key) -> dict:
        initiative = self.records.initiative(initiative_key)
        if not initiative.work_item_url:
            raise ValidationException(message=f"{initiative.slug} has no Azure DevOps work item to push tasks under")
        parent = work_item_id(initiative.work_item_url)
        g = self.records.graph(initiative)
        pushed, skipped = [], []
        base = settings.people.PUBLIC_BASE_URL.rstrip("/")
        for t in g.of_type("task"):
            if g.f(t, "tracker_id"):
                skipped.append(t.ref)
                continue
            desc = (
                f"<p>{g.f(t, 'goal', '')}</p><p>Implements {', '.join(g.f(t, 'implements') or [])}; "
                f"covers {', '.join(g.f(t, 'covers') or [])}.</p>"
                f"<p>The SDLC record is the source of truth: <a href=\"{base}/features/{initiative.id}/tasks/{t.ref}\">{t.ref}</a>. "
                "Edits here are not synced back.</p>"
            )
            child = self.client.create_child(parent, f"{t.ref}: {t.title}", desc)
            url = ((child.get("_links") or {}).get("html") or {}).get("href") or self.client.web_url(child["id"])
            result = self.records.write(
                str(initiative.id),
                [WriteOp(ref=t.ref, fields={"tracker_id": str(child["id"]), "tracker_url": url}, note=f"pushed to Azure DevOps {child['id']}")],
                ADO_ACTOR,
            )
            if not result.ok:
                raise ValidationException(message="could not store the tracker id", error_data=result.to_dict())
            pushed.append({"task": t.ref, "work_item_id": child["id"], "url": url})
        return {"initiative_id": initiative.id, "parent": parent, "pushed": pushed, "skipped": skipped}

    # ── webhook ──────────────────────────────────────────────────────────

    @staticmethod
    def verify(headers: Mapping[str, str]) -> None:
        secret = settings.azure_devops.ADO_WEBHOOK_SECRET
        if not secret:
            raise UnauthorizedException(message="Azure DevOps webhook is not configured (ADO_WEBHOOK_SECRET)", error_code="HOOK_DISABLED")
        given = headers.get("x-srs-hook-secret") or ""
        auth = headers.get("authorization") or ""
        if not given and auth.lower().startswith("basic "):
            try:
                given = b64decode(auth[6:].strip()).decode().partition(":")[2]
            except ValueError:
                given = ""
        if not given or not hmac.compare_digest(given.encode(), secret.encode()):
            raise UnauthorizedException(message="bad webhook secret", error_code="BAD_HOOK_SECRET")

    def handle_event(self, headers: Mapping[str, str], event: dict) -> dict:
        self.verify(headers)
        kind = event.get("eventType") or ""
        resource = event.get("resource") or {}
        if kind != "workitem.updated":
            return {"event": kind, "handled": []}
        item_id = int(resource.get("workItemId") or resource.get("id") or 0)
        changed = set((resource.get("fields") or {}).keys())
        handled = []
        if changed & set(DRIFT_FIELDS):
            for iid in self._linked(item_id):
                gap = self._raise_prd_drift(iid, item_id, resource, sorted(changed & set(DRIFT_FIELDS)))
                if gap:
                    handled.append({"initiative_id": iid, "gap": gap})
        if changed - {"System.Rev", "System.ChangedDate", "System.Watermark", "System.AuthorizedDate", "System.RevisedDate", "System.ChangedBy", "System.AuthorizedAs", "System.PersonId"}:
            handled += self._mark_tracker_edited(item_id)
        return {"event": kind, "work_item_id": item_id, "handled": handled}

    def _raise_prd_drift(self, iid: int, item_id: int, resource: dict, fields: List[str]) -> Optional[str]:
        initiative = self.records.initiative(iid)
        g = self.records.graph(initiative)
        if g.f("initiative", "closed_because"):
            return None
        for gap in g.of_type("gap"):
            if gap.status == "OPEN" and g.f(gap, "kind") == "prd_drift" and g.f(gap, "asked_by") == ASKED_BY:
                return None  # one open question covers every later edit
        rev = (resource.get("revision") or {}).get("rev") or resource.get("rev")
        changes = []
        for name in fields:
            diff = (resource.get("fields") or {}).get(name) or {}
            label = "Description" if name == "System.Description" else "Acceptance criteria"
            new = html_to_markdown(diff.get("newValue"))[:1500]
            changes.append(f"**{label}** now reads:\n\n{new or '(empty)'}")
        by = ((resource.get("revisedBy") or {}).get("displayName")) or "someone"
        blocks = ["draft"] if g.get("draft") is not None else []
        op = WriteOp(
            type="gap",
            title=f"Work item {item_id} changed after the requirement was pinned",
            fields={
                "question": f"Azure DevOps work item {item_id} was edited (rev {rev or '?'}) after this feature's requirement was pinned. Re-snapshot the requirement?",
                "kind": "prd_drift",
                "domain": "product",
                "asked_by": ASKED_BY,
                "why_now": f"{by} changed {', '.join('the description' if f == 'System.Description' else 'the acceptance criteria' for f in fields)} in Azure DevOps",
                "context": "\n\n".join(changes) + f"\n\nThe pinned requirement is unchanged until someone re-pins it (Feature page → re-pin). Work item: {initiative.work_item_url}",
                "options": [
                    {"key": "repin", "label": "Re-snapshot the requirement", "consequence": "the DRI re-pins; the drift report shows the re-pin"},
                    {"key": "keep", "label": "Keep the pinned requirement", "consequence": "the ADO edit does not change this feature"},
                ],
                "blocks": blocks,
            },
            note="raised by the Azure DevOps webhook",
        )
        result = self.records.write(str(iid), [op], ADO_ACTOR)
        if not result.ok:
            raise ValidationException(message="could not raise the prd_drift gap", error_data=result.to_dict())
        return result.results[0].ref

    def _mark_tracker_edited(self, item_id: int) -> List[dict]:
        out = []
        for initiative in self.records.initiatives.list_ordered():
            g = self.records.graph(initiative)
            for t in g.of_type("task"):
                if g.f(t, "tracker_id") == str(item_id) and g.f(t, "tracker_edited") != "yes":
                    result = self.records.write(str(initiative.id), [WriteOp(ref=t.ref, fields={"tracker_edited": "yes"}, note=f"edited in Azure DevOps ({item_id})")], ADO_ACTOR)
                    if result.ok:
                        out.append({"initiative_id": initiative.id, "task": t.ref, "tracker_edited": "yes"})
        return out
