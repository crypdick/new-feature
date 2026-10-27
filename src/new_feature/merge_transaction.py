"""Bound merge rollback to Git state still owned by the current operation."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path  # noqa: TC003 - runtime annotation checking

from new_feature.errors import NewFeatureError
from new_feature.git import (
    CheckoutState,
    checkout_state,
    commit_parents,
    indexed_gitlink,
    resolve_revision,
    rollback_merge,
)


@dataclass
class MergeTransaction:
    """Keep verified Git state across commands that may modify the target checkout."""

    root: Path
    feature: str
    original: CheckoutState = field(init=False)
    owned: CheckoutState = field(init=False)
    feature_revision: str = field(init=False)

    def __post_init__(self) -> None:
        self.original = self.owned = checkout_state(self.root)
        self.feature_revision = resolve_revision(self.root, self.feature)

    def prepared(self) -> None:
        """Capture the result of Git's merge before running lifecycle commands."""
        current = checkout_state(self.root)
        if (
            current.branch != self.original.branch
            or current.unstaged
            or not self._submodules_match(current)
            or current.untracked != self.original.untracked
        ):
            raise NewFeatureError("merge state changed; target checkout preserved")
        if current.head == self.original.head:
            if current.merge_heads not in {(), (self.feature_revision,)}:
                raise NewFeatureError("merge parents changed; target checkout preserved")
        elif (
            current.merge_heads
            or current.tree != resolve_revision(self.root, "HEAD^{tree}")
            or (
                current.head != self.feature_revision
                and commit_parents(self.root, current.head) != (self.original.head, self.feature_revision)
            )
        ):
            raise NewFeatureError("unexpected merge revision; target checkout preserved")
        self.owned = current

    def _submodules_match(self, current: CheckoutState) -> bool:
        """Allow clean owned checkouts to follow the parent's indexed gitlink."""
        if tuple(module.path for module in current.submodules) != tuple(
            module.path for module in self.owned.submodules
        ):
            return False
        return all(
            observed == expected
            or (
                not expected.status
                and not observed.status
                and observed.branch in {None, expected.branch}
                and observed.head == indexed_gitlink(self.root, observed.path)
            )
            for expected, observed in zip(self.owned.submodules, current.submodules, strict=True)
        )

    def _completed(self, current: CheckoutState) -> bool:
        return (
            (
                bool(self.owned.merge_heads)
                or self.owned.tree != resolve_revision(self.root, f"{self.owned.head}^{{tree}}")
            )
            and current.branch == self.owned.branch
            and not current.merge_heads
            and current.tree == self.owned.tree
            and not current.unstaged
            and current.submodules == self.owned.submodules
            and current.untracked == self.owned.untracked
            and resolve_revision(self.root, "HEAD^{tree}") == self.owned.tree
            and commit_parents(self.root, current.head) == (self.owned.head, *self.owned.merge_heads)
        )

    def pending_commit(self) -> bool:
        """Accept unchanged prepared state or an exact external completion of it."""
        current = checkout_state(self.root)
        if resolve_revision(self.root, self.feature) != self.feature_revision:
            raise NewFeatureError("feature branch changed during merge; target checkout preserved")
        if current == self.owned:
            return bool(current.merge_heads) or current.tree != resolve_revision(self.root, "HEAD^{tree}")
        # NOTE: docs/ARCHITECTURE.md allows only clean indexed submodule reconciliation.
        if self._submodules_match(current):
            normalized = replace(current, submodules=self.owned.submodules)
            if normalized == self.owned:
                self.owned = current
                return bool(current.merge_heads) or current.tree != resolve_revision(self.root, "HEAD^{tree}")
            if self._completed(normalized):
                return False
        raise NewFeatureError("merge state changed during checks; target checkout preserved")

    def committed(self) -> None:
        """Take ownership only of an exact commit of the prepared tree."""
        current = checkout_state(self.root)
        if not self._completed(current):
            raise NewFeatureError("merge commit changed unexpectedly; target checkout preserved")
        self.owned = current

    def rollback(self) -> None:
        """Restore only unchanged owned state, leaving uncertain user work intact."""
        # NOTE: docs/ARCHITECTURE.md documents conservative ownership and retained local files.
        try:
            current = checkout_state(self.root)
            unchanged = (
                current == self.owned and resolve_revision(self.root, self.feature) == self.feature_revision
            )
        except NewFeatureError as exc:
            raise NewFeatureError("cannot verify merge ownership; target checkout preserved") from exc
        if not unchanged:
            raise NewFeatureError("merge ownership changed; target checkout preserved for manual recovery")
        rollback_merge(self.root, revision=self.original.head)
