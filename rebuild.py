#!/usr/bin/env python3
"""
rebuild.py - RBA Policy Tracker build script
=============================================
Reads  : template.html  (layout, with {{TOKEN}} placeholders)
         data.json      (editorial content you maintain by hand)
Fetches: cash rate + rate path  -> RBA statistical table F1.1
         AUD/USD               -> frankfurter.app, then open.er-api.com
Writes : index.html

Design note on what is and is not automatic
-------------------------------------------
AUTOMATIC  cash rate level, effective date, direction of last move, full
           rate-path chart, AUD/USD, next-meeting countdown, timestamps,
           sentiment series extension, staleness warnings.
MANUAL     meeting outcomes, board member views, sentiment scores, market
           pricing, bank forecasts. These are editorial judgements or have
           no free API. They live in data.json and carry an as-of date that
           is printed on the page, so stale commentary is visible rather
           than silent.

Every fetch has a fallback. A network failure degrades one field and is
logged; it never fails the build or blanks the page.
"""

import json
import sys
import csv
import io
import datetime as dt
import urllib.request

TEMPLATE = "template.html"
DATA     = "data.json"
OUTPUT   = "index.html"

AEST = dt.timezone(dt.timedelta(hours=10))

# RBA F1.1 - Interest Rates and Yields, Money Market, Daily.
# Series FIRMMCRTD is the cash rate target.
RBA_F11 = "https://www.rba.gov.au/statistics/tables/csv/f1.1-data.csv"
RBA_SERIES_ID = "FIRMMCRTD"

# Baseline rate path to 2023. These are settled historical facts that will
# never change, so they are not re-fetched. Live data from F1.1 is merged
# on top of this, which keeps the chart complete even if the fetch fails.
BASELINE_PATH = [
    ["1999-11-03",5.00],["2000-02-02",5.25],["2000-03-01",5.50],["2000-05-03",5.75],
    ["2000-08-02",6.00],["2000-10-04",6.25],["2001-02-07",6.00],["2001-03-07",5.75],
    ["2001-04-04",5.50],["2001-05-02",5.00],["2001-07-04",4.50],["2001-09-05",4.25],
    ["2002-06-05",4.50],["2002-11-06",4.75],["2003-11-05",5.00],["2003-12-03",5.25],
    ["2005-03-02",5.50],["2006-05-03",5.75],["2006-08-02",6.00],["2006-11-08",6.25],
    ["2007-02-07",6.50],["2007-08-08",6.75],["2008-02-05",7.00],["2008-03-04",7.25],
    ["2008-09-03",7.00],["2008-10-07",6.00],["2008-11-04",5.25],["2008-12-02",4.25],
    ["2009-02-03",3.25],["2009-03-03",3.00],["2009-10-06",3.25],["2009-11-03",3.50],
    ["2009-12-01",3.75],["2010-03-02",4.00],["2010-04-06",4.25],["2010-05-04",4.50],
    ["2010-11-02",4.75],["2011-11-01",4.50],["2011-12-06",4.25],["2012-05-01",3.75],
    ["2012-06-05",3.50],["2012-10-02",3.25],["2012-12-04",3.00],["2013-05-07",2.75],
    ["2013-08-06",2.50],["2015-02-03",2.25],["2015-05-05",2.00],["2016-05-03",1.75],
    ["2016-08-02",1.50],["2019-06-04",1.25],["2019-07-02",1.00],["2019-10-01",0.75],
    ["2020-03-03",0.50],["2020-03-19",0.25],["2020-11-03",0.10],["2022-05-03",0.35],
    ["2022-06-07",0.85],["2022-07-05",1.35],["2022-08-02",1.85],["2022-09-06",2.35],
    ["2022-10-04",2.60],["2022-11-01",2.85],["2022-12-06",3.10],["2023-02-07",3.35],
    ["2023-03-07",3.60],["2023-05-02",3.85],["2023-06-06",4.10],["2023-11-07",4.35],
]

# Fallback tail used only if the RBA fetch fails entirely.
FALLBACK_TAIL = [
    ["2025-02-18",4.10],["2025-05-20",3.85],["2025-08-12",3.60],
    ["2026-02-04",3.85],["2026-03-18",4.10],["2026-05-06",4.35],
]

# Meeting schedule. Day-two dates, 14:30 local. Update each January when
# the RBA publishes the next year's calendar.
MEETINGS = {
    "2026-02-05T14:30:00+11:00": "Thu 5 Feb 2026",
    "2026-03-17T14:30:00+11:00": "Tue 17 Mar 2026",
    "2026-05-05T14:30:00+10:00": "Tue 5 May 2026",
    "2026-06-16T14:30:00+10:00": "Tue 16 Jun 2026",
    "2026-08-11T14:30:00+10:00": "Tue 11 Aug 2026",
    "2026-09-29T14:30:00+10:00": "Tue 29 Sep 2026",
    "2026-11-03T14:30:00+11:00": "Tue 3 Nov 2026",
    "2026-12-08T14:30:00+11:00": "Tue 8 Dec 2026",
}

# Sentiment baseline, Jan 2000 - Jun 2026. Historical reconstruction; static.
# Extended forward from data.json["sentiment_recent"].
SENT_BASELINE = [
    ["Jan 2000",3],["Feb 2000",4],["Mar 2000",5],["Apr 2000",5],["May 2000",5],["Jun 2000",5],
    ["Jul 2000",6],["Aug 2000",6],["Sep 2000",5],["Oct 2000",5],["Nov 2000",4],["Dec 2000",3],
    ["Jan 2001",2],["Feb 2001",-1],["Mar 2001",-2],["Apr 2001",-3],["May 2001",-4],["Jun 2001",-5],
    ["Jul 2001",-5],["Aug 2001",-5],["Sep 2001",-6],["Oct 2001",-6],["Nov 2001",-5],["Dec 2001",-4],
    ["Jan 2002",-2],["Feb 2002",-1],["Mar 2002",0],["Apr 2002",1],["May 2002",2],["Jun 2002",2],
    ["Jul 2002",3],["Aug 2002",3],["Sep 2002",3],["Oct 2002",3],["Nov 2002",3],["Dec 2002",2],
    ["Jan 2003",1],["Feb 2003",1],["Mar 2003",1],["Apr 2003",1],["May 2003",2],["Jun 2003",2],
    ["Jul 2003",3],["Aug 2003",3],["Sep 2003",3],["Oct 2003",4],["Nov 2003",4],["Dec 2003",4],
    ["Jan 2004",3],["Feb 2004",3],["Mar 2004",3],["Apr 2004",3],["May 2004",3],["Jun 2004",3],
    ["Jul 2004",3],["Aug 2004",3],["Sep 2004",3],["Oct 2004",3],["Nov 2004",3],["Dec 2004",3],
    ["Jan 2005",3],["Feb 2005",3],["Mar 2005",3],["Apr 2005",3],["May 2005",4],["Jun 2005",4],
    ["Jul 2005",4],["Aug 2005",4],["Sep 2005",4],["Oct 2005",4],["Nov 2005",4],["Dec 2005",4],
    ["Jan 2006",4],["Feb 2006",4],["Mar 2006",5],["Apr 2006",5],["May 2006",5],["Jun 2006",5],
    ["Jul 2006",5],["Aug 2006",5],["Sep 2006",5],["Oct 2006",5],["Nov 2006",5],["Dec 2006",5],
    ["Jan 2007",5],["Feb 2007",6],["Mar 2007",6],["Apr 2007",6],["May 2007",6],["Jun 2007",6],
    ["Jul 2007",7],["Aug 2007",6],["Sep 2007",5],["Oct 2007",5],["Nov 2007",5],["Dec 2007",4],
    ["Jan 2008",5],["Feb 2008",6],["Mar 2008",6],["Apr 2008",6],["May 2008",6],["Jun 2008",5],
    ["Jul 2008",3],["Aug 2008",1],["Sep 2008",-2],["Oct 2008",-5],["Nov 2008",-7],["Dec 2008",-8],
    ["Jan 2009",-8],["Feb 2009",-8],["Mar 2009",-8],["Apr 2009",-7],["May 2009",-6],["Jun 2009",-5],
    ["Jul 2009",-4],["Aug 2009",-3],["Sep 2009",-2],["Oct 2009",0],["Nov 2009",1],["Dec 2009",2],
    ["Jan 2010",2],["Feb 2010",2],["Mar 2010",3],["Apr 2010",3],["May 2010",4],["Jun 2010",4],
    ["Jul 2010",4],["Aug 2010",4],["Sep 2010",4],["Oct 2010",4],["Nov 2010",4],["Dec 2010",3],
    ["Jan 2011",3],["Feb 2011",3],["Mar 2011",3],["Apr 2011",3],["May 2011",3],["Jun 2011",2],
    ["Jul 2011",2],["Aug 2011",1],["Sep 2011",0],["Oct 2011",-1],["Nov 2011",-2],["Dec 2011",-3],
    ["Jan 2012",-3],["Feb 2012",-3],["Mar 2012",-3],["Apr 2012",-3],["May 2012",-4],["Jun 2012",-4],
    ["Jul 2012",-4],["Aug 2012",-4],["Sep 2012",-4],["Oct 2012",-5],["Nov 2012",-5],["Dec 2012",-4],
    ["Jan 2013",-4],["Feb 2013",-4],["Mar 2013",-4],["Apr 2013",-4],["May 2013",-4],["Jun 2013",-4],
    ["Jul 2013",-4],["Aug 2013",-5],["Sep 2013",-4],["Oct 2013",-3],["Nov 2013",-3],["Dec 2013",-2],
    ["Jan 2014",-2],["Feb 2014",-2],["Mar 2014",-2],["Apr 2014",-2],["May 2014",-2],["Jun 2014",-2],
    ["Jul 2014",-2],["Aug 2014",-2],["Sep 2014",-2],["Oct 2014",-2],["Nov 2014",-2],["Dec 2014",-2],
    ["Jan 2015",-3],["Feb 2015",-3],["Mar 2015",-3],["Apr 2015",-3],["May 2015",-4],["Jun 2015",-4],
    ["Jul 2015",-4],["Aug 2015",-4],["Sep 2015",-3],["Oct 2015",-3],["Nov 2015",-3],["Dec 2015",-3],
    ["Jan 2016",-3],["Feb 2016",-3],["Mar 2016",-3],["Apr 2016",-4],["May 2016",-4],["Jun 2016",-4],
    ["Jul 2016",-4],["Aug 2016",-5],["Sep 2016",-5],["Oct 2016",-4],["Nov 2016",-4],["Dec 2016",-3],
    ["Jan 2017",-2],["Feb 2017",-2],["Mar 2017",-2],["Apr 2017",-2],["May 2017",-2],["Jun 2017",-2],
    ["Jul 2017",-2],["Aug 2017",-2],["Sep 2017",-2],["Oct 2017",-2],["Nov 2017",-2],["Dec 2017",-1],
    ["Jan 2018",-1],["Feb 2018",-1],["Mar 2018",-1],["Apr 2018",-1],["May 2018",-1],["Jun 2018",-1],
    ["Jul 2018",-1],["Aug 2018",-1],["Sep 2018",-1],["Oct 2018",-1],["Nov 2018",0],["Dec 2018",0],
    ["Jan 2019",0],["Feb 2019",-1],["Mar 2019",-1],["Apr 2019",-2],["May 2019",-3],["Jun 2019",-4],
    ["Jul 2019",-5],["Aug 2019",-5],["Sep 2019",-5],["Oct 2019",-5],["Nov 2019",-5],["Dec 2019",-4],
    ["Jan 2020",-4],["Feb 2020",-4],["Mar 2020",-8],["Apr 2020",-9],["May 2020",-9],["Jun 2020",-9],
    ["Jul 2020",-9],["Aug 2020",-9],["Sep 2020",-9],["Oct 2020",-9],["Nov 2020",-9],["Dec 2020",-9],
    ["Jan 2021",-9],["Feb 2021",-9],["Mar 2021",-9],["Apr 2021",-9],["May 2021",-8],["Jun 2021",-8],
    ["Jul 2021",-8],["Aug 2021",-8],["Sep 2021",-7],["Oct 2021",-6],["Nov 2021",-6],["Dec 2021",-5],
    ["Jan 2022",-4],["Feb 2022",-4],["Mar 2022",-3],["Apr 2022",-1],["May 2022",4],["Jun 2022",7],
    ["Jul 2022",8],["Aug 2022",9],["Sep 2022",9],["Oct 2022",8],["Nov 2022",8],["Dec 2022",7],
    ["Jan 2023",7],["Feb 2023",7],["Mar 2023",6],["Apr 2023",6],["May 2023",7],["Jun 2023",6],
    ["Jul 2023",4],["Aug 2023",4],["Sep 2023",4],["Oct 2023",5],["Nov 2023",6],["Dec 2023",4],
    ["Jan 2024",3],["Feb 2024",3],["Mar 2024",1],["Apr 2024",1],["May 2024",2],["Jun 2024",2],
    ["Jul 2024",3],["Aug 2024",3],["Sep 2024",2],["Oct 2024",2],["Nov 2024",2],["Dec 2024",5],
    ["Jan 2025",5],["Feb 2025",-1],["Mar 2025",-2],["Apr 2025",-3],["May 2025",-3],["Jun 2025",-2],
    ["Jul 2025",-2],["Aug 2025",-1],["Sep 2025",-1],["Oct 2025",4],["Nov 2025",5],["Dec 2025",6],
    ["Jan 2026",7],["Feb 2026",8],["Mar 2026",7],["Apr 2026",7],["May 2026",7],["Jun 2026",6.4],
]

PIVOTS = [
    {"idx":7,"txt":"6.25% peak","above":True},
    {"idx":20,"txt":"6 cuts \u2192 4.25%","above":False},
    {"idx":98,"txt":"GFC peak 7.25%","above":True},
    {"idx":106,"txt":"GFC emergency cuts","above":False},
    {"idx":242,"txt":"COVID: 0.10%","above":False},
    {"idx":268,"txt":"First 2022 hike","above":True},
    {"idx":271,"txt":"Peak hawk +9","above":True},
    {"idx":290,"txt":"Dovish tilt","above":False},
    {"idx":301,"txt":"Easing cycle","above":False},
    {"idx":309,"txt":"Hawkish re-pivot","above":True},
    {"idx":313,"txt":"Unanimous hike","above":True},
]


def fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "rba-tracker/2.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def parse_rba_csv(text):
    """
    Extract (date, cash_rate_target) pairs from an RBA statistical CSV.

    RBA CSVs carry ~10 metadata rows before the data. We locate the row
    whose first cell is 'Series ID' to find the column holding FIRMMCRTD,
    then read every subsequent row as date,value. Written defensively:
    the RBA has changed this layout before.
    """
    rows = list(csv.reader(io.StringIO(text)))
    col = None
    data_start = None
    for i, row in enumerate(rows):
        if not row:
            continue
        if row[0].strip().lower().startswith("series id"):
            for j, cell in enumerate(row):
                if cell.strip().upper() == RBA_SERIES_ID:
                    col = j
                    break
            data_start = i + 1
            break
    if col is None or data_start is None:
        raise ValueError(f"could not locate series {RBA_SERIES_ID} in CSV")

    out = []
    for row in rows[data_start:]:
        if len(row) <= col or not row[0].strip():
            continue
        raw_date, raw_val = row[0].strip(), row[col].strip()
        if not raw_val:
            continue
        d = None
        for fmt in ("%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d %b %Y"):
            try:
                d = dt.datetime.strptime(raw_date, fmt).date()
                break
            except ValueError:
                continue
        if d is None:
            continue
        try:
            v = float(raw_val)
        except ValueError:
            continue
        if not (0.0 <= v <= 20.0):      # sanity band for an Australian cash rate
            continue
        out.append((d, v))
    if not out:
        raise ValueError("no usable rows parsed from CSV")
    return sorted(out)


def to_step_changes(series):
    """Collapse a daily series into one entry per rate CHANGE."""
    changes, last = [], None
    for d, v in series:
        if last is None or abs(v - last) > 1e-9:
            changes.append([d.isoformat(), round(v, 2)])
            last = v
    return changes


def fetch_rate_path():
    """
    Returns (path, current_rate, effective_date, source_label).
    Merges the static pre-2024 baseline with whatever the RBA gives us
    from 2024 onward, so a fetch failure only costs the recent tail.
    """
    try:
        series = parse_rba_csv(fetch(RBA_F11))
        changes = to_step_changes(series)
        tail = [c for c in changes if c[0] >= "2024-01-01"]
        if not tail:
            raise ValueError("no post-2024 observations returned")
        path = BASELINE_PATH + tail
        print(f"  source: RBA F1.1 ({len(series)} obs, {len(tail)} changes since 2024)")
        return path, tail[-1][1], tail[-1][0], "RBA F1.1 (live)"
    except Exception as e:
        print(f"  [warn] RBA F1.1 fetch failed: {e}")
        print("  [warn] falling back to bundled rate path")
        path = BASELINE_PATH + FALLBACK_TAIL
        return path, FALLBACK_TAIL[-1][1], FALLBACK_TAIL[-1][0], "bundled fallback"


def fetch_audusd():
    """AUD/USD from keyless public APIs. Returns (value_str, source_label)."""
    for name, url, pick in [
        ("frankfurter.app", "https://api.frankfurter.app/latest?from=AUD&to=USD",
         lambda d: d["rates"]["USD"]),
        ("open.er-api.com", "https://open.er-api.com/v6/latest/AUD",
         lambda d: d["rates"]["USD"]),
    ]:
        try:
            v = float(pick(json.loads(fetch(url, timeout=10))))
            if not (0.3 < v < 1.5):
                raise ValueError(f"implausible rate {v}")
            print(f"  source: {name}")
            return f"{v:.4f}", name
        except Exception as e:
            print(f"  [warn] {name} failed: {e}")
    return "n/a", "unavailable"


def next_meeting():
    now = dt.datetime.now(dt.timezone.utc)
    for iso, label in sorted(MEETINGS.items()):
        if dt.datetime.fromisoformat(iso) > now:
            return iso, label
    last = sorted(MEETINGS)[-1]
    return last, MEETINGS[last]


def fmt_date(iso):
    return dt.date.fromisoformat(iso).strftime("%-d %b %Y")


def rate_on(path, year, month):
    """Cash rate in effect at the end of a given month, from the step path."""
    cutoff = f"{year:04d}-{month:02d}-28"
    val = path[0][1]
    for iso, v in path:
        if iso <= cutoff:
            val = v
        else:
            break
    return val


def build_sentiment(data, path):
    """
    Baseline sentiment + months from data.json, with the cash rate for each
    month derived from the live rate path. Rows are [label, score, rate] -
    the chart reads the third element for its cash-rate overlay, so this
    must stay a triple.
    """
    seen = {k for k, _ in SENT_BASELINE}
    rows = list(SENT_BASELINE)
    for label, score in data.get("sentiment_recent", []):
        if label not in seen:
            rows.append([label, score])
            seen.add(label)

    months = {m: i + 1 for i, m in enumerate(
        ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"])}
    out = []
    for label, score in rows:
        mon, yr = label.split()
        out.append([label, score, rate_on(path, int(yr), months[mon])])
    return out


def indicator_cards(data, audusd, fx_source):
    html = []
    for ind in data["indicators"]:
        val = ind["value"].replace("{{AUDUSD_LIVE}}", audusd)
        ctx = ind["context"].replace("{{FX_SOURCE}}", fx_source)
        inner = f'<span class="warn">{val}</span>' if ind.get("warn") else val
        html.append(
            '      <div class="ind">\n'
            f'        <div class="lab">{ind["label"]}</div>\n'
            f'        <div class="val">{inner}</div>\n'
            f'        <div class="ctx">{ctx}</div>\n'
            '      </div>'
        )
    return "\n".join(html)


def pricing_rows(data):
    html = []
    for r in data["pricing_rows"]:
        cls = "chg up" if r["dir"] == "up" else "chg flat"
        bar = "px-bar" if r["dir"] == "up" else "px-bar zero"
        tr = ' class="next-mtg"' if r.get("next") else ""
        name = f'<b>{r["meeting"]}</b>' if r.get("next") else r["meeting"]
        html.append(
            f'          <tr{tr}>\n'
            f'            <td class="mono">{name}</td>\n'
            f'            <td class="mono">{r["implied"]}</td>\n'
            f'            <td><span class="{cls}">{r["cum"]}</span></td>\n'
            f'            <td><span class="{bar}" style="width:{r["bar"]}px"></span>{r["note"]}</td>\n'
            f'          </tr>'
        )
    return "\n".join(html)


def sentiment_score(members):
    tw = sum(m["weight"] for m in members)
    if tw == 0:
        return 0.0
    return sum(m["score"] * m["weight"] for m in members) / tw


def score_label(s):
    if s >= 6:  return "Hawkish"
    if s >= 2:  return "Lean Hawkish"
    if s <= -6: return "Dovish"
    if s <= -2: return "Lean Dovish"
    return "Neutral"


def main():
    print("RBA Policy Tracker - rebuild")
    print("=" * 46)

    try:
        data = json.load(open(DATA))
    except Exception as e:
        sys.exit(f"ERROR: cannot read {DATA}: {e}")

    print("-> Cash rate path")
    path, rate, eff_date, rate_source = fetch_rate_path()

    print("-> AUD/USD")
    audusd, fx_source = fetch_audusd()

    print("-> Next meeting")
    next_iso, next_label = next_meeting()
    print(f"  {next_label}")

    # staleness of the editorial layer
    as_of = dt.date.fromisoformat(data["editorial_as_of"])
    age_days = (dt.datetime.now(AEST).date() - as_of).days
    stamp = f'editorial content as of {as_of.strftime("%-d %b %Y")}'
    if age_days > 75:
        stamp += f' &middot; <b style="color:#A8431F">{age_days} days old &mdash; review after recent meetings</b>'
    elif age_days > 40:
        stamp += f' &middot; {age_days} days old'
    print(f"-> Editorial age: {age_days} days")

    ld = data["last_decision"]
    arrow = {"hike": "&#9650;", "cut": "&#9660;", "hold": "&#9644;"}.get(ld["action"], "")
    change = f'{ld["change_bp"]:+d} bp' if ld["change_bp"] else "no change"
    pill = f'{arrow} {change} &middot; {ld["date"]} &middot; {ld["vote"]}'

    members = data["members"]
    score = sentiment_score(members)
    sb = data["setup_blurb"]
    setup = (
        f'<div class="next-fact" style="margin-bottom:6px"><b>{sb["headline"]}</b> {sb["text"]}</div>\n'
        f'          <div class="next-fact">{sb["secondary"]}</div>'
    )

    subs = {
        "{{CURRENT_RATE}}":       f"{rate:.2f}".rstrip("0").rstrip("."),
        "{{RATE_META}}":          f'Effective {fmt_date(eff_date)} &middot; {ld["note"]}',
        "{{RATE_PILL}}":          pill,
        "{{RATE_PATH_JSON}}":     json.dumps(path, separators=(",", ":")),
        "{{NEXT_MEETING_LABEL}}": next_label,
        "{{NEXT_MEETING_ISO}}":   next_iso,
        "{{SETUP_BLURB}}":        setup,
        "{{INDICATOR_CARDS}}":    indicator_cards(data, audusd, fx_source),
        "{{PRICING_ROWS}}":       pricing_rows(data),
        "{{MEETINGS_JSON}}":      json.dumps(data["meetings"]),
        "{{BANKS_JSON}}":         json.dumps(data["banks"]),
        "{{MEMBERS_JSON}}":       json.dumps(members),
        "{{SENTIMENT_JSON}}":     json.dumps(build_sentiment(data, path), separators=(",", ":")),
        "{{PIVOTS_JSON}}":        json.dumps(PIVOTS),
        "{{SENT_SCORE}}":         f"{score:+.1f}",
        "{{SENT_LABEL}}":         score_label(score),
        "{{EDITORIAL_STAMP}}":    stamp,
        "{{LAST_UPDATED}}":       dt.datetime.now(AEST).strftime("%-d %b %Y, %H:%M"),
        "{{FOOTER_SOURCES}}":     data["footer_sources"],
    }

    try:
        html = open(TEMPLATE).read()
    except FileNotFoundError:
        sys.exit(f"ERROR: {TEMPLATE} not found")

    for token, value in subs.items():
        if token not in html:
            print(f"  [warn] token absent from template: {token}")
        html = html.replace(token, value)

    leftover = [t for t in subs if t in html]
    if leftover:
        sys.exit(f"ERROR: tokens survived substitution: {leftover}")

    open(OUTPUT, "w").write(html)

    print("-" * 46)
    print(f"Written {OUTPUT}")
    print(f"  cash rate : {rate}%  (eff {eff_date}, {rate_source})")
    print(f"  AUD/USD   : {audusd}  ({fx_source})")
    print(f"  next mtg  : {next_label}")
    print(f"  sentiment : {score:+.1f} {score_label(score)}")
    print(f"  editorial : {age_days} days old")


if __name__ == "__main__":
    main()
