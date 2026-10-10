"""Which of a paper's claims can run here (ANY-1): the LLM states facts, code decides.

extract_facts  one small structured call per paper: for each experiment, the facts the paper states about it (dataset
               and whether it is public, its size, hardware and compute, model size, public code), null when not
               stated, with one short supporting quote. No judgement is asked for, so the answer stays small.
triage         code tags every claim papers.claims[i].runnable = {status, reason, facts}:
                 not_runnable  no public data · dataset too big · compute over budget · needs GPU
                 runnable      otherwise, with the reason (e.g. "MNIST is public and small"); a missing public repo
                               does not block (the Implementer writes the code from the paper)
The Designer is offered only runnable claims, and check_design rejects a not_runnable one with its reason."""
from __future__ import annotations

import json

MAX_DATASET_GB = 2.0            # a CPU executor downloads and holds the data
MAX_TRAIN_EXAMPLES = 2_000_000
MAX_PARAMS_M = 50               # millions of parameters trainable on CPU at reduced scale
SMALL_DATASETS = ("mnist", "cifar-10", "cifar10", "cifar-100", "cifar100", "svhn", "stl-10", "stl10", "iris", "uci",
                  "kmnist", "emnist", "fashion")  # public, small, in torchvision or sklearn
FACT_KEYS = ("dataset", "dataset_public", "dataset_size_gb", "train_examples", "code_public", "needs_gpu", "hardware",
             "compute", "gpu_hours", "params_millions", "quote")

_NSTR, _NBOOL, _NNUM = {"type": ["string", "null"]}, {"type": ["boolean", "null"]}, {"type": ["number", "null"]}
FACTS_SCHEMA = {"type": "object", "properties": {"experiments": {"type": "array", "items": {
    "type": "object",
    "properties": {
        "claim_ids": {"type": "array", "items": {"type": "string"}, "description": "the claims this experiment gives"},
        "dataset": {**_NSTR, "description": "the dataset name, a few words"},
        "dataset_public": {**_NBOOL, "description": "true if the paper uses a public dataset, false if in-house"},
        "dataset_size_gb": {**_NNUM, "description": "only if the paper states the size"},
        "train_examples": {**_NNUM, "description": "number of training examples, only if stated"},
        "code_public": {**_NBOOL, "description": "true if the paper links its code, false if it says it is not "
                                                 "released, null if it does not say"},
        "needs_gpu": {**_NBOOL, "description": "true if the paper trains on GPUs/TPUs or a cluster"},
        "hardware": {**_NSTR, "description": "the hardware as stated, a few words"},
        "compute": {**_NSTR, "description": "training time or compute as stated, a few words"},
        "gpu_hours": {**_NNUM, "description": "GPU-hours, only if stated or directly given"},
        "params_millions": {**_NNUM, "description": "model size in millions of parameters, only if stated"},
        "quote": {**_NSTR, "description": "one short verbatim span supporting the facts above"},
    },
    "required": ["claim_ids", *FACT_KEYS]}}}, "required": ["experiments"]}

FACTS_PROMPT = """Paper: {title} (arXiv {arxiv_id})

Claims already extracted (id | model | metric = value):
{claims}

For each experiment that produced these claims, state the facts the paper gives about running it: dataset and whether
it is public, dataset size, number of training examples, hardware and training compute, model size, and whether code is
released. Use null for anything the paper does not state; do not guess and do not judge whether we can run it. Keep
every string to a few words. One item per experiment, listing its claim ids.

{text}"""


def _small(dataset: str | None) -> bool:
    return bool(dataset) and any(s in dataset.lower() for s in SMALL_DATASETS)


def decide(f: dict | None, cap_min: float) -> tuple[str, str]:
    """(status, reason) for one experiment's facts; first blocking rule wins."""
    if not f:
        return "runnable", "no blocker stated in the paper (no facts extracted for this claim; unverified)"
    ds = f.get("dataset") or "the dataset"
    if f.get("dataset_public") is False:
        return "not_runnable", f"no public data: {ds} is not public"
    if (f.get("dataset_size_gb") or 0) > MAX_DATASET_GB:
        return "not_runnable", f"dataset too big: {ds} is {f['dataset_size_gb']:g} GB (limit {MAX_DATASET_GB:g} GB on CPU)"
    if (f.get("train_examples") or 0) > MAX_TRAIN_EXAMPLES:
        return "not_runnable", (f"dataset too big: {ds} has {int(f['train_examples'])} training examples "
                                f"(limit {MAX_TRAIN_EXAMPLES})")
    if f.get("gpu_hours") and f["gpu_hours"] * 60 > cap_min:
        return "not_runnable", (f"compute over budget: the paper reports {f['gpu_hours']:g} GPU-hours; the project cap "
                                f"is {cap_min:g} CPU-minutes")
    if (f.get("params_millions") or 0) > MAX_PARAMS_M:
        return "not_runnable", (f"compute over budget: a {f['params_millions']:g}M-parameter model does not train in "
                                f"{cap_min:g} CPU-minutes (limit {MAX_PARAMS_M}M)")
    small = _small(f.get("dataset"))
    if f.get("needs_gpu") and not small:
        return "not_runnable", f"needs GPU: {f.get('hardware') or 'the paper trains on GPUs'}, and {ds} is not small"
    why = [f"{ds} is public and small" if small and f.get("dataset_public") is not False else
           f"no blocker stated for {ds}"]
    if f.get("needs_gpu"):
        why.append(f"the paper used {f.get('hardware') or 'a GPU'}, but {ds} is small enough for CPU at reduced scale")
    if f.get("code_public") is False:
        why.append("no public code: the Implementer writes it from the paper")
    return "runnable", "; ".join(why)


def triage(claims: list[dict], experiments: list[dict], cap_min: float) -> list[dict]:
    """Every claim with runnable = {status, reason, facts} (claims are copied, not changed in place)."""
    by_claim = {cid: e for e in experiments or [] for cid in (e.get("claim_ids") or [])}
    out = []
    for c in claims:
        f = by_claim.get(c["id"])
        status, reason = decide(f, cap_min)
        out.append({**c, "runnable": {"status": status, "reason": reason,
                                      "facts": {k: f[k] for k in FACT_KEYS if f and f.get(k) is not None}}})
    return out


def extract_facts(text: str, claims: list[dict], *, llm, agent: dict, title: str = "", arxiv_id: str = "",
                  task_id=None, model: str = "smart") -> tuple[list[dict], int]:
    """One small call; returns (experiments with facts, tokens). Unknown claim ids are dropped by code."""
    from lab.agents.paper import READER_MAX_OUTPUT, check_request_size, reader_system, select_sections
    from lab.llm import Request

    valid = [c for c in claims if c.get("valid")]
    if not valid:
        return [], 0
    sel, _ = select_sections(text)
    lines = "\n".join(f"{c['id']} | {c.get('model')} | {c.get('metric')} = {c.get('value')}" for c in valid)
    prompt = FACTS_PROMPT.format(title=title or "(untitled)", arxiv_id=arxiv_id or "?", claims=lines, text=sel)
    system = reader_system(agent)
    check_request_size(prompt, system)
    resp = llm.call(Request(agent=agent["name"], system=system, prompt=prompt, schema=FACTS_SCHEMA, model=model,
                            max_output=READER_MAX_OUTPUT), agent_id=agent.get("id"), task_id=task_id)
    ids = {c["id"] for c in claims}
    exps = []
    for e in (resp.output or {}).get("experiments", []) if isinstance(resp.output, dict) else []:
        if isinstance(e, dict):
            e = {**e, "claim_ids": [i for i in e.get("claim_ids") or [] if i in ids]}
            exps.append(e)
    return exps, resp.tokens_in + resp.tokens_out


def summary(claims: list[dict]) -> str:
    n = {"runnable": 0, "not_runnable": 0}
    for c in claims:
        n[(c.get("runnable") or {}).get("status", "runnable")] += 1
    reasons = {}
    for c in claims:
        r = c.get("runnable") or {}
        if r.get("status") == "not_runnable":
            reasons[r["reason"].split(":")[0]] = reasons.get(r["reason"].split(":")[0], 0) + 1
    return f"{n['runnable']} runnable, {n['not_runnable']} not runnable" + \
        (f" ({json.dumps(reasons)})" if reasons else "")
