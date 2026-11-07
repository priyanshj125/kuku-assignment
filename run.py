"""python run.py <episodes_folder> [config.yaml] [out_dir]
-> outputs/promos.md, promos.json, rejected.json, review.csv (fill in for the quality check), raw/ (unedited LLM replies)"""
import sys, json, csv, pathlib, yaml, time, urllib.error
from parse import parse_all, mmss
from score import propose, parse_t
from candidates import snap, legal_points
from validate import check
from rank import select, llm_rerank

def propose_with_retry(num, eps, cfg, raw, retries=8):
    """Wraps propose() with retry logic for transient HTTP 5xx / 429 / network errors.
    Reuses existing valid raw output if present so resumed runs don't re-burn API quota."""
    from score import parse_json, build_prompt, SYSTEM, prompt_key
    user = build_prompt(num, eps, cfg["proposals_per_episode"])
    key = prompt_key(SYSTEM, user)
    for att in (0, 1):
        f = pathlib.Path(raw, f"ep{num:03d}.try{att}.txt"); k = f.with_suffix(".key")
        # reuse a saved reply ONLY if it was made from this exact prompt (stale replies from another show are ignored)
        if f.exists() and k.exists() and k.read_text().strip() == key:
            try:
                data = parse_json(f.read_text())
                if "promos" in data:
                    toks = (len(SYSTEM) + len(user)) // 4
                    print(f"  [ep{num:03d}] reused saved output from {f.name}", flush=True)
                    return data["promos"], toks
            except Exception:
                pass

    for attempt in range(retries):
        try:
            res = propose(num, eps, cfg, raw)
            time.sleep(cfg.get("sleep", 6))  # stay under free-tier RPM (set sleep: 0 in config for a paid key)
            return res
        except (urllib.error.HTTPError, urllib.error.URLError, OSError, TimeoutError) as e:
            code = getattr(e, "code", None)
            if attempt < retries - 1:
                if code == 429:
                    wait = min(60 * (2 ** attempt), 300)
                elif code in (500, 502, 503, 504):
                    wait = 15 * (attempt + 1)
                else:
                    wait = 20 * (attempt + 1)
                print(f"  [ep{num:03d}] {type(e).__name__} ({e}) – retrying in {wait}s (attempt {attempt+1}/{retries})", flush=True)
                time.sleep(wait)
            else:
                raise

def main(folder, cfg_path="config.yaml", out_dir="outputs"):
    cfg = cfg_path if isinstance(cfg_path, dict) else yaml.safe_load(open(cfg_path))
    out = pathlib.Path(out_dir); raw = out / "raw"; raw.mkdir(parents=True, exist_ok=True)
    eps = parse_all(folder)
    if not eps:
        sys.exit(f"No readable episodes in '{folder}'. Need .txt files in the pack format (see README: Input format).")
    ok, rejected, n_prop, toks = [], [], 0, 0
    t0, total = time.time(), len(eps)
    for idx, num in enumerate(sorted(eps), 1):
        ep = eps[num]; pts = legal_points(ep)
        print(f"  [ep{num:03d}] asking the model...", flush=True)
        props, t = propose_with_retry(num, eps, cfg, raw); toks += t; n_prop += len(props)
        kept = 0
        for p in props:
            try:
                segs = []
                for sg in p["segments"]:
                    s, e = parse_t(sg["start"]), parse_t(sg["end"])
                    segs.append((s, e))
                # snap: single segment -> snap with length limits; multi-segment -> snap each to legal points only
                if len(segs) == 1:
                    sn = snap(ep, segs[0][0], segs[0][1], cfg, pts)
                    if not sn: raise ValueError("cannot snap to a legal 20-60s cut")
                    segs = [sn]
                else:
                    starts, ends = pts
                    near = lambda xs, v: min(xs, key=lambda x: abs(x - v))
                    segs = [(near(starts, s), near(ends, e)) for s, e in segs]
                p = dict(p, ep=num, segments=segs, dur=round(sum(e - s for s, e in segs), 1))
                for k in ("hook", "context", "open_question", "spoiler_risk"): p[k] = int(p.get(k, 3))
                errs, flags = check(p, ep, cfg)
            except Exception as ex:
                rejected.append(dict(ep=num, proposal=p.get("segments"), errors=[f"{type(ex).__name__}: {ex}"])); continue
            if errs:
                rejected.append(dict(ep=num, segments=[[mmss(s), mmss(e)] for s, e in segs], errors=errs)); continue
            p["flags"] = flags
            if kept < cfg["top_k_per_episode"]: ok.append(p); kept += 1
        print(f"  [ep{num:03d}] {len(props)} proposed, {kept} kept  ({idx}/{total}, {time.time() - t0:.0f}s elapsed)", flush=True)
    top = select(ok, cfg)
    if cfg["provider"] != "mock" and cfg.get("rerank") and len(top) > 1:
        top = llm_rerank(top, eps, cfg, raw)
    for i, c in enumerate(top, 1): c["rank"] = i
    fmt = lambda segs: " + ".join(f"{mmss(s)}-{mmss(e)}" for s, e in segs)
    (out / "promos.json").write_text(json.dumps(top, indent=1))
    (out / "rejected.json").write_text(json.dumps(rejected, indent=1))
    md = [f"# Promo picks: {len(eps)} episodes, {n_prop} proposed, {len(ok)} passed validation, {len(rejected)} rejected, "
          f"~{toks:,} input tokens\n"]
    for c in top:
        md.append(f"## #{c['rank']}  Episode {c['ep']}  {fmt(c['segments'])}  ({c['dur']}s)\n"
                  f"- **Hook:** {c['hook_line']}\n- **Cliffhanger:** {c['cliffhanger']}\n- **Why it works:** {c['why']}\n"
                  + (f"- **Why this rank:** {c['rank_reason']}\n" if c.get("rank_reason") else "")
                  + f"- scores: hook {c['hook']} / context {c['context']} / open-question {c['open_question']} / spoiler-risk {c['spoiler_risk']}\n"
                  f"- **Needs a human look:** {', '.join(c['flags']) or 'no flags'}\n")
    (out / "promos.md").write_text("\n".join(md))
    with open(out / "review.csv", "w", newline="") as f:     # fill in verdict/failure_type by hand = the quality check
        w = csv.writer(f); w.writerow(["rank", "episode", "segments", "hook_line", "cliffhanger", "verdict(good/ok/bad)", "failure_type", "notes"])
        for c in top: w.writerow([c["rank"], c["ep"], fmt(c["segments"]), c["hook_line"], c["cliffhanger"], "", "", ""])
    print(f"{len(top)} promos -> {out}/promos.md | proposed {n_prop}, passed {len(ok)}, rejected {len(rejected)}")

if __name__ == "__main__":
    main(*sys.argv[1:])
