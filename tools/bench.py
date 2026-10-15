"""Benchmark the offline formatter on a folder of trees saved as JSON (tools/dump_tree.py).

Runs without Blender, with any Python 3 (Blender's bundled one works):

    python tools/bench.py CORPUS [--runs 3] [--slow 10] [--only TEXT] [--jobs 4]
                          [--save base.json | --compare base.json] [--profile [--top 30]]

For every *.json in CORPUS (the files of tools/dump_tree.py: {"data": model data, ...}) it runs
what one pass of a sort runs on plain data: the copy plan of input nodes (dup.plan, which lays
out the merged tree), the plan carried out on the data (dup.apply_model) and the layout of the
whole tree (layout.Formatter), with the default rules (rules.Config()). It prints one row per
tree: node count, time (median of --runs runs; a tree whose first run takes longer than --slow
seconds runs once), the share of the copy plan in it, and an output fingerprint: a hash of the
copy plan, every node position, every reroute and link of the result (layout.Formatter.geometry)
and the label positions, rounded to 0.001 units, so two runs can be compared exactly.

  --save FILE     keep the rows (time and fingerprint per tree) as a baseline
  --compare FILE  print old time, new time, speedup and "same" / "DIFFERENT" output per tree
                  against a saved baseline, and the totals; exits 1 if any output differs
  --profile       run each tree once under cProfile and print the top functions by cumulative
                  time and by own time (--top N rows); no timing table
  --jobs N        run the trees in N processes (faster, for checking fingerprints; the times
                  are less reliable, as the processes share the machine)

The layout is deterministic and its search budgets are counted in layouts, not seconds, so a
change that only makes the code faster must keep every fingerprint.
"""
import argparse
import glob
import hashlib
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nodefmt import dup, rules  # noqa: E402
from nodefmt.layout import Formatter  # noqa: E402
from nodefmt.model import Model  # noqa: E402


def load(path):
    """The model data of a JSON file of tools/dump_tree.py (or plain model data)."""
    with open(path) as f:
        j = json.load(f)
    return j["data"] if "data" in j else j


def format_once(data):
    """One offline pass on model data: copy plan, plan applied, layout. Returns (plan,
    formatter, seconds of the copy plan)."""
    with rules.applied(rules.Config()):
        t0 = time.perf_counter()
        plan = dup.plan(data, 'relayout')
        tp = time.perf_counter() - t0
        if dup.changes(plan, data):
            data, _ = dup.apply_model(data, plan)
        f = Formatter(Model(data)).run()
    return plan, f, tp


def _canon(v):
    """v as plain data with floats rounded (to 0.001) and tuples as lists, for hashing."""
    if isinstance(v, float):
        r = round(v, 3)
        return 0.0 if r == 0 else r
    if isinstance(v, dict):
        return {str(k): _canon(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set, frozenset)):
        out = [_canon(x) for x in v]
        if isinstance(v, (set, frozenset)):
            out.sort(key=lambda x: json.dumps(x, sort_keys=True))
        return out
    return v


def fingerprint(plan, f):
    """A short hash of the output: the copy plan, the geometry Blender would draw (node
    positions, reroutes, links, frames, swaps) and the label positions."""
    geo = f.geometry()
    for k in ("nodes", "reroutes", "links"):
        geo[k] = sorted((_canon(x) for x in geo[k]), key=lambda x: json.dumps(x, sort_keys=True))
    labels = sorted([repr(k), _canon(v)] for k, v in getattr(f, 'label_pts', {}).items())
    blob = json.dumps([_canon(plan), _canon(geo), _canon(labels)], sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()[:12]


def nodes_of(data):
    """Node count of a tree: real nodes, no frames and no reroutes."""
    return len(Model(data).real)


def bench_one(path, runs, slow):
    """Time one tree: median of `runs` runs (one if the first takes over `slow` seconds).
    Returns a row dict (name, nodes, seconds, plan seconds, runs, fingerprint)."""
    data = load(path)
    times, fps, tps = [], set(), []
    for k in range(runs):
        t0 = time.perf_counter()
        plan, f, tp = format_once(data)
        times.append(time.perf_counter() - t0)
        tps.append(tp)
        fps.add(fingerprint(plan, f))
        if times[0] > slow:
            break
    fp = fps.pop() if len(fps) == 1 else "NONDETERMINISTIC"
    return {"tree": os.path.basename(path)[:-5], "nodes": nodes_of(data), "seconds": round(statistics.median(times), 3),
            "plan": round(statistics.median(tps), 3), "runs": len(times), "fp": fp}


def _bench_args(a):
    """bench_one for a process pool (one argument tuple)."""
    return bench_one(*a)


def profile_one(path, top):
    """Run one tree once under cProfile; print the top functions by cumulative and own time."""
    import cProfile
    import io
    import pstats
    data = load(path)
    pr = cProfile.Profile()
    t0 = time.perf_counter()
    pr.enable()
    format_once(data)
    pr.disable()
    print(f"\n=== {os.path.basename(path)}: {nodes_of(data)} nodes, {time.perf_counter() - t0:.2f} s (profiled)")
    for key in ("cumulative", "tottime"):
        s = io.StringIO()
        pstats.Stats(pr, stream=s).strip_dirs().sort_stats(key).print_stats(top)
        lines = s.getvalue().splitlines()
        start = next((n for n, l in enumerate(lines) if l.strip().startswith("ncalls")), 0)
        print(f"--- by {key}")
        print("\n".join(lines[start:]))


def main(argv=None):
    """Command line (see the module docstring)."""
    ap = argparse.ArgumentParser(prog="bench.py", description="Benchmark the offline formatter.")
    ap.add_argument("corpus", help="folder of tree JSON files (tools/dump_tree.py)")
    ap.add_argument("--runs", type=int, default=3, help="runs per tree, the median is reported")
    ap.add_argument("--slow", type=float, default=10.0, help="a tree slower than this (s) runs once")
    ap.add_argument("--only", default=None, help="only the files whose name contains this text")
    ap.add_argument("--jobs", type=int, default=1, help="processes (fingerprint checks)")
    ap.add_argument("--save", default=None, help="save the rows as a baseline file")
    ap.add_argument("--compare", default=None, help="compare with a saved baseline file")
    ap.add_argument("--profile", action="store_true", help="cProfile each tree once")
    ap.add_argument("--top", type=int, default=30, help="--profile: rows per table")
    args = ap.parse_args(argv)
    paths = sorted(glob.glob(os.path.join(args.corpus, "*.json")))
    if args.only:
        paths = [p for p in paths if args.only in os.path.basename(p)]
    if not paths:
        sys.exit(f"no *.json in {args.corpus}")
    if args.profile:
        for p in paths:
            profile_one(p, args.top)
        return 0
    base = None
    if args.compare:
        with open(args.compare) as f:
            base = {r["tree"]: r for r in json.load(f)["rows"]}
    if args.jobs > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(args.jobs) as ex:
            rows = list(ex.map(_bench_args, [(p, args.runs, args.slow) for p in paths]))
    else:
        rows = []
        for p in paths:
            rows.append(bench_one(p, args.runs, args.slow))
            if base is None:
                r = rows[-1]
                print(f"{r['tree'][:44]:44} {r['nodes']:5d} {r['seconds']:9.3f} s  plan {r['plan']:7.3f} s"
                      f"  x{r['runs']}  {r['fp']}", flush=True)
    status = 0
    if base is not None:
        print(f"{'tree':44} {'nodes':>5} {'old s':>9} {'new s':>9} {'speedup':>8}  output")
        to = tn = 0.0
        for r in rows:
            b = base.get(r["tree"])
            if b is None:
                print(f"{r['tree'][:44]:44} {r['nodes']:5d} {'-':>9} {r['seconds']:9.3f} {'-':>8}  (new)")
                continue
            same = "same" if b["fp"] == r["fp"] else "DIFFERENT"
            if same != "same":
                status = 1
            to += b["seconds"]
            tn += r["seconds"]
            sp = b["seconds"] / r["seconds"] if r["seconds"] > 0 else float('inf')
            print(f"{r['tree'][:44]:44} {r['nodes']:5d} {b['seconds']:9.3f} {r['seconds']:9.3f} {sp:7.2f}x  {same}")
        print(f"{'TOTAL':44} {'':5} {to:9.3f} {tn:9.3f} {to / tn if tn else 0:7.2f}x  "
              f"{'all same' if status == 0 else 'SOME DIFFERENT'}")
    else:
        print(f"TOTAL {sum(r['seconds'] for r in rows):.3f} s over {len(rows)} trees")
    if args.save:
        with open(args.save, "w") as f:
            json.dump({"python": sys.version.split()[0], "runs": args.runs, "rows": rows}, f, indent=1)
        print(f"saved {args.save}")
    return status


if __name__ == "__main__":
    sys.exit(main())
