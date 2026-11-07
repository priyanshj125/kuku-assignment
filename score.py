"""LLM proposal step. The LLM sees one episode's timeline (+ neighbouring loglines) and proposes promos with scores.
Two-axis rubric from information-gap theory: context sufficiency and open-question strength.
All timestamps it returns are untrusted: run.py snaps them to legal cuts and validate.py re-checks them."""
import json, os, re, pathlib, urllib.request, hashlib
from parse import mmss
from candidates import heuristic_proposals

SYSTEM = """You pick PROMO clips from AI-generated vertical microdrama episodes (US audience, episodes ~1-3 min).
A promo is a 20-60 second clip posted on TikTok/Instagram/YouTube to pull in NEW viewers. It is usually one continuous
stretch; you may join up to 3 segments from the SAME episode. A good promo:
1. HOOK: in its first 3 seconds something makes a scroller stop (slap, reveal, shocking line, threat).
2. CLIFFHANGER: it ends on a specific unresolved moment so the viewer must know what happens next.
3. STANDS ALONE: a person who never saw the show can follow who is who and what is at stake.
Curiosity needs a gap of the right size: if a stranger cannot follow, the gap is too big; if the clip reveals the answer, there is no gap.
Rules: use ONLY timestamps that appear in the timeline; start and end on line boundaries (never mid-dialogue);
hook_line and cliffhanger must be copied EXACTLY from the timeline text. Do not choose clips that give away the episode's
or series' big payoff (spoiler_risk). Be strict: return fewer promos rather than weak ones.
Scores are integers 1-5: hook, context (5 = a newcomer fully follows), open_question (5 = sharp unresolved question), spoiler_risk (5 = big spoiler).
Return ONLY JSON:
{"promos":[{"segments":[{"start":"mm:ss.ss","end":"mm:ss.ss"}],"hook_line":"...","cliffhanger":"...","hook":int,"context":int,
"open_question":int,"spoiler_risk":int,"why":"one line"}]}"""

def prompt_key(*parts):
    """Short hash of the exact prompt. Saved next to each raw reply so a cached reply is only reused for the SAME input."""
    return hashlib.sha1("\x00".join(parts).encode()).hexdigest()[:12]

def timeline(ep):
    rows = []
    for b in ep["blocks"]:
        if b["type"] == "CAMERA":
            continue
        who = b["speaker"] + (f" ({b['tone']})" if b["tone"] else "") if b["speaker"] else b["type"]
        rows.append(f"[{mmss(b['start'])}-{mmss(b['end'])}] {who}: {b['text'][:220]}")
    return "\n".join(rows)

def build_prompt(num, eps, n):
    ep, prev, nxt = eps[num], eps.get(num - 1), eps.get(num + 1)
    ctx = f"Episode {num}. Logline: {ep['logline']}\nContinuity: {ep['continuity']}\n"
    if prev: ctx += f"Previous episode logline: {prev['logline']}\n"
    if nxt: ctx += f"Next episode logline (shows what the ending sets up): {nxt['logline']}\n"
    return f"{ctx}\nPropose up to {n} promos.\nTIMELINE:\n{timeline(ep)}"

def call_llm(cfg, system, user, model=None):
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    payload = {"model": model or cfg["model"], "temperature": 0,
               "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    req = urllib.request.Request(url, json.dumps(payload).encode(), {
        "Content-Type": "application/json", "Authorization": "Bearer " + os.environ[cfg["api_key_env"]]})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"]

def parse_json(txt):
    return json.loads(re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M).strip())

def parse_t(x):
    if isinstance(x, (int, float)): return float(x)
    m = re.match(r"^(\d+):(\d+(?:\.\d+)?)$", str(x).strip())
    return int(m.group(1)) * 60 + float(m.group(2)) if m else float(x)

def propose(num, eps, cfg, raw_dir):
    """Returns (promos, tokens_estimate). Never raises on bad model output: returns [] and records the error."""
    if cfg["provider"] == "mock":
        return heuristic_proposals(eps[num], cfg), 0
    user = build_prompt(num, eps, cfg["proposals_per_episode"])
    toks = (len(SYSTEM) + len(user)) // 4
    for attempt in range(2):
        raw = call_llm(cfg, SYSTEM, user)
        pathlib.Path(raw_dir, f"ep{num:03d}.try{attempt}.txt").write_text(raw)
        pathlib.Path(raw_dir, f"ep{num:03d}.try{attempt}.key").write_text(prompt_key(SYSTEM, user))
        try:
            return parse_json(raw)["promos"], toks
        except Exception as ex:
            pathlib.Path(raw_dir, f"ep{num:03d}.error.txt").write_text(f"{type(ex).__name__}: {ex}")
    return [], toks
