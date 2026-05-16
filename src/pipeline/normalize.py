from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "ref_src", "ref_url", "fbclid", "gclid", "mc_cid", "mc_eid",
    "igshid", "yclid", "_hsenc", "_hsmi", "hsCtaTracking",
}


def normalize_url(url: str) -> str:
    try:
        p = urlparse(url.strip())
    except (ValueError, AttributeError):
        return url

    scheme = p.scheme.lower() or "https"
    netloc = p.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    if netloc.endswith(":80") and scheme == "http":
        netloc = netloc[:-3]
    if netloc.endswith(":443") and scheme == "https":
        netloc = netloc[:-4]

    query = urlencode([(k, v) for k, v in parse_qsl(p.query, keep_blank_values=False)
                       if k.lower() not in TRACKING_PARAMS])

    path = p.path.rstrip("/") or "/"
    return urlunparse((scheme, netloc, path, "", query, ""))


_WS = re.compile(r"\s+")


def normalize_title(title: str) -> str:
    t = _WS.sub(" ", title).strip()
    if t.endswith(".") and not t.endswith(".."):
        t = t[:-1]
    return t
