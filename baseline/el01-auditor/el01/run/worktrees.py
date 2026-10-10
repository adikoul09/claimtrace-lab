"""One git worktree per branch (or ref) under workspace/worktrees/<audit>/<name>, detached at the ref's commit."""
from __future__ import annotations

from pathlib import Path

from el01.ingest.repo import GitError, git, resolve


def ensure_worktree(repo: Path, ref: str, dest: Path) -> tuple[Path, str]:
    """Create `dest` as a detached worktree of `repo` at `ref`, or check an existing one.

    An existing worktree must sit at the same commit and have no changes to tracked files: runs never mix code
    states. Untracked files (generated data, results/) are allowed. Returns (worktree path, full sha)."""
    repo, dest = Path(repo).resolve(), Path(dest).resolve()
    sha = resolve(repo, ref)
    if dest.exists():
        head = git(dest, "rev-parse", "HEAD")
        if head != sha:
            raise GitError(f"worktree {dest} is at {head[:7]}, expected {ref} = {sha[:7]}")
        dirty = git(dest, "status", "--porcelain", "--untracked-files=no")
        if dirty:
            raise GitError(f"worktree {dest} has changes to tracked files:\n{dirty}")
        return dest, sha
    dest.parent.mkdir(parents=True, exist_ok=True)
    git(repo, "worktree", "prune")  # drop the registration of a worktree whose folder was deleted
    git(repo, "worktree", "add", "--detach", str(dest), sha)
    return dest, sha
