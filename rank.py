"""Code score + diversity, then an optional global LLM re-rank. Hook and open question dominate (the cliffhanger studies'
outcome is desire-to-continue); context gates (gap must be understandable); spoilers subtract."""
import json, pathlib
from score import call_llm, parse_json, prompt_key
from parse import mmss

def base_score(p):
    s = 0.35 * p["hook"] + 0.40 * p["open_question"] + 0.25 * p["context"]
    s -= 0.3 * max(0, p.get("spoiler_risk", 1) - 2)
    s -= 0.5 if p["context"] <= 2 else 0
    return round(s, 3)

def overlaps(a, b):
    return a["ep"] == b["ep"] and any(s1 < e2 and s2 < e1 for s1, e1 in a["segments"] for s2, e2 in b["segments"])

def select(cands, cfg):
    for c in cands: c["score"] = base_score(c)
    cands.sort(key=lambda c: -c["score"])
    out, per = [], {}
    for c in cands:
        if per.get(c["ep"], 0) >= cfg["max_per_episode_in_top"] or any(overlaps(c, o) for o in out): continue
        per[c["ep"]] = per.get(c["ep"], 0) + 1; out.append(c)
        if len(out) >= cfg["final_top_k"]: break
    return out

def llm_rerank(top, eps, cfg, raw_dir):
    """One call: order the shortlist and say why the first ones go first. Falls back to code order on any failure."""
    rows = "\n".join(f"{i}. ep{c['ep']} [{mmss(c['segments'][0][0])}] hook: {c['hook_line']!r} | cliffhanger: {c['cliffhanger']!r} | "
                     f"{c['why']} | ep logline: {eps[c['ep']]['logline']}" for i, c in enumerate(top))
    system = ("You are a social growth lead for a microdrama app. Order these promo candidates by which to post FIRST to win new viewers "
              "(strongest hook + sharpest unresolved question + clear to a stranger + no big spoiler). Prefer variety of storylines "
              'in the first 5. Return ONLY JSON: {"order":[ids best-first],"reasons":{"id":"one line why it ranks there"}} for the top 5.')
    try:
        saved = pathlib.Path(raw_dir, "rerank.txt"); keyf = saved.with_suffix(".key"); key = prompt_key(system, rows)
        if saved.exists() and keyf.exists() and keyf.read_text().strip() == key:
            raw = saved.read_text()                          # same shortlist as before: reuse, don't re-spend quota
        else:
            raw = call_llm(cfg, system, rows, cfg.get("rerank_model")); saved.write_text(raw); keyf.write_text(key)
        r = parse_json(raw)
        ids = [int(i) for i in r["order"] if str(i).strip().isdigit()]   # models often return ids as strings ("4")
        order = [i for i in dict.fromkeys(ids) if 0 <= i < len(top)]
        order += [i for i in range(len(top)) if i not in order]
        for i, why in r.get("reasons", {}).items():
            if str(i).isdigit() and int(i) < len(top): top[int(i)]["rank_reason"] = why
        return [top[i] for i in order]
    except Exception as ex:
        pathlib.Path(raw_dir, "rerank.error.txt").write_text(repr(ex)); return top
