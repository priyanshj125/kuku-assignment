"""Pure-code timeline logic: legal cut points, snapping LLM timestamps to them, and an offline heuristic proposer."""
import re

EPS = 0.05
HOOK_WORDS = re.compile(r"\b(slap\w*|pregnan\w*|divorce\w*|lied|lie|secret|affair|dead|die|kill\w*|dagger|sword|blood|"
                        r"betray\w*|traitor|poison\w*|arrest\w*|guards?|wedding|duke|duchess|truth|mistake|never|"
                        r"get out|who are you|how dare|forgive|curse\w*|murder\w*|mine|baby|heir|crown|king|queen)\b", re.I)
ACTION_HOOK = re.compile(r"\b(slaps?|slapped|throws?|grabs?|screams?|shoves?|reveals?|bursts?|storms?|drops?|faints?|"
                         r"draws?|unsheathes?|gasps?|recoils?|shatters?|collapses?)\b", re.I)
CLIFF_TONE = re.compile(r"(cliffhanger|ominous|gasp|stunned|shock|cut to black|silence|dread|freeze|frozen)", re.I)

def dlg(b): return b["type"] == "DIALOGUE"
def texty(b): return b["type"] != "CAMERA" and b["text"]

def legal_points(ep):
    """Cut times where no dialogue block is mid-line. starts/ends are sorted lists of seconds."""
    d = [(b["start"], b["end"]) for b in ep["blocks"] if dlg(b)]
    ok = lambda t: not any(s + EPS < t < e - EPS for s, e in d)
    starts = sorted({round(b["start"], 2) for b in ep["blocks"] if ok(b["start"])})
    ends = sorted({round(b["end"], 2) for b in ep["blocks"] if ok(b["end"])})
    return starts, ends

def snap(ep, s, e, cfg, pts=None):
    """Move proposed (s,e) to the nearest legal pair within snap_radius that satisfies length limits."""
    starts, ends = pts or legal_points(ep)
    r = cfg["snap_radius"]
    best = None
    for a in (x for x in starts if abs(x - s) <= r):
        for b in (x for x in ends if abs(x - e) <= r):
            if cfg["min_len"] <= b - a <= cfg["max_len"]:
                cost = abs(a - s) + abs(b - e)
                if best is None or cost < best[0]:
                    best = (cost, a, b)
    return (best[1], best[2]) if best else None

def blocks_in(ep, s, e, start_only=True):
    return [b for b in ep["blocks"] if b["start"] >= s - EPS and (b["start"] < e if start_only else b["end"] <= e + EPS)]

def hook_signal(ep, s, cfg):
    w = [b for b in ep["blocks"] if texty(b) and s - EPS <= b["start"] <= s + cfg["hook_window"]]
    txt = " ".join(b["text"] for b in w)
    sc = 2 * bool(HOOK_WORDS.search(txt)) + 2 * bool(ACTION_HOOK.search(txt)) + ("!" in txt or "?" in txt)
    return min(sc, 5), (w[0] if w else None)

def last_block(ep, e):
    c = [b for b in ep["blocks"] if texty(b) and b["end"] <= e + EPS]
    return max(c, key=lambda b: (b["end"], b["start"])) if c else None

def cliff_signal(ep, e):
    b = last_block(ep, e)
    if not b: return 0, None
    t = b["text"].strip()
    sc = 2 * t.endswith(("?", "...", "—", "-")) + 2 * bool(HOOK_WORDS.search(t) or CLIFF_TONE.search(t) or ACTION_HOOK.search(t)) + t.endswith("!")
    sc -= 2 * bool(re.search(r"\b(thank you|goodbye|good night|the end)\b", t, re.I))
    return max(0, min(sc, 5)), b

def heuristic_proposals(ep, cfg):
    """Offline stand-in for the LLM: best non-overlapping windows by hook+cliffhanger heuristics."""
    starts, ends = legal_points(ep)
    wins = []
    for s in starts:
        h, hb = hook_signal(ep, s, cfg)
        for e in ends:
            if cfg["min_len"] <= e - s <= cfg["max_len"]:
                c, cb = cliff_signal(ep, e)
                wins.append((h + c - abs((e - s) - 40) / 40, s, e, h, c, hb, cb))
    wins.sort(reverse=True)
    out = []
    for _, s, e, h, c, hb, cb in wins:
        if all(e <= p["_e"] or s >= p["_s"] for p in out):
            out.append(dict(_s=s, _e=e, segments=[dict(start=s, end=e)], hook=max(1, h), context=3, open_question=max(1, c),
                            spoiler_risk=1, hook_line=hb["text"] if hb else "", cliffhanger=cb["text"] if cb else "",
                            why="[offline heuristic - not an LLM judgement]"))
        if len(out) >= cfg["proposals_per_episode"]:
            break
    return out
