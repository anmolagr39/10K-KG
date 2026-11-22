"""Run a plan step by step over the graph; one repair round-trip to the planner on failure."""
import copy
import re

from kg.query.operators import OPS, Ctx, OpError
from kg.query.planner import Plan, PlanError, plan
from kg.query.store import store


def _resolve(v, results: dict):
    if isinstance(v, str) and v.startswith("$"):
        key = v[1:]
        if key not in results:
            raise OpError(f"reference {v} to a step that has not run")
        return results[key]
    if isinstance(v, list):
        out = []
        for x in v:
            r = _resolve(x, results)
            out += r if isinstance(x, str) and x.startswith("$") and isinstance(r, list) else [r]
        return out
    if isinstance(v, dict):
        return {k: _resolve(x, results) for k, x in v.items()}
    return v


ARG_ALIASES = {"company": "companies", "tickers": "companies", "input": "items", "data": "items"}


def run_plan(p: Plan, ctx: Ctx) -> list:
    results = {}
    for step in p.steps:
        fn = OPS[step.op]
        args = _resolve(copy.deepcopy(step.args), results)
        # tolerate small naming slips by the planner
        params = fn.__code__.co_varnames[1:fn.__code__.co_argcount]
        fixed = {}
        for k, v in args.items():
            if k not in params and ARG_ALIASES.get(k) in params:
                k = ARG_ALIASES[k]
            if k not in params and k == "companies" and "company" in params:
                k = "company"
            if k in params:
                fixed[k] = v
        try:
            out = fn(ctx, **fixed)
        except TypeError as e:
            raise OpError(f"step {step.id} ({step.op}): bad arguments: {e}")
        except OpError as e:
            raise OpError(f"step {step.id} ({step.op}): {e}")
        results[step.id] = out
        ctx.results[step.id] = out
        ctx.trace.append({"step": step.id, "op": step.op, "args": step.args, "n": len(out),
                          "result": [{k: v for k, v in it.items() if k in ("ticker", "name", "value", "unit", "period_end", "winner")}
                                     for it in out[:12]]})
    if p.answer not in results:
        raise OpError(f"answer refers to unknown step {p.answer}")
    return results[p.answer]


def _parts(p: Plan, ctx) -> list[dict]:
    """Independent results of a plan: steps whose output no later step uses.
    "Who audits Apple and since when?" -> [related(audited_by), get_fact(auditor_since)]."""
    import json as _json
    used = set()
    for st in p.steps:
        used |= set(re.findall(r"\$(s\d+)", _json.dumps(st.args)))
    leaves = [st for st in p.steps if st.id not in used]
    if len(leaves) <= 1:
        return []
    return [{"step": st.id, "op": st.op, "args": st.args, "items": ctx.results.get(st.id, [])} for st in leaves]


def answer_question(question: str) -> dict:
    """Plan -> execute (-> one repair) -> result items + execution log."""
    s = store()
    log = {"question": question, "plans": [], "error": None}
    p, err = None, None
    for attempt in range(2):
        ctx = Ctx(s)
        try:
            p = plan(question, repair={"plan": log["plans"][-1], "error": err} if attempt else None)
            log["plans"].append(p.model_dump())
            items = run_plan(p, ctx)
            return {**log, "items": items, "touched": ctx.touched, "trace": ctx.trace, "parts": _parts(p, ctx),
                    "final_op": p.steps[-1].op
                    if p.steps[-1].id == p.answer else next(st.op for st in p.steps if st.id == p.answer),
                    "final_args": next(st.args for st in p.steps if st.id == p.answer), "repaired": attempt == 1}
        except PlanError as e:
            err = f"invalid plan: {e}"
            log["plans"].append(e.raw if isinstance(e.raw, dict) else {"raw": str(e.raw)})
        except OpError as e:
            err = str(e)
        except Exception as e:  # noqa: BLE001 - report any planner/LLM failure as an abstention
            err = f"{type(e).__name__}: {e}"
            if not log["plans"]:
                log["plans"].append({})
    return {**log, "items": [], "touched": ctx.touched if p else [], "trace": [], "error": err, "abstain": True}
