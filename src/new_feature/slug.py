"""Normalize feature names into branch and manifest-safe identifiers."""

from __future__ import annotations

import re

from new_feature.errors import NewFeatureError


def slugify(name: str) -> str:
    """Convert a user-facing feature name into a normalized URL-style slug."""
    raw = name.strip().lower()
    if not raw:
        raise NewFeatureError("feature name cannot be empty")
    slug = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        raise NewFeatureError("feature name must contain letters or numbers")
    return slug


def feature_key(slug: str) -> str:
    """Return the manifest key that identifies a feature slug."""
    return slug.replace("-", "_")
