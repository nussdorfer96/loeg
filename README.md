# The League of Extraordinary Gentlemen: History Book

A static website that serves as the permanent record of the league: ESPN redraft years (2020-2025) and the Sleeper dynasty era (2026-).
It builds to plain HTML/CSS/JS in `dist/`, so it can be hosted for free (GitHub Pages, Netlify, Cloudflare Pages).

## Layout

```
data/managers.json        <- EDIT ME: who managed which team, every season (people, not team names)
data/lore.json            <- EDIT ME: league stories for the Lore page
data/generated/           <- produced by the scripts (don't hand-edit)
  seasons/YYYY.json       normalized season: teams, games, draft, rosters, lineups, transactions
  league.json             managers, head-to-head, records, awards, stories, lore
raw/espn/                 ESPN league exports (espn_YYYY_core.json)
raw/espn_players/         public ESPN player DB + weekly stat lines (kona_YYYY.json)
raw/espn_archive/         OPTIONAL weekly ESPN box scores + transactions (espn_YYYY_wWW.json)
raw/sleeper/              Sleeper API dumps (league, users, rosters, matchups, transactions, drafts, players)
scripts/
  process_espn.py         raw ESPN -> data/generated/seasons/YYYY.json
  process_sleeper.py      raw Sleeper -> data/generated/seasons/YYYY.json
  aggregate.py            all seasons -> data/generated/league.json (records, H2H, awards, narratives)
  build_site.py           Jinja2 templates in src/ -> dist/
  build_all.py            runs everything in order
  fetch_sleeper.sh        refresh Sleeper data (public API, no auth)
  fetch_espn_players.sh   download the public ESPN player/stat DB for a season
  screenshots.py          headless-Chromium screenshots of key pages
src/templates, src/static Jinja2 page templates, CSS, a little JS
dist/                     BUILD OUTPUT: deploy this folder
```

Requirements: Python 3.10+ and `pip install jinja2` (plus `playwright` only for screenshots).

## Everyday commands

```bash
python3 scripts/build_all.py           # rebuild data + site from whatever raw data is present
python3 scripts/build_all.py --fetch   # refresh live Sleeper data first (do this weekly during the season)
python3 -m http.server 8765 --directory dist   # local preview at http://localhost:8765/
```

## Adding a new season

**Sleeper (2027 onward).** Sleeper creates a new league id every season.
1. Add the id to `data/managers.json` under `sleeper.league_ids`, and add any new Sleeper users to `sleeper.users`
   (`"<user_id>": {"display_name": "...", "manager": "<manager-id>", "confirmed": true}`). New people also go in `managers`.
2. Save the data: `scripts/fetch_sleeper.sh <league_id> 2027` (writes to `raw/sleeper/2027/`).
   The current season (2026) lives directly in `raw/sleeper/`; older ones go in a year subfolder.
3. `python3 scripts/build_all.py`. Each `raw/sleeper/YYYY/` folder gets picked up automatically.
   Champion/runner-up for Sleeper seasons are left empty while in progress; once the playoffs finish, extend
   `process_sleeper.py` to read `winners_bracket.json` (structure already saved) or set them by hand.

**ESPN (if ever needed again).** Drop `espn_YYYY_core.json` (views mTeam, mMatchupScore, mSettings, mDraftDetail, mRoster, mStandings, mNav)
in `raw/espn/`, run `scripts/fetch_espn_players.sh YYYY`, add the slot -> manager entries for that year in `data/managers.json`, rebuild.
Optional weekly files `espn_YYYY_wWW.json` (mTransactions2 + mMatchup + mMatchupScore + mBoxscore + mRoster for one scoringPeriodId)
in `raw/espn_archive/` (or `/home/box/Downloads/espn_archive/`) unlock lineup-based awards (MVP by started points, bench points,
best single-game performances, waiver pickup impact) and the trade/pickup logs. Transactions are deduplicated by id across weeks.

## Editing managers (`data/managers.json`)

* `managers`: one entry per **person** (`id` is the URL slug, e.g. `managers/ryan-nussdorfer.html`). Set `"confirmed": false` on anything
  you're unsure about; it shows an "unconfirmed" badge.
* `espn.slots`: ESPN team id -> list of `{from, to, manager}` ranges. This is how "took over from" lineage is shown. Stats are always
  credited to the person in charge that season: a new owner starts from zero and never inherits the previous owner's record.
* `espn.team_names`: optional overrides, `{"2023": {"7": "Better Name"}}`. Otherwise names come from ESPN.
* `sleeper.users`: Sleeper user id -> manager. `sleeper.team_names` overrides names for users who never set one.

## Adding lore (`data/lore.json`)

Copy an entry in `entries` and edit it:

```json
{ "id": "unique-slug", "title": "The Trade That Shall Not Be Named", "season": 2023, "week": 9,
  "category": "trade", "managers": ["ryan-nussdorfer", "drew-hartman"],
  "body": "Write the story. **bold**, *italic*, [links](https://example.com) and blank-line paragraphs work.", "source": "league" }
```

Categories: `trade, waiver, injury, game, draft, controversy, tradition, other`. Data-driven entries (record games, title games,
draft steals, waiver heists, every archived trade) are generated automatically and don't live in this file.

## How the numbers are computed

* **Player points (ESPN)**: computed from ESPN's public weekly stat lines with this league's exact scoring settings (including D/ST and K
  overrides). Verified against ESPN box scores: 150 of 150 player-weeks matched exactly in the 2020 week 1 check.
* **Draft value**: points above positional replacement (QB12, RB30, WR36, TE12) ranked among drafted QB/RB/WR/TE and compared with
  draft slot. "Steals" = biggest positive gap among top-40 value finishers; "busts" = biggest negative gap in rounds 1-4.
* **Luck**: actual wins minus expected wins from the all-play record.
* **Career W-L**: regular-season head-to-head games. Sleeper's weekly vs-median games show on the Dynasty page but aren't counted in career W-L.
  Playoff W-L counts winners-bracket games only.
* **Score records** use the ESPN era only, because Sleeper dynasty scoring (superflex, yardage bonuses) isn't comparable.
* Without weekly box scores, MVP and pickup awards fall back to "points scored while on the season-ending roster" and show a *provisional* badge.

## Deploying to GitHub Pages

Push the repo, then either serve `dist/` with a Pages workflow (upload `dist` as the artifact) or copy `dist/` into a `gh-pages` branch.
All links are relative and `dist/.nojekyll` is included, so it works under `https://<user>.github.io/<repo>/`.

## Publishing (GitHub Pages)

Live site: https://nussdorfer96.github.io/loeg/

- `main` holds the source (scripts, templates, hand-edited `data/*.json`). Raw league exports (`raw/`) and build outputs are git-ignored and stay on the build box.
- `gh-pages` holds the built `dist/` (plain static files plus `.nojekyll`), which GitHub Pages serves from the branch root.
- Weekly update: `bash scripts/publish.sh` refreshes Sleeper data (`--fetch`), rebuilds, runs `scripts/check_links.py`, and pushes `dist/` to `gh-pages`. Use `--no-fetch` to skip the Sleeper refresh.
- Power rankings (Dynasty overview, "Power Rankings" dropdown): run `bash scripts/publish_power_rankings.sh` on Wednesday after Sleeper's ~3 AM ET waiver run. It runs `scripts/power_rankings.py` for the current Sleeper week (writes `data/generated/power_rankings/<season>_wNN.json` + `latest.json`), then `scripts/publish.sh`. `publish.sh` alone never recomputes rankings; it re-renders the latest saved JSON, so a Tuesday refresh keeps last week's rankings. Blurbs are auto-written from league data unless `data/power_rankings_blurbs/<season>_wNN.json` (`{"<manager-id>": "text"}`) overrides them. `--drafts` also writes a preview to `drafts/`.
- Link previews use `data/site.json` (`url` must stay the live address so `og:image` resolves).
- Hand-edited data: `data/managers.json`, `data/lore.json` (lore + press-conference archive), `data/draft_order_games.json`, `data/site.json`.
