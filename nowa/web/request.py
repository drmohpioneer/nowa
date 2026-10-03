from fastapi import Request

from nowa.config import get_settings


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else ""
    hops = get_settings().trusted_proxy_hops
    if hops:
        forwarded = request.headers.get("X-Forwarded-For", "")
        entries = [entry.strip() for entry in forwarded.split(",")] if forwarded else []
        if len(entries) >= hops and entries[-hops]:
            return entries[-hops]
    return peer


def page_language(request: Request) -> str:
    """Used only by the judge-facing public pages."""
    explicit = request.query_params.get("lang")
    if explicit in {"ar", "en"}:
        return explicit
    first = request.headers.get("Accept-Language", "").split(",", 1)[0].split(";", 1)[0].strip()
    return "en" if first and first.lower().split("-", 1)[0] != "ar" else "ar"


def page_link(request: Request, path: str) -> str:
    """Carry only an explicit supported language across page entrances."""
    lang = request.query_params.get("lang")
    if lang not in {"ar", "en"}:
        return path
    route, marker, fragment = path.partition("#")
    route += ("&" if "?" in route else "?") + "lang=" + lang
    return route + (marker + fragment if marker else "")
