"""Hard checks in code, independent of the LLM. Returns (errors, flags). Any error => promo is rejected and logged."""
import re, difflib
from candidates import legal_points, blocks_in, last_block, texty, dlg, EPS, CLIFF_TONE

CLOSURE = re.compile(r"\b(thank you|goodbye|good night|the end|forgive you|at last|finally safe)\b", re.I)
norm = lambda s: re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()

def similar(claim, text):
    a, b = norm(claim)[:60], norm(text)
    return bool(a) and (a[:30] in b or difflib.SequenceMatcher(None, a, b[:len(a) + 10]).ratio() >= 0.7)

def check(p, ep, cfg):
    errs, flags = [], []
    segs = p["segments"]
    total = sum(e - s for s, e in segs)
    if not (cfg["min_len"] - EPS <= total <= cfg["max_len"] + EPS):
        errs.append(f"total duration {total:.1f}s outside {cfg['min_len']}-{cfg['max_len']}s")
    starts, ends = legal_points(ep)
    for s, e in segs:
        if s < 0 or e > ep["dur"] + EPS or e <= s: errs.append("segment outside episode")
        if round(s, 2) not in starts or round(e, 2) not in ends: errs.append("segment cuts through a spoken line")
    if errs: return errs, flags
    s0, e_last = segs[0][0], segs[-1][1]
    hook_blocks = [b for b in blocks_in(ep, s0, s0 + cfg["hook_window"] + 1.0) if texty(b)]
    if not hook_blocks: errs.append("nothing happens in the first 3s")
    elif p.get("hook_line") and not any(similar(p["hook_line"], b["text"]) for b in hook_blocks):
        errs.append("claimed hook line not in first 3s of clip (possible hallucination)")
    lb = last_block(ep, e_last)
    if p.get("cliffhanger") and lb and not similar(p["cliffhanger"], lb["text"]):
        errs.append("claimed cliffhanger is not the clip's last line (possible hallucination)")
    if lb and CLOSURE.search(lb["text"]): errs.append("clip ends on a closure line")
    # soft flags: a human should look
    if p.get("context", 5) <= 2: flags.append("low context: newcomer may be lost")
    if p.get("spoiler_risk", 1) >= 4: flags.append("spoiler risk")
    if lb and not (lb["text"].rstrip().endswith(("?", "...", "—", "-", "!")) or CLIFF_TONE.search(lb["text"])) and p.get("open_question", 0) < 4:
        flags.append("ending not clearly unresolved")
    if lb and not dlg(lb) and len(segs) == 1 and (e_last - lb["start"]) < 0.5: flags.append("ends on a very short beat")
    return errs, flags
