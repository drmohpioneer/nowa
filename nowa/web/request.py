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
