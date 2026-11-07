# Promo Finder (Kuku, Problem 1)

Finds 20-60s promo clips (hook in first 3s, unresolved ending, stands alone) in microdrama screenplays.

## Pipeline
parse.py -> score.py (LLM proposes per episode) -> candidates.py (code snaps timestamps to legal cuts)
-> validate.py (code re-checks, rejects hallucinated hooks/cliffhangers) -> rank.py (score + diversity + 1 LLM re-rank) -> outputs/

## Run
    pip install -r requirements.txt
    export LLM_API_KEY=...                      # any OpenAI-compatible endpoint
    # edit model / base_url in config.yaml (Gemini free tier is preconfigured)
    python run.py <folder_with_episode_txt_files> config.yaml
    python run.py data/sample config.mock.yaml  # offline plumbing test, no API (heuristic, NOT an LLM judgement)

Outputs: outputs/promos.md (ranked), promos.json, rejected.json (with reasons), review.csv (hand-label for quality check), raw/ (unedited LLM replies).

## App (run on a new story, or review results)
    pip install -r requirements.txt
    streamlit run app.py
- **Run on new scripts:** upload the episode .txt files (or a .zip), enter model / base URL / API key (or choose the offline mode), press Run, read the picks. Each run is saved in `runs/<time>/`.
- **View a results folder:** browse the picks, read each clip's lines from the script, label good / ok / bad plus a failure type ("Save labels" writes `review.csv`), and see yield per episode.
`outputs/`, `runs/` and `data/pack/` are git-ignored because they contain Kuku's content: run the app locally or keep any deployment private.
CLI equivalent: `python run.py <folder> config.yaml [out_dir]`.

## Input format
One `.txt` per episode, in the pack's format: header lines (`EPISODE NUMBER:`, `EPISODE LOGLINE:`, `CONTINUITY NOTES:`), then blocks like

    **MARA (Furious):**
    Start: (00:01.00) | End: (00:03.50)
    "You lied to me for ten years!"

Block names CAMERA / ACTION / SOUND FX are non-dialogue; any other name is a speaker. Files with no timed blocks are skipped with a warning.
`data/sample/` is a synthetic example of the format.

## Running on a new show
    python run.py <new_folder> config.yaml
Saved LLM replies are cached with a hash of the exact prompt (`outputs/raw/*.key`), so replies from another show are never reused.
Use a clean `outputs/` for a clean deliverable (old files are overwritten, not merged).
To use another model, change `model`, `base_url`, `api_key_env` in `config.yaml` (any OpenAI-compatible `/chat/completions` endpoint).

## Assumptions
- Input format = the pack's: `**CAMERA|ACTION|SOUND FX|NAME (tone):**` blocks with `Start: (mm:ss.ff) | End: (mm:ss.ff)`.
- A cut may not land inside a spoken line. LLM timestamps are untrusted and moved to the nearest legal cut within 4s.
- Multi-segment promos are supported within one episode only.

## Known limits
Text only (no acting, visuals, audio); no cross-episode joins; ranking weights are untested against real viewer data
(real test = A/B the picks on view-through and installs).
# kuku-assignment
