from typing import Annotated, List, Optional

from fastapi import Depends

from app.base.controllers.base_controller import BaseController
from app.core.utils.actor import Actor
from app.exceptions import ValidationException
from app.initiatives.requests.requests import WriteRequest
from app.initiatives.schemas.write import WriteResult
from app.initiatives.services.record_service import RecordService, parse_op
from app.initiatives.services.views import record_json, revision_json


class RecordController(BaseController):
    def __init__(self, service: Annotated[RecordService, Depends()]):
        self.service = service

    def list_records(self, slug: str, type_: Optional[str], status: Optional[str], query: Optional[str], since: Optional[str]) -> List[dict]:
        g = self.service.graph(self.service.initiative(slug))
        return [record_json(r, g) for r in self.service.find(g, type_, status, query, since)]

    def get_record(self, slug: str, ref: str) -> dict:
        initiative = self.service.initiative(slug)
        self.service.get(initiative, ref)
        g = self.service.graph(initiative)
        return record_json(g.by_ref[ref], g, detail=True)

    def history(self, slug: str, ref: str) -> List[dict]:
        record = self.service.get(self.service.initiative(slug), ref)
        return [revision_json(rev) for rev in self.service.history(record)]

    def write(self, slug: str, body: WriteRequest, actor: Actor) -> dict:
        ops = [parse_op(raw) for raw in body.ops]
        return self.respond(self.service.write(slug, ops, actor, body.batch_id))

    @staticmethod
    def respond(result: WriteResult) -> dict:
        """422 with the full result in `error_data` — every op's errors at once."""
        if not result.ok:
            raise ValidationException(message="Write rejected — nothing was saved", error_data=result.to_dict())
        return result.to_dict()
