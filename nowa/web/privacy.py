"""Public privacy policy pages, without patient data or authentication."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from nowa import schema as s
from nowa.core.consent import policy_text
from nowa.web.logging import PRIVATE_HEADERS
from nowa.web.templates import environment, markdown_html

router = APIRouter()


@router.get("/privacy", response_class=HTMLResponse)
@router.get("/c/{slug}/privacy", response_class=HTMLResponse)
def privacy(request: Request, slug: str | None = None) -> HTMLResponse:
    if slug is not None:
        with request.app.state.engine.connect() as conn:
            if not conn.execute(
                select(s.clinics.c.id).where(s.clinics.c.slug == slug, s.clinics.c.slug != "_nowa")
            ).first():
                raise HTTPException(404)
    lang = "en" if request.query_params.get("lang") == "en" else "ar"
    version, _, text = policy_text(lang)
    return HTMLResponse(
        environment.get_template("privacy.html").render(
            lang=lang,
            version=version,
            policy=markdown_html(text),
            home="/" if lang == "ar" else "/?lang=en",
        ),
        headers=PRIVATE_HEADERS,
    )
