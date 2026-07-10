from __future__ import annotations

import re

from new_feature.errors import NewFeatureError


def slugify(name: str) -> str:
    raw = name.strip().lower()
    if not raw:
        raise NewFeatureError("feature name cannot be empty")
    slug = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        raise NewFeatureError("feature name must contain letters or numbers")
    return slug


def feature_key(slug: str) -> str:
    return slug.replace("-", "_")
