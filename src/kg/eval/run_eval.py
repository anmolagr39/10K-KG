"""Run the benchmark: `python -m kg eval --split test` (or dev).

Writes results/eval_<split>_<system>.json and results/per_question_<split>_<system>.csv and prints
accuracy / precision / recall overall and by question type, plus abstention and citation-page accuracy.
"""
import csv
import json
import time

from kg.config import BENCH_DIR, RESULTS_DIR
from kg.eval.score import answer_correct, retrieval_scores

TYPES = ["single_fact", "multi_hop", "cross_filing"]


def load(split: str) -> list[dict]:
    return [json.loads(line) for line in open(BENCH_DIR / f"{split}.jsonl", encoding="utf-8")]


def graph_system(q: dict) -> dict:
    from kg.query.answer import citations, render, typed_answer
    from kg.query.executor import answer_question
    res = answer_question(q["question"])
    pred = typed_answer(res)
    cites = citations(res)
    retrieved = [{"ticker": c["ticker"], "value": c["value"], "period_end": c["period_end"], "page": c["page"],
                  "kind": c["kind"], "relation": c["relation"], "object": c["object"]} for c in cites]
    return {"pred": pred, "rendered": render(res, pred), "retrieved": retrieved, "plan": res["plans"][-1] if res["plans"] else None,
            "error": res.get("error"), "repaired": res.get("repaired", False)}


def summarize(rows: list[dict]) -> dict:
    def agg(rs):
        n = len(rs)
        if not n:
            return {}
        return {"n": n, "accuracy": sum(r["correct"] for r in rs) / n,
                "precision": sum(r["precision"] for r in rs) / n, "recall": sum(r["recall"] for r in rs) / n,
                "abstained": sum(r["abstained"] for r in rs),
                "page_accuracy": (lambda v: sum(v) / len(v) if v else None)([r["page_accuracy"] for r in rs if r["page_accuracy"] is not None])}
    return {"overall": agg(rows), **{t: agg([r for r in rows if r["type"] == t]) for t in TYPES}}


def run(split: str = "test", system: str = "graph", ids: list[str] | None = None) -> dict:
    qs = [q for q in load(split) if not ids or q["id"] in ids]
    fn = graph_system
    if system == "bm25":
        from kg.eval.baseline_bm25 import bm25_system as fn
    rows = []
    for q in qs:
        t0 = time.time()
        out = fn(q)
        sc = retrieval_scores(out["retrieved"], q["gold_facts"])
        ok = answer_correct(q["answer"], out["pred"])
        rows.append({"id": q["id"], "type": q["type"], "question": q["question"], "correct": ok,
                     "abstained": out["pred"].get("kind") in (None, "none"), "answer": out["rendered"],
                     "gold": q["answer"], "pred": out["pred"], **sc, "plan": out.get("plan"), "error": out.get("error"),
                     "repaired": out.get("repaired", False), "seconds": round(time.time() - t0, 1)})
        print(f"{q['id']} {'OK ' if ok else 'XX '} P={sc['precision']:.2f} R={sc['recall']:.2f} | {out['rendered'][:90]}"
              + (f" | err: {out['error'][:120]}" if out.get("error") else ""), flush=True)
    summary = summarize(rows)
    RESULTS_DIR.mkdir(exist_ok=True)
    tag = f"{split}_{system}" + ("_subset" if ids else "")
    (RESULTS_DIR / f"eval_{tag}.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1, default=str),
                                                  encoding="utf-8")
    with open(RESULTS_DIR / f"per_question_{tag}.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "type", "correct", "abstained", "precision", "recall", "page_accuracy", "answer", "question", "error"])
        for r in rows:
            w.writerow([r["id"], r["type"], int(r["correct"]), int(r["abstained"]), f"{r['precision']:.3f}",
                        f"{r['recall']:.3f}", "" if r["page_accuracy"] is None else f"{r['page_accuracy']:.2f}",
                        r["answer"], r["question"], r["error"] or ""])
    print("\n" + format_summary(summary))
    return summary


def format_summary(s: dict) -> str:
    lines = [f"{'type':14s} {'n':>3s} {'accuracy':>9s} {'precision':>10s} {'recall':>7s} {'abstain':>8s} {'cite-page':>10s}"]
    for k in ["overall"] + TYPES:
        v = s.get(k) or {}
        if v:
            pa = "-" if v["page_accuracy"] is None else f"{v['page_accuracy']:.2f}"
            lines.append(f"{k:14s} {v['n']:3d} {v['accuracy']:9.2f} {v['precision']:10.2f} {v['recall']:7.2f} "
                         f"{v['abstained']:8d} {pa:>10s}")
    return "\n".join(lines)
