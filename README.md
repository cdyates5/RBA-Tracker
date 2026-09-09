# RBA Policy Tracker

Self-updating dashboard for the Reserve Bank of Australia's Monetary Policy Board.

Live at `https://YOUR_USERNAME.github.io/rba-tracker/`

---

## Files

| File | Edit it? | Purpose |
|---|---|---|
| `data.json` | **Yes** — after each meeting | All editorial content: meeting outcomes, member views, sentiment scores, market pricing, bank calls |
| `template.html` | Rarely | Page layout and styling, with `{{TOKEN}}` placeholders |
| `rebuild.py` | Rarely | Fetches live data, fills tokens, writes `index.html` |
| `index.html` | **Never** | Generated output. Overwritten on every run |
| `.github/workflows/refresh.yml` | Rarely | The schedule |
| `.nojekyll` | Never | Empty file; stops GitHub running Jekyll |

---

## What updates automatically vs by hand

**Automatic, every run — no action needed:**

| Field | Source |
|---|---|
| Cash rate level and effective date | RBA statistical table F1.1 (series `FIRMMCRTD`) |
| Rate-path step chart | Same, merged onto a static pre-2024 baseline |
| Cash-rate overlay on the sentiment chart | Derived from the same path |
| AUD/USD | frankfurter.app, falling back to open.er-api.com |
| Next-meeting countdown | `MEETINGS` dict in `rebuild.py` |
| Timestamps and editorial age warning | System clock |

**By hand, in `data.json` after each meeting:**

Meeting outcomes and vote splits, board member views and sentiment scores, market pricing rows, bank forecasts, CPI and unemployment indicator cards.

These are editorial judgements or series with no free API. They cannot be fetched honestly, so instead they carry an `editorial_as_of` date that is printed on the dashboard. Past 40 days it shows the age; past 75 days it turns red and asks to be reviewed. Stale commentary is visible rather than silent — which is the failure this design is guarding against.

---

## After each RBA meeting

Open `data.json` and update:

1. `editorial_as_of` — set to the meeting date. **Do this every time**, it drives the staleness warning.
2. `last_decision` — date, action (`hike` / `cut` / `hold`), `change_bp`, rate, vote, note.
3. `meetings[]` — change the meeting that just happened from `pending` to its outcome; mark the next one `"next": true`.
4. `setup_blurb` — the framing for the next decision.
5. `indicators[]` — new CPI or labour force prints.
6. `members[]` — any new speeches; adjust `score` (−10 dove to +10 hawk).
7. `sentiment_recent` — append `["Mon YYYY", score]` for the new month.
8. `pricing_rows[]` and `banks[]` — refresh from the ASX RBA Rate Tracker and bank research.

You do **not** need to touch the cash rate itself — that comes from the RBA.

Commit and push. The next scheduled run rebuilds, or trigger it immediately from the Actions tab.

---

## Schedule

| Cron (UTC) | Local | What |
|---|---|---|
| `0 21 * * *` | 07:00 AEST daily | Refresh rate and FX |
| `30 5 * * 1-5` | 15:30 AEST weekdays | Lands after any RBA decision |

A `keepalive` job commits a heartbeat on the 1st of each month. This exists because **GitHub disables scheduled workflows after 60 days of repository inactivity** — silently, with no notification. The heartbeat keeps the repo active so the cron never switches itself off.

The build fails loudly if `index.html` comes out empty or with unsubstituted tokens, rather than publishing a broken page.

---

## Running locally

```bash
python3 rebuild.py && open index.html
```

Python 3.8+, standard library only.

---

## Yearly maintenance

When the RBA publishes next year's meeting calendar, update the `MEETINGS` dict in `rebuild.py`. Watch the UTC offsets: Australian eastern time is +11 in Jan–Mar and Nov–Dec, +10 in Apr–Oct.

---

## Troubleshooting

**Page not updating** — check the Actions tab. If the last run is ~60 days old, the schedule was disabled; click **Enable workflow**, then **Run workflow**.

**Cash rate looks stale, log says "bundled fallback"** — the RBA fetch failed. The page still builds from the bundled path. If it persists, the RBA may have changed the CSV layout; `parse_rba_csv()` in `rebuild.py` is where to look.

**AUD/USD shows `n/a`** — both FX APIs were unreachable. Harmless, retries next run.

**404 on the live URL** — the served file must be named `index.html` at the repo root, and Pages must point at branch `main`, folder `/ (root)`.
