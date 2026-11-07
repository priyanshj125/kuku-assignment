"""Promo Finder app. (1) Run on NEW scripts: upload episode .txt files, run the pipeline, see the picks.
(2) View / label any results folder (writes review.csv).   streamlit run app.py"""
import csv, io, json, os, pathlib, re, time, zipfile, contextlib, yaml, streamlit as st
from collections import Counter
from parse import parse_all, mmss
from run import main as run_pipeline

st.set_page_config(page_title="Promo Finder", layout="wide")
FAIL = ["", "weak hook", "weak / closure ending", "spoiler", "needs context", "bad cut", "same storyline as another pick", "other"]
COLS = ["rank", "episode", "segments", "hook_line", "cliffhanger", "verdict(good/ok/bad)", "failure_type", "notes"]
fmt = lambda segs: " + ".join(f"{mmss(s)}-{mmss(e)}" for s, e in segs)

def show(out, scripts):
    out = pathlib.Path(out)
    if not (out / "promos.json").exists(): st.error(f"No results in '{out}'."); return
    promos = json.loads((out / "promos.json").read_text()); rej = json.loads((out / "rejected.json").read_text())
    eps = parse_all(scripts) if pathlib.Path(scripts).exists() else {}
    saved = {r["rank"]: r for r in csv.DictReader(open(out / "review.csv", newline=""))} if (out / "review.csv").exists() else {}
    c1, c2, c3 = st.columns(3)
    c1.metric("Final picks", len(promos)); c2.metric("Rejected by checks", len(rej)); c3.metric("Flagged for a human", sum(1 for p in promos if p["flags"]))
    tab1, tab2, tab3 = st.tabs(["Ranked picks + review", "Rejected (with reasons)", "Quality summary"])
    with tab1:
        labels = {}
        for p in promos:
            k = str(p["rank"]); old = saved.get(k, {})
            with st.expander(f"#{p['rank']}  Episode {p['ep']}  |  {fmt(p['segments'])}  ({p['dur']}s)  |  {p['hook_line'][:60]}", expanded=p["rank"] <= 3):
                a, b = st.columns([3, 2])
                a.markdown(f"**Hook:** {p['hook_line']}\n\n**Cliffhanger:** {p['cliffhanger']}\n\n**Why it works:** {p['why']}")
                if p.get("rank_reason"): a.markdown(f"**Why this rank:** {p['rank_reason']}")
                a.caption(f"scores: hook {p['hook']} / context {p['context']} / open question {p['open_question']} / spoiler risk {p['spoiler_risk']}"
                          + (f"  |  needs a human look: {', '.join(p['flags'])}" if p["flags"] else "  |  no flags"))
                if p["ep"] in eps:
                    with a.expander("Show the clip in the script"):
                        for s, e in p["segments"]:
                            st.markdown(f"**{mmss(s)} - {mmss(e)}**")
                            for blk in eps[p["ep"]]["blocks"]:
                                if blk["type"] != "CAMERA" and blk["start"] >= s - .05 and blk["end"] <= e + .05:
                                    st.text(f"[{mmss(blk['start'])}] {blk['speaker'] or blk['type']}: {blk['text']}")
                v = ["", "good", "ok", "bad"]; ov = old.get("verdict(good/ok/bad)", "")
                verdict = b.radio("Your verdict", v, index=v.index(ov) if ov in v else 0, horizontal=True, key=f"v{out}{k}")
                of = old.get("failure_type", "")
                fail = b.selectbox("Failure type", FAIL, index=FAIL.index(of) if of in FAIL else 0, key=f"f{out}{k}")
                note = b.text_input("Notes", old.get("notes", ""), key=f"n{out}{k}")
                labels[k] = [p["rank"], p["ep"], fmt(p["segments"]), p["hook_line"], p["cliffhanger"], verdict, fail, note]
        if st.button("Save labels to review.csv", type="primary", key=f"save{out}"):
            with open(out / "review.csv", "w", newline="") as f:
                w = csv.writer(f); w.writerow(COLS); w.writerows(labels.values())
            st.success(f"Saved {out / 'review.csv'}")
        done = [r for r in labels.values() if r[5]]
        if done: st.caption(f"Labelled: {len(done)}/{len(labels)} (good {sum(r[5]=='good' for r in done)}, ok {sum(r[5]=='ok' for r in done)}, bad {sum(r[5]=='bad' for r in done)}); unsaved until you press Save")
    with tab2:
        kind = lambda e: ("cannot snap to a legal cut" if "snap" in e else "total length outside 20-60 s" if "duration" in e else
                          "cliffhanger is not the clip's last line" if "cliffhanger" in e else "hook not in first 3 s" if "hook line" in e else
                          "cut through a spoken line" if "spoken" in e else e[:50])
        cnt = Counter(kind(e) for r in rej for e in r["errors"])
        if cnt: st.bar_chart(cnt)
        st.dataframe([{"episode": r["ep"], "segments": str(r.get("segments") or r.get("proposal")), "reasons": "; ".join(r["errors"])} for r in rej])
    with tab3:
        n = len(eps) or max([p["ep"] for p in promos] + [r["ep"] for r in rej] + [1])
        st.markdown(f"**Yield per episode** (final picks vs rejected proposals), {n} episodes")
        pe, re_ = Counter(p["ep"] for p in promos), Counter(r["ep"] for r in rej)
        st.bar_chart({"final picks": {e: pe.get(e, 0) for e in range(1, n + 1)}, "rejected": {e: re_.get(e, 0) for e in range(1, n + 1)}})
        rows = list(csv.DictReader(open(out / "review.csv", newline=""))) if (out / "review.csv").exists() else []
        lab = [r for r in rows if r["verdict(good/ok/bad)"]]
        if lab:
            v = Counter(r["verdict(good/ok/bad)"] for r in lab)
            st.markdown(f"**Your labels:** {len(lab)}/{len(promos)} picks: good {v['good']}, ok {v['ok']}, bad {v['bad']}")
            ft = Counter(r["failure_type"] for r in lab if r["failure_type"])
            if ft: st.bar_chart(ft)
        else: st.info("No labels saved yet. Label the picks in the first tab and press Save.")

class Log(io.StringIO):
    def __init__(self, box, bar): super().__init__(); self.box, self.bar = box, bar
    def write(self, s):
        super().write(s); self.box.code(self.getvalue()[-3000:])
        m = re.search(r"\((\d+)/(\d+),", s)
        if m: self.bar.progress(int(m.group(1)) / int(m.group(2)), text=f"Episode {m.group(1)} of {m.group(2)}")
        return len(s)

mode = st.sidebar.radio("Mode", ["Run on new scripts", "View a results folder"])
st.title("Promo Finder")
st.caption("Finds 20-60 s promo clips (hook in the first 3 s, unresolved ending, stands alone) in microdrama screenplays. The tool shortlists; a person decides.")

if mode == "View a results folder":
    show(st.sidebar.text_input("Results folder", "outputs"), st.sidebar.text_input("Episode scripts folder", "data/pack"))
else:
    cfg0 = yaml.safe_load(open("config.yaml"))
    st.subheader("1. Upload the episode scripts")
    st.caption("One .txt per episode, in the pack format (blocks with `Start: (mm:ss.ff) | End: (mm:ss.ff)`). You can upload several .txt files or a .zip.")
    up = st.file_uploader("Episode files", type=["txt", "zip"], accept_multiple_files=True)
    st.subheader("2. Model")
    c1, c2 = st.columns(2)
    provider = c1.radio("Mode", ["LLM (OpenAI-compatible API)", "Offline heuristic (no API, plumbing test only)"], index=0)
    model = c2.text_input("Model", cfg0["model"]); base = c2.text_input("Base URL", cfg0["base_url"])
    key = c1.text_input(f"API key ({cfg0['api_key_env']})", type="password", help="Used only for this run, never saved.")
    sleep = c1.number_input("Seconds between calls (6 = free tier, 0 = paid key)", 0, 60, int(cfg0.get("sleep", 6)))
    rerank = c1.checkbox("LLM re-rank of the final list", cfg0.get("rerank", True))
    if st.button("Run", type="primary", disabled=not up):
        run_dir = pathlib.Path("runs") / time.strftime("%Y%m%d-%H%M%S"); (run_dir / "scripts").mkdir(parents=True)
        for f in up:
            if f.name.lower().endswith(".zip"):
                for m in zipfile.ZipFile(f).namelist():
                    if m.lower().endswith(".txt") and not m.endswith("/"): (run_dir / "scripts" / pathlib.Path(m).name).write_bytes(zipfile.ZipFile(f).read(m))
            else: (run_dir / "scripts" / f.name).write_bytes(f.getvalue())
        eps = parse_all(str(run_dir / "scripts"))
        if not eps: st.error("No readable episodes. Expected .txt files with timed blocks like `Start: (00:01.00) | End: (00:03.50)`."); st.stop()
        st.info(f"Read {len(eps)} episodes, {sum(len(e['blocks']) for e in eps.values())} timed blocks. Running...")
        cfg = dict(cfg0, provider="mock" if provider.startswith("Offline") else "openai_compatible", model=model, base_url=base, sleep=sleep, rerank=rerank)
        if key: os.environ[cfg0["api_key_env"]] = key
        if cfg["provider"] != "mock" and not os.environ.get(cfg0["api_key_env"]): st.error("Enter an API key, or choose the offline mode."); st.stop()
        bar = st.progress(0.0, text="Starting..."); box = st.empty()
        try:
            with contextlib.redirect_stdout(Log(box, bar)): run_pipeline(str(run_dir / "scripts"), cfg, str(run_dir / "outputs"))
            st.session_state["last_run"] = str(run_dir)
        except Exception as ex: st.error(f"Run failed: {type(ex).__name__}: {ex}")
    if st.session_state.get("last_run"):
        rd = st.session_state["last_run"]; st.subheader(f"3. Results ({rd})"); show(pathlib.Path(rd) / "outputs", pathlib.Path(rd) / "scripts")
