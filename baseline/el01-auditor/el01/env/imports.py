"""Which third-party packages the audited scripts import, and how surely they need them.

An AST walk starts at the entry-point scripts and follows imports of the repo's own modules (resolved the way Python
does for a script: the script's folder first). Every import site of a third-party module gets a tier:
  eager    executed whenever the entry point runs (module-level, through module-level imports only)
  lazy     inside a function, an `if`, a loop, or in a module that is itself only imported lazily
  guarded  inside `try:` whose handler catches ImportError (or broader): the code runs without the package
A module's tier is its strongest site (eager < lazy < guarded). The env builder installs eager and lazy packages and
never guarded ones; only eager frameworks may set the Python version."""
from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

TIERS = ("eager", "lazy", "guarded")
STDLIB = set(sys.stdlib_module_names) | {"__future__"}
IMPORT_ERRORS = {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}

# import name -> distribution name, where they differ (lower-case distribution names)
MODULE_TO_DIST = {
    "sklearn": "scikit-learn", "PIL": "pillow", "cv2": "opencv-python", "yaml": "pyyaml", "skimage": "scikit-image",
    "bs4": "beautifulsoup4", "dateutil": "python-dateutil", "attr": "attrs", "Crypto": "pycryptodome",
    "google": "protobuf", "jwt": "pyjwt", "serial": "pyserial", "magic": "python-magic", "dotenv": "python-dotenv",
    "Bio": "biopython", "OpenGL": "pyopengl", "wx": "wxpython", "fitz": "pymupdf", "docx": "python-docx",
    "absl": "absl-py", "tensorflow_hub": "tensorflow-hub",
}
# distribution -> import name, where they differ (beyond the inverse of MODULE_TO_DIST and `-` -> `_`)
DIST_TO_MODULE = {v: k for k, v in MODULE_TO_DIST.items()} | {
    "tensorflow-gpu": "tensorflow", "tensorflow-cpu": "tensorflow", "tf-nightly": "tensorflow",
    "opencv-python-headless": "cv2", "opencv-contrib-python": "cv2", "opencv-contrib-python-headless": "cv2",
    "torch-geometric": "torch_geometric", "pytorch-lightning": "pytorch_lightning",
}


def normalize(dist: str) -> str:
    """PEP 503 name normalisation."""
    return re.sub(r"[-_.]+", "-", dist).lower()


def dist_for_module(module: str) -> str:
    return normalize(MODULE_TO_DIST.get(module, module))


def module_for_dist(dist: str) -> str:
    d = normalize(dist)
    return DIST_TO_MODULE.get(d, d.replace("-", "_"))


def _weaker(a: str, b: str) -> str:
    return TIERS[max(TIERS.index(a), TIERS.index(b))]


def _catches_import_error(handlers) -> bool:
    for h in handlers:
        if h.type is None:
            return True
        names = h.type.elts if isinstance(h.type, ast.Tuple) else [h.type]
        if any(isinstance(n, ast.Name) and n.id in IMPORT_ERRORS for n in names):
            return True
    return False


def import_sites(tree: ast.Module):
    """Yield (import node, context tier) for every import statement in the module."""
    def visit(stmts, ctx):
        for st in stmts:
            if isinstance(st, (ast.Import, ast.ImportFrom)):
                yield st, ctx
            elif isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield from visit(st.body, _weaker(ctx, "lazy"))
            elif isinstance(st, ast.ClassDef):
                yield from visit(st.body, ctx)  # class bodies run at import time
            elif isinstance(st, ast.Try):
                body_ctx = _weaker(ctx, "guarded") if _catches_import_error(st.handlers) else ctx
                yield from visit(st.body, body_ctx)
                yield from visit(st.orelse, body_ctx)
                for h in st.handlers:
                    yield from visit(h.body, _weaker(ctx, "lazy"))
                yield from visit(st.finalbody, ctx)
            elif isinstance(st, (ast.With, ast.AsyncWith)):
                yield from visit(st.body, ctx)
            elif isinstance(st, (ast.If, ast.For, ast.AsyncFor, ast.While)):
                yield from visit(st.body, _weaker(ctx, "lazy"))
                yield from visit(st.orelse, _weaker(ctx, "lazy"))
            elif isinstance(st, ast.Match):
                for case in st.cases:
                    yield from visit(case.body, _weaker(ctx, "lazy"))
    yield from visit(tree.body, "eager")


@dataclass
class Site:
    file: str   # repo-relative, posix
    line: int
    tier: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}" + ("" if self.tier == "eager" else f" ({self.tier})")


@dataclass
class ScanResult:
    entry_points: list[str]
    local_files: dict[str, str] = field(default_factory=dict)        # repo-relative file -> tier
    third_party: dict[str, list[Site]] = field(default_factory=dict)  # top-level module -> sites
    unparsed: dict[str, str] = field(default_factory=dict)            # file -> syntax error

    def tier(self, module: str) -> str:
        return TIERS[min(TIERS.index(s.tier) for s in self.third_party[module])]

    def modules(self, tier: str) -> list[str]:
        return sorted(m for m in self.third_party if self.tier(m) == tier)

    def to_json(self) -> dict:
        return {"entry_points": self.entry_points, "local_files": len(self.local_files),
                "local_files_by_tier": {t: sum(1 for v in self.local_files.values() if v == t) for t in TIERS},
                "unparsed": self.unparsed,
                "third_party": {m: {"tier": self.tier(m), "sites": [str(s) for s in sorted(
                    sites, key=lambda s: (TIERS.index(s.tier), s.file, s.line))]}
                    for m, sites in sorted(self.third_party.items())}}


def _is_package_dir(p: Path) -> bool:
    return p.is_dir() and any(p.glob("*.py"))


def _resolve_local(roots: list[Path], parts: list[str]) -> list[Path] | None:
    """The files Python executes for `import a.b.c` if `a` is one of the repo's modules; None if it is not local."""
    for root in roots:
        if not ((root / f"{parts[0]}.py").is_file() or _is_package_dir(root / parts[0])):
            continue
        files = []
        for i in range(1, len(parts) + 1):
            p = root.joinpath(*parts[:i])
            if p.with_suffix(".py").is_file():
                files.append(p.with_suffix(".py"))
                break
            if (p / "__init__.py").is_file():
                files.append(p / "__init__.py")
            elif not _is_package_dir(p):
                break
        return files
    return None


def scan(repo: Path, entry_points: list[str]) -> ScanResult:
    repo = Path(repo).resolve()
    eps = [repo / e for e in entry_points]
    missing = [e for e, p in zip(entry_points, eps) if not p.is_file()]
    if missing:
        raise FileNotFoundError(f"entry points not found in {repo}: {missing}")
    roots = list(dict.fromkeys([p.parent for p in eps] + [repo]))
    res = ScanResult(entry_points=list(entry_points))
    tier: dict[Path, str] = {p: "eager" for p in eps}
    parsed: dict[Path, list] = {}
    queue = list(eps)

    def targets(node, file: Path):
        """(local files, third-party top-level module) for each name the import statement loads."""
        if isinstance(node, ast.Import):
            names = [a.name.split(".") for a in node.names]
            return [(_resolve_local(roots, n), n[0]) for n in names]
        if node.level:  # relative import: always the repo's own code
            base = file.parent
            for _ in range(node.level - 1):
                base = base.parent
            mod = node.module.split(".") if node.module else []
            out = [(_resolve_local([base], mod) or [], None)] if mod else []
            out += [(_resolve_local([base], mod + [a.name]) or [], None) for a in node.names if a.name != "*"]
            return out
        mod = node.module.split(".")
        local = _resolve_local(roots, mod)
        if local is None:
            return [(None, mod[0])]
        out = [(local, None)]  # `from pkg import sub` may load the submodule pkg/sub.py
        out += [(_resolve_local(roots, mod + [a.name]) or [], None) for a in node.names if a.name != "*"]
        return out

    while queue:  # fixpoint: a file is re-walked when it becomes reachable through a stronger tier
        f = queue.pop()
        if f not in parsed:
            try:
                parsed[f] = list(import_sites(ast.parse(f.read_bytes(), filename=str(f))))
            except (SyntaxError, ValueError) as e:
                res.unparsed[f.relative_to(repo).as_posix()] = f"{type(e).__name__}: {e}"
                parsed[f] = []
        for node, ctx in parsed[f]:
            eff = _weaker(tier[f], ctx)
            for local, _ in targets(node, f):
                for lf in local or []:
                    if lf not in tier or TIERS.index(eff) < TIERS.index(tier[lf]):
                        tier[lf] = eff
                        queue.append(lf)

    for f, t in tier.items():
        res.local_files[f.relative_to(repo).as_posix()] = t
        for node, ctx in parsed.get(f, []):
            for local, top in targets(node, f):
                if local is None and top not in STDLIB:
                    res.third_party.setdefault(top, []).append(
                        Site(f.relative_to(repo).as_posix(), node.lineno, _weaker(t, ctx)))
    res.local_files = dict(sorted(res.local_files.items()))
    return res
