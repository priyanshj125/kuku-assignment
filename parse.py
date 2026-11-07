"""Parse Kuku screenplay files -> {ep: {num, logline, continuity, blocks[], dur}}.
Format (verified on all 50 episodes): header lines, then SCENE n / Scene heading, then blocks:
  **CAMERA:** | **ACTION:** | **SOUND FX:** | **NAME (tone):**   followed by  'Start: (mm:ss.ff) | End: (mm:ss.ff)'  and text."""
import re, json, sys, pathlib

TS = r"(\d+):(\d{2}(?:\.\d+)?)"
HEAD = re.compile(r"^\*\*(.+?):\*\*\s*$")
SE = re.compile(rf"^Start:\s*\(?{TS}\)?\s*\|\s*End:\s*\(?{TS}\)?")
NONDIALOGUE = {"CAMERA", "ACTION", "SOUND FX"}

def sec(m, s): return int(m) * 60 + float(s)
def mmss(t): return f"{int(t // 60):02d}:{t % 60:05.2f}"

def parse_episode(path):
    txt = pathlib.Path(path).read_text(encoding="utf-8")
    g = lambda k: (re.search(rf"^{k}:\s*(.+)$", txt, re.M) or [None, ""])[1].strip()
    num = re.search(r"\d+", g("EPISODE NUMBER") or "") or re.search(r"episode-(\d+)", str(path))
    ep = dict(num=int(num.group(0) if hasattr(num, "group") else 0), logline=g("EPISODE LOGLINE"),
              continuity=g("CONTINUITY NOTES"), blocks=[])
    scene, cur = "SCENE 01", None
    for raw in txt.splitlines():
        line = raw.strip()
        if m := re.match(r"^Scene heading:\s*(.+)$", line):
            scene = m.group(1); continue
        if line.startswith("--- SCRIPT END"):
            break
        if m := HEAD.match(line):
            full = m.group(1)
            name = re.sub(r"\s*\(.*\)\s*$", "", full).strip()
            tone = (re.search(r"\((.*)\)", full) or [None, ""])[1]
            cur = dict(type=name if name in NONDIALOGUE else "DIALOGUE",
                       speaker=None if name in NONDIALOGUE else name, tone=tone, scene=scene, text="")
            ep["blocks"].append(cur); continue
        if cur is not None and cur.get("start") is None and (m := SE.match(line)):
            a = m.groups(); cur["start"], cur["end"] = sec(a[0], a[1]), sec(a[2], a[3]); continue
        if cur is not None and line and not line.startswith(("SCENE ", "Scene start", "Scene end", "Actions and")):
            cur["text"] = (cur["text"] + " " + line.strip('"“”')).strip()
    ep["blocks"] = [b for b in ep["blocks"] if b.get("start") is not None]
    ep["blocks"].sort(key=lambda b: (b["start"], b["end"]))
    for i, b in enumerate(ep["blocks"]): b["i"] = i
    ep["dur"] = max((b["end"] for b in ep["blocks"]), default=0)
    return ep

def parse_all(folder):
    files = sorted(pathlib.Path(folder).glob("*.txt"))
    eps = {}
    for p in files:
        e = parse_episode(p)
        if not e["blocks"]:
            print(f"  WARNING: skipped '{p.name}': no timed blocks found (not in the pack format?)"); continue
        if e["num"] <= 0 or e["num"] in eps:           # missing or duplicate episode number -> next free number
            new = max(eps, default=0) + 1
            print(f"  WARNING: '{p.name}' has no usable episode number; using {new}"); e["num"] = new
        eps[e["num"]] = e
    return eps

if __name__ == "__main__":
    eps = parse_all(sys.argv[1])
    pathlib.Path("outputs").mkdir(exist_ok=True)
    pathlib.Path("outputs/episodes.json").write_text(json.dumps(eps, indent=1))
    from collections import Counter
    print(len(eps), "episodes;", sum(len(e["blocks"]) for e in eps.values()), "blocks;",
          dict(Counter(b["type"] for e in eps.values() for b in e["blocks"])))
    print("dur min/max:", min(e["dur"] for e in eps.values()), max(e["dur"] for e in eps.values()))
