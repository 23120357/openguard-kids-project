"""Offline domain validation and privacy-preserving registrable names."""

import ipaddress
import re
from functools import lru_cache

from publicsuffix2 import get_sld

MANDATORY_SAFETY_DOMAIN = "tongdai111.vn"
LEGACY_SAFETY_DOMAINS = frozenset({"111.vn"})

# Some products serve the same site from several independently registered
# domains. Blocking only the address-bar domain can leave an already-open page
# usable through its API/CDN domains. Keep this list deliberately small and
# reviewed: broad vendor domains (for example google.com/googleapis.com) must
# never be inferred from a specific hostname such as drive.google.com.
SERVICE_DOMAIN_GROUPS = {
    "shopee.vn": frozenset(
        {"shopee.vn", "shopee.com", "shopeemobile.com", "susercontent.com"}
    ),
    "youtube.com": frozenset(
        {
            "youtube.com",
            "youtu.be",
            "youtube-nocookie.com",
            "googlevideo.com",
            "ytimg.com",
            "youtubei.googleapis.com",
        }
    ),
}


def domain_name(value):
    value = value.strip().rstrip(".").lower().encode("idna").decode("ascii")
    if len(value) > 253 or "." not in value:
        raise ValueError("Enter a domain name, without scheme, URL path or port")
    if any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part) for part in value.split(".")
    ):
        raise ValueError("Invalid domain name")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return value
    raise ValueError("IP addresses are not domain names")


def event_domain(value):
    value = domain_name(value)
    # Reserved lab TLDs are absent from the packaged public suffix list.
    return get_sld(value, strict=True) or ".".join(value.split(".")[-2:])


@lru_cache(maxsize=256)
def _expanded_block_domains(values):
    result = set()
    for value in values:
        domain = domain_name(value)
        result.update(SERVICE_DOMAIN_GROUPS.get(domain, (domain,)))
    return tuple(sorted(result))


def expanded_block_domains(values=()):
    """Return explicit rules plus narrowly reviewed domains for one service."""
    return _expanded_block_domains(tuple(values))


def normalize_safety_domains(values=()):
    """Keep the mandatory hotline domain and retire legacy aliases."""
    domains = {domain_name(value) for value in values}
    domains.difference_update(LEGACY_SAFETY_DOMAINS)
    domains.add(MANDATORY_SAFETY_DOMAIN)
    return sorted(domains)
