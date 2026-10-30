"""The knowledge base over REST (the MCP tools kb_search / kb_get are the agent's way in)."""

from fastapi import APIRouter

from app.knowledge.services.outline import OutlineClient

router = APIRouter(tags=["knowledge"])


@router.get("/kb/search")
def kb_search(q: str, limit: int = 8):
    return [h.to_dict() for h in OutlineClient().search(q, limit)]


@router.get("/kb/doc")
def kb_doc(citation: str):
    """`citation`: kb:outline/<doc-id>[#anchor], or a bare document id."""
    return OutlineClient().get(citation).to_dict()
