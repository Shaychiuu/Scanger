"""The upstream VisualMatch API, plus FashionCLIP when VISUALMATCH_MODEL=fashionclip.

Upstream's SearchEngine only knows its three built-in models and the checkout is
not part of this repo, so instead of editing it we reuse its FastAPI app and wrap
`get_engine`. Any other VISUALMATCH_MODEL value behaves exactly as before.

Run from the repo root: uvicorn scanger.visualmatch_server:app
"""

import os
import sys

from fastapi import HTTPException

from scanger.config import REPO_ROOT
from scanger.fashionclip import MODEL_NAME

sys.path.insert(0, str(REPO_ROOT / "upstream" / "visualmatch"))

from api import app as upstream  # noqa: E402  (needs the path above)

app = upstream.app
_upstream_get_engine = upstream.get_engine


def get_engine():
    if upstream._engine is None and os.environ.get("VISUALMATCH_MODEL") == MODEL_NAME:
        try:
            from scanger.fashionclip import FashionClipEngine

            upstream._engine = FashionClipEngine()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"FashionCLIP failed to load: {exc}") from exc
    return _upstream_get_engine()


# The route handlers look up get_engine in the upstream module at call time.
upstream.get_engine = get_engine
