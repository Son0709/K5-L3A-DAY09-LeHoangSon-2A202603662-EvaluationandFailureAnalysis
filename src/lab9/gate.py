"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, aggregate, load_spec, per_item


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    rows = pr.get("rows") or []
    brows = base.get("rows") or []

    # 1. Non-finite numbers: `nan < min` is False, so a naive threshold comparison lets them through.
    def _nonfinite(obj, path):
        if isinstance(obj, float) and not math.isfinite(obj):
            problems.append(f"non-finite value {obj!r} at {path}")
        elif isinstance(obj, dict):
            for k, v in obj.items():
                _nonfinite(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                _nonfinite(v, f"{path}[{i}]")
    _nonfinite(pr.get("metrics") or {}, "metrics")
    _nonfinite(rows, "rows")

    # 2. A crashed grader must never be quietly turned into "no data", even on a green run.
    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s), first: {pr['evaluator_failures'][0]}")
    graded = [m["id"] for m in spec.get("metrics", []) if brows and m["id"] in brows[0]]
    none_rows = sum(1 for r in rows if any(r.get(m) is None for m in graded))
    if none_rows:
        problems.append(f"{none_rows} row(s) with a missing/None value for a graded metric (a crashed grader drops out of the mean)")

    # 3. Same population as the baseline: dropped, duplicated, added or re-picked (item, seed) rows.
    man, bman = pr.get("manifest") or {}, base.get("manifest") or {}
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    expect_n = int(man.get("items", 0)) * len(man.get("seeds") or [])
    if len(rows) != expect_n:
        problems.append(f"{len(rows)} rows, manifest says {man.get('items')} items x {len(man.get('seeds') or [])} seeds = {expect_n}")
    dup = sorted({k for k in keys if keys.count(k) > 1})
    if dup:
        problems.append(f"duplicated (item, seed) row(s), e.g. {dup[0]}")
    bkeys = {(r.get("item_id"), r.get("seed")) for r in brows}
    if set(keys) != bkeys:
        missing, extra = sorted(bkeys - set(keys)), sorted(set(keys) - bkeys)
        problems.append(f"(item, seed) set differs from the baseline: {len(missing)} missing"
                        + (f" e.g. {missing[0]}" if missing else "") + f", {len(extra)} extra" + (f" e.g. {extra[0]}" if extra else ""))
    if man.get("seeds") != bman.get("seeds") or man.get("items") != bman.get("items"):
        problems.append(f"manifest seeds/items {man.get('seeds')}/{man.get('items')} != baseline {bman.get('seeds')}/{bman.get('items')}")

    # 4. Slice tags are derived from labels. Relabelling an item hides it from the slice gate.
    def _tags(rs):
        out: dict = {}
        for r in rs:
            out.setdefault(r.get("item_id"), set()).add(tuple(sorted(r.get("slices") or [])))
        return out
    ptags, btags = _tags(rows), _tags(brows)
    changed = sorted(i for i in ptags if i in btags and ptags[i] != btags[i])
    if changed:
        problems.append(f"slice tags differ from the baseline for {len(changed)} item(s), e.g. {changed[0]}")

    # 5. Reported metrics must be what the rows add up to (a hand-edited number would pass every threshold).
    #    Only the metrics the report itself states are checked; cost needs a per-row cost column.
    if rows and not any(p.startswith("non-finite") for p in problems):
        ids = [m["id"] for m in spec.get("metrics", []) if m["id"] in rows[0]]
        has_cost = all("cost" in r for r in rows)
        try:
            again = aggregate([{"cost": 0.0, **r} for r in rows], ids, k_values=spec.get("pass_k", []))
        except Exception as exc:   # malformed rows are an integrity problem, not a crash
            problems.append(f"cannot recompute metrics from rows: {exc!r}")
            again = {}
        reported = pr.get("metrics") or {}
        for k, v in again.items():
            if k not in reported or (k == "cost_per_success" and not has_cost):
                continue
            got = reported[k]
            if v is None or got is None:
                if v != got:
                    problems.append(f"metric {k}: rows give {v}, report says {got}")
            elif isinstance(v, (int, float)) and isinstance(got, (int, float)) and not math.isclose(v, got, rel_tol=0, abs_tol=1e-4):
                problems.append(f"metric {k}: rows give {v}, report says {got}")

    # 6. Ratchet: on the same eval-set version thresholds may only get stricter.
    if base_spec is not None and spec.get("eval_set_version") == base_spec.get("eval_set_version"):
        problems += _ratchet(spec, base_spec)
    return problems


def _ratchet(spec: dict, base_spec: dict) -> list[str]:
    out: list[str] = []

    def _entry(kind, name, new, old):
        # metrics keep their limits under "threshold"; slices keep them at the top level
        nth, oth = (new.get("threshold") or {}, old.get("threshold") or {}) if kind == "metric" else (new, old)
        if old.get("blocking") and not new.get("blocking"):
            out.append(f"{kind} {name}: blocking turned off")
        for key in ("max", "max_increase"):
            if key in oth and (key not in nth or nth[key] > oth[key]):
                out.append(f"{kind} {name}: {key} loosened {oth[key]} -> {nth.get(key)}")
        if "min" in oth and ("min" not in nth or nth["min"] < oth["min"]):
            out.append(f"{kind} {name}: min loosened {oth['min']} -> {nth.get('min')}")
        if oth.get("no_significant_drop") and not nth.get("no_significant_drop"):
            out.append(f"{kind} {name}: no_significant_drop dropped")

    new_m = {m["id"]: m for m in spec.get("metrics", [])}
    for m in base_spec.get("metrics", []):
        if m["id"] not in new_m:
            out.append(f"metric {m['id']}: removed")
        else:
            _entry("metric", m["id"], new_m[m["id"]], m)
    new_s = {(s["name"], s.get("metric")): s for s in spec.get("slices") or []}
    for s in base_spec.get("slices") or []:
        key = (s["name"], s.get("metric"))
        if key not in new_s:
            out.append(f"slice {s['name']}/{s.get('metric')}: removed")
        else:
            _entry("slice", f"{s['name']}/{s.get('metric')}", new_s[key], s)
    if base_spec.get("seeds") and set(spec.get("seeds") or []) < set(base_spec["seeds"]):
        out.append(f"seeds shrunk {base_spec['seeds']} -> {spec.get('seeds')}")
    bc, nc = (base_spec.get("bootstrap") or {}).get("confidence"), (spec.get("bootstrap") or {}).get("confidence")
    if bc is not None and nc is not None and nc > bc:
        out.append(f"bootstrap confidence raised {bc} -> {nc} (wider CI blocks less)")
    return out


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked: list[str] = []
    lines: list[str] = []
    bs = spec.get("bootstrap", {})
    for sl in spec.get("slices") or []:
        name, metric = sl["name"], sl["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        problems, note, value = [], "", None
        if not a:
            # An empty slice would pass vacuously. Fail closed: rows may have been relabelled out of it.
            problems.append("no rows in this slice")
        else:
            value = sum(a.values()) / len(a)
            if "min" in sl and value < sl["min"]:
                problems.append(f"{value:.4f} < min {sl['min']}")
            if sl.get("no_significant_drop"):
                keys = sorted(set(a) & set(b))
                if not keys:
                    problems.append("baseline has no rows in this slice to compare with")
                else:
                    d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                       n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
                    note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}] over {len(keys)} items"
                    if hi < 0:
                        problems.append("paired CI entirely below 0")
        failed = bool(problems)
        label = "ok" if not failed else ("BLOCK" if sl.get("blocking") else "warn")
        if failed and sl.get("blocking"):
            blocked.append(sid)
        shown = "n/a" if value is None else f"{value:.4f}"
        lines.append(f"  {sid:<40} {shown:<8} {json.dumps({k: sl[k] for k in ('min', 'no_significant_drop') if k in sl}):<40} "
                     f"{note:<44} {label}" + (f"  ({'; '.join(problems)})" if failed else ""))
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
