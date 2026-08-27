"""Compatibility reads for optional annotation-registry provenance axes."""

from __future__ import annotations


def satisfaction_of(registry, name) -> tuple:
    """Read one optional satisfaction axis, or return empty for a pre-axis registry."""
    reader = getattr(registry, "satisfaction_of", None)
    if registry is None or not callable(reader):
        return ()
    return tuple(reader(name))


def satisfaction_ids(registry) -> set:
    """Return all placed structured-note authority from any registry-shaped object."""
    if registry is None:
        return set()
    return {identity for name in registry.names() for identity in satisfaction_of(registry, name)}


def annotation_owner(registry, annotation):
    """Return the feature owning *annotation*, if the registry exposes that identity."""
    named = getattr(registry, "named", None)
    feature_of = getattr(registry, "feature_of", None)
    if registry is None or not callable(named) or not callable(feature_of):
        return None
    for name in registry.names():
        if named(name) is annotation:
            owner = feature_of(name)
            if owner is not None:
                return owner
    return None
