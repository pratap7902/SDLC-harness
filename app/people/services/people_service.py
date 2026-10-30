"""The canonical people directory: one person per human, however many platforms they are
on. Integrations feed it directory entries (Teams users today); the merge is by email
(PEOPLE_MATCH_KEY), and anything it cannot merge on its own goes to the review list —
never an automatic duplicate.

Merge rules for an entry (source, external_id, email, name, active):
1. The account is already linked → refresh its email / name / active. If its email now
   belongs to a DIFFERENT person → conflict (the link is kept, an admin decides).
2. Not linked, its email matches exactly one person → link it — unless that person already
   has another account on the same source (conflict: one human, two accounts).
3. Two entries of one sync share an email → conflict for both (none is linked).
4. No email, or no person has it → unmatched.
An open review row is not duplicated by the next sync."""

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from app.core.utils.time import utcnow
from app.exceptions import ConflictException, NotFoundException, ValidationException
from app.people.models.person import PeopleReviewItem, Person, PersonIdentity
from app.people.repositories.people_repository import PeopleRepository, norm_email
from config.settings import settings


@dataclass
class DirectoryEntry:
    """A user as an integration lists it (normalized)."""

    external_id: str
    display_name: str = ""
    email: Optional[str] = None
    active: bool = True
    avatar_url: Optional[str] = None


@dataclass
class SyncResult:
    source: str
    seen: int = 0
    linked: List[str] = field(default_factory=list)  # handles newly linked
    updated: int = 0
    unmatched: List[str] = field(default_factory=list)  # external ids sent to review
    conflicts: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "seen": self.seen,
            "linked": self.linked,
            "updated": self.updated,
            "unmatched": self.unmatched,
            "conflicts": self.conflicts,
        }


def person_json(p: Person, identities: List[PersonIdentity]) -> dict:
    return {
        "id": p.id,
        "handle": p.handle,
        "name": p.name,
        "email": p.email,
        "active": bool(p.active),
        "identities": [
            {"source": i.source, "external_id": i.external_id, "email": i.email, "active": bool(i.active)}
            for i in identities
        ],
    }


def review_json(r: PeopleReviewItem) -> dict:
    return {
        "id": r.id,
        "source": r.source,
        "external_id": r.external_id,
        "email": r.email,
        "display_name": r.display_name,
        "reason": r.reason,
        "detail": r.detail,
        "candidates": list(r.candidates or []),
        "status": r.status,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "resolved_by": r.resolved_by,
    }


class PeopleService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = PeopleRepository(db)

    # ── lookups (identity providers, inbound actions) ────────────────────

    def by_email(self, email: Optional[str]) -> Optional[Person]:
        return self.repo.by_email(email)

    def by_identity(self, source: str, external_id: str) -> Optional[Person]:
        identity = self.repo.identity(source, external_id)
        if identity is None or not identity.active:
            return None
        person = self.repo.get(identity.person_id)
        return person if person is not None and person.active else None

    def identity_of(self, handle: str, source: str) -> Optional[PersonIdentity]:
        person = self.repo.by_handle(handle)
        if person is None or not person.active:
            return None
        identity = self.repo.identity_of(person.id, source)
        return identity if identity is not None and identity.active else None

    def resolve_handle(self, value: str) -> Optional[str]:
        """A handle, or an email → the canonical handle."""
        value = (value or "").strip()
        if not value:
            return None
        if "@" in value:
            person = self.repo.by_email(value)
            return person.handle if person else None
        person = self.repo.by_handle(value)
        return person.handle if person else None

    # ── the directory ────────────────────────────────────────────────────

    def directory(self) -> Dict[str, dict]:
        idents: Dict[int, List[PersonIdentity]] = {}
        for i in self.repo.identities():
            idents.setdefault(i.person_id, []).append(i)
        return {p.handle: person_json(p, idents.get(p.id, [])) for p in self.repo.all()}

    def create(self, handle: str, name: str = "", email: Optional[str] = None) -> Person:
        handle = (handle or "").strip()
        if not handle or len(handle) > 80 or any(c.isspace() for c in handle):
            raise ValidationException(message="handle: 1–80 characters, no spaces (what assignments name)")
        if self.repo.by_handle(handle):
            raise ConflictException(message=f"person {handle} exists", error_code="PERSON_EXISTS")
        email = norm_email(email)
        if email and self.repo.by_email(email):
            raise ConflictException(message=f"{email} already belongs to {self.repo.by_email(email).handle}", error_code="EMAIL_TAKEN")
        now = utcnow()
        return self.repo.add(Person(handle=handle, name=(name or handle)[:200], email=email, active=True, created_at=now, updated_at=now))

    # ── sync ─────────────────────────────────────────────────────────────

    def sync(self, source: str, entries: Iterable[DirectoryEntry]) -> SyncResult:
        if settings.people.PEOPLE_MATCH_KEY != "email":
            raise ValidationException(message="PEOPLE_MATCH_KEY: only `email` is supported")
        entries = [e for e in entries if (e.external_id or "").strip()]
        result = SyncResult(source=source, seen=len(entries))
        by_email: Dict[str, List[DirectoryEntry]] = {}
        for e in entries:
            if norm_email(e.email):
                by_email.setdefault(norm_email(e.email), []).append(e)
        now = utcnow()
        for e in entries:
            email = norm_email(e.email)
            identity = self.repo.identity(source, e.external_id)
            if identity is not None:
                identity.email, identity.display_name, identity.active, identity.synced_at = email, (e.display_name or "")[:200], bool(e.active), now
                result.updated += 1
                owner = self.repo.by_email(email)
                if owner is not None and owner.id != identity.person_id:
                    linked = self.repo.get(identity.person_id)
                    self._review(e, source, "conflict", f"linked to {linked.handle if linked else '?'}, but {email} belongs to {owner.handle}", [owner.handle] + ([linked.handle] if linked else []), result)
                continue
            if email and len(by_email.get(email, [])) > 1:
                others = [x.external_id for x in by_email[email] if x is not e]
                self._review(e, source, "conflict", f"{email} is shared with {', '.join(others)} on {source}", [], result)
                continue
            person = self.repo.by_email(email)
            if person is None:
                self._review(e, source, "unmatched", "no email" if not email else f"no person has {email}", [], result)
                continue
            existing = self.repo.identity_of(person.id, source)
            if existing is not None:
                self._review(e, source, "conflict", f"{person.handle} already has {source} account {existing.external_id}", [person.handle], result)
                continue
            self.repo.add_identity(
                PersonIdentity(person_id=person.id, source=source, external_id=e.external_id, email=email, display_name=(e.display_name or "")[:200], active=bool(e.active), synced_at=now)
            )
            if not person.name or person.name == person.handle:
                person.name = (e.display_name or person.name)[:200]
            result.linked.append(person.handle)
        self.db.flush()
        return result

    def _review(self, e: DirectoryEntry, source: str, reason: str, detail: str, candidates: List[str], result: SyncResult) -> None:
        (result.conflicts if reason == "conflict" else result.unmatched).append(e.external_id)
        open_item = self.repo.open_review_for(source, e.external_id)
        if open_item is not None:
            open_item.reason, open_item.detail, open_item.candidates = reason, detail[:400], sorted(set(candidates))
            open_item.email, open_item.display_name = norm_email(e.email), (e.display_name or "")[:200]
            return
        self.repo.add_review(
            PeopleReviewItem(
                source=source,
                external_id=e.external_id,
                email=norm_email(e.email),
                display_name=(e.display_name or "")[:200],
                reason=reason,
                detail=detail[:400],
                candidates=sorted(set(candidates)),
                status="open",
                created_at=utcnow(),
            )
        )

    # ── the review list ──────────────────────────────────────────────────

    def review(self, status: Optional[str] = "open") -> List[PeopleReviewItem]:
        return self.repo.review(None if status in (None, "", "all") else status)

    def resolve_review(self, item_id: int, action: str, by: str, handle: Optional[str] = None, name: Optional[str] = None) -> PeopleReviewItem:
        """link (to an existing person) · create (a person from the entry) · ignore."""
        item = self.repo.review_item(item_id)
        if item is None:
            raise NotFoundException(message=f"No people review item {item_id}")
        if item.status != "open":
            raise ValidationException(message=f"review item {item_id} is already {item.status}")
        if action not in ("link", "create", "ignore"):
            raise ValidationException(message="action: link | create | ignore")
        if action in ("link", "create"):
            if action == "create":
                person = self.create(handle or "", name or item.display_name, item.email)
            else:
                person = self.repo.by_handle(handle or "")
                if person is None:
                    raise NotFoundException(message=f"No person {handle}")
            current = self.repo.identity(item.source, item.external_id)
            if current is not None:
                current.person_id = person.id  # an admin re-points a conflicting link
            else:
                other = self.repo.identity_of(person.id, item.source)
                if other is not None:
                    raise ConflictException(message=f"{person.handle} already has {item.source} account {other.external_id}", error_code="IDENTITY_TAKEN")
                self.repo.add_identity(
                    PersonIdentity(person_id=person.id, source=item.source, external_id=item.external_id, email=item.email, display_name=item.display_name, active=True, synced_at=utcnow())
                )
            if person.email is None and item.email and self.repo.by_email(item.email) is None:
                person.email = item.email
        item.status = {"link": "linked", "create": "created", "ignore": "ignored"}[action]
        item.resolved_by, item.resolved_at = by, utcnow()
        self.db.flush()
        return item
