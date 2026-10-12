"""Offline domain validation and privacy-preserving registrable names."""

import ipaddress
import re

from publicsuffix2 import get_sld

MANDATORY_SAFETY_DOMAIN = "tongdai111.vn"
LEGACY_SAFETY_DOMAINS = frozenset({"111.vn"})


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


def normalize_safety_domains(values=()):
    """Keep the mandatory hotline domain and retire legacy aliases."""
    domains = {domain_name(value) for value in values}
    domains.difference_update(LEGACY_SAFETY_DOMAINS)
    domains.add(MANDATORY_SAFETY_DOMAIN)
    return sorted(domains)
