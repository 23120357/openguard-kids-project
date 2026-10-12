"""Offline, inspectable domain classification; no browsing history leaves the device."""

import csv
from functools import lru_cache
from pathlib import Path

from common.domains import domain_name

CATEGORY_LABELS = {
    "education": "Giáo dục",
    "entertainment": "Giải trí",
    "social": "Mạng xã hội",
    "games": "Trò chơi",
    "age_inappropriate": "Không phù hợp lứa tuổi",
    "unclassified": "Chưa phân loại",
}
DEFAULT_ACTIONS = {
    key: "block" if key in {"social", "games", "age_inappropriate"} else "allow"
    for key in CATEGORY_LABELS
}


@lru_cache(maxsize=1)
def category_catalog():
    with Path(__file__).with_name("domain_categories.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    result = {}
    for row in rows:
        domain = domain_name(row["domain"])
        if domain in result or row["category"] not in CATEGORY_LABELS:
            raise ValueError("Invalid or duplicate classification entry")
        result[domain] = row["category"]
    return result


def classify_domain(host, overrides=None):
    parts = domain_name(host).split(".")
    catalog = category_catalog()
    for index in range(len(parts) - 1):
        candidate = ".".join(parts[index:])
        if overrides and candidate in overrides:
            return overrides[candidate]
        if candidate in catalog:
            return catalog[candidate]
    return "unclassified"
