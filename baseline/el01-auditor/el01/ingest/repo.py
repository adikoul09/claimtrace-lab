"""The code under audit: clone once, resolve commits, read commit dates. Git runs as a subprocess with argument lists."""
from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path


class GitError(RuntimeError):
    pass


def git(repo: Path, *args: str) -> str:
    """`git -C <repo> <args>`; stdout without the trailing newline. Raises GitError with git's message."""
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if p.returncode != 0:
        raise GitError(f"git {' '.join(args)} (in {repo}): {p.stderr.strip() or p.stdout.strip()}")
    return p.stdout.rstrip("\n")


def ensure_clone(url: str, dest: Path) -> Path:
    """Clone `url` into `dest` unless a clone is already there. Network is used only here (fetch phase)."""
    dest = Path(dest)
    if (dest / ".git").exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    p = subprocess.run(["git", "clone", url, str(dest)], capture_output=True, text=True)
    if p.returncode != 0:
        raise GitError(f"git clone {url}: {p.stderr.strip()}")
    return dest


def resolve(repo: Path, ref: str) -> str:
    """Full sha of a commit-ish."""
    return git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")


def commit_date(repo: Path, ref: str) -> datetime:
    """Committer date with its UTC offset (`git show -s --format=%cI`)."""
    return datetime.fromisoformat(git(repo, "show", "-s", "--format=%cI", ref))


def tracked_files(repo: Path, ref: str = "HEAD") -> list[str]:
    return git(repo, "ls-tree", "-r", "--name-only", ref).splitlines()


def tree_id(repo: Path, ref: str) -> str:
    """The git tree id of a commit: a content hash of every tracked file (used as an LLM cache input)."""
    return git(repo, "rev-parse", f"{ref}^{{tree}}")


def snapshot(repo: Path, ref: str, dest_root: Path) -> Path:
    """Tracked files of `ref` (no .git, no untracked data) in dest_root/<sha>/, via `git archive`. Read-only use."""
    import io
    import tarfile
    sha = resolve(repo, ref)
    dest = Path(dest_root) / sha
    if (dest / ".el01-snapshot").exists():
        return dest
    p = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", sha], capture_output=True)
    if p.returncode != 0:
        raise GitError(f"git archive {sha}: {p.stderr.decode(errors='replace').strip()}")
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(p.stdout)) as tar:
        tar.extractall(dest)
    (dest / ".el01-snapshot").write_text(sha + "\n")
    return dest
