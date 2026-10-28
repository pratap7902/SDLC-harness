"""The React app (`frontend/dist`, built by `make frontend`) at the
real page paths. Built files are served as they are (`/assets/…`); every page path gets
`index.html`, so the app's own router resolves it. `/api`, `/static` and `/mcp` are not
touched: the page paths are listed, never a catch-all."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

DIST_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"

# Every page the app serves. A new page is a route here and in the frontend router.
PAGE_PATHS = (
    "/",
    "/new",
    "/inbox",
    "/standards",
    "/learnings",
    "/blueprint",
    "/features/{initiative_id}",
    "/features/{initiative_id}/draft",
    "/features/{initiative_id}/drift",
    "/features/{initiative_id}/tasks/{ref}",
    "/features/{initiative_id}/records/{ref}",
    "/features/{initiative_id}/reviews",
    "/features/{initiative_id}/activity",
)

router = APIRouter(include_in_schema=False)


def _index():
    index = DIST_DIR.resolve() / "index.html"
    if not index.is_file():
        return JSONResponse({"detail": "The frontend is not built. Build frontend/ into frontend/dist."}, status_code=404)
    # The page must be re-validated on every visit, or a browser keeps a bundle that no
    # longer exists after a deploy; the hashed assets below can be cached for good.
    return FileResponse(index, headers={"Cache-Control": "no-cache"})


def page(initiative_id: str = "", ref: str = ""):
    return _index()


for path in PAGE_PATHS:
    router.add_api_route(path, page, methods=["GET"])


@router.get("/assets/{path:path}")
def asset(path: str):
    dist = DIST_DIR.resolve()
    candidate = (dist / "assets" / path).resolve()
    if candidate.is_file() and dist in candidate.parents:
        return FileResponse(candidate, headers={"Cache-Control": "public, max-age=31536000, immutable"})
    return JSONResponse({"detail": "Not Found"}, status_code=404)
