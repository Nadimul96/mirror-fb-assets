"""
Mirror — Instagram cross-poster (Instagram Graph API).

Publishes the same cards/captions from schedule.csv to the Instagram account linked
to the Mirror FB page. Images are served from the public GitHub repo (IG requires a
public image_url — it won't take a local upload).

IMPORTANT DIFFERENCES vs Facebook:
  - IG has NO server-side scheduling. media_publish posts IMMEDIATELY.
    So to spread posts across the day you run --post-due on a cron (or in batches)
    while the token is alive. (FB schedules server-side; IG cannot.)
  - Token must include: instagram_basic, instagram_content_publish,
    pages_show_list, pages_read_engagement.
  - IG limit: ~25 published posts / 24h.

SAFE BY DEFAULT: dry-run unless --post-due is passed.

USAGE:
  python3 post_to_ig.py                 # dry-run: show what's due, post nothing
  python3 post_to_ig.py --post-due      # publish anything due now (run from cron)
  python3 post_to_ig.py --post-due --limit 1   # publish ONE (test)
  python3 post_to_ig.py --start 2026-06-21      # anchor Day 1
"""
import csv, json, os, sys, time, argparse, datetime as dt

PAGE_ID = "951362634735195"          # Mirror by ClearPath FB page
IMG_BASE = "https://raw.githubusercontent.com/Nadimul96/mirror-fb-assets/main/"
GRAPH = "https://graph.facebook.com/v21.0"
HERE = os.path.dirname(os.path.abspath(__file__))
SCHEDULE = os.path.join(HERE, "schedule.csv")
POSTED = os.path.join(HERE, "posted-ig.json")
TIME_MAP = {"8:00 AM": 8, "9:00 AM": 9, "11:00 AM": 11, "12:00 PM": 12, "2:00 PM": 14, "5:00 PM": 17, "8:00 PM": 20}


def load_token():
    return (os.environ.get("FB_PAGE_TOKEN")
            or (open(os.path.join(HERE, ".fb-page-token")).read().strip()
                if os.path.exists(os.path.join(HERE, ".fb-page-token")) else None))


def load_posted():
    return json.load(open(POSTED)) if os.path.exists(POSTED) else {}


def save_posted(d):
    json.dump(d, open(POSTED, "w"), indent=2)


def ig_account(token):
    """Resolve the IG business account linked to the Mirror page (SAFETY: print it)."""
    import requests
    r = requests.get(f"{GRAPH}/{PAGE_ID}",
                     params={"fields": "instagram_business_account{id,username}", "access_token": token}, timeout=30)
    j = r.json()
    if r.status_code != 200:
        sys.exit(f"Token/page check failed: {j.get('error', j)}")
    iba = j.get("instagram_business_account")
    if not iba:
        sys.exit("No Instagram BUSINESS account is linked to the Mirror page.\n"
                 "Fix: in Meta settings, link the IG account to the page AND make it a Business/Creator account.")
    print(f"  ✓ IG target: @{iba.get('username')} (id {iba['id']}) — linked to Mirror page.")
    return iba["id"]


def publish(token, igid, image_url, caption):
    import requests
    c = requests.post(f"{GRAPH}/{igid}/media",
                      data={"image_url": image_url, "caption": caption, "access_token": token}, timeout=90)
    j = c.json()
    if c.status_code != 200:
        raise RuntimeError(j.get("error", j))
    cid = j["id"]
    time.sleep(4)  # let the container finish processing
    p = requests.post(f"{GRAPH}/{igid}/media_publish",
                      data={"creation_id": cid, "access_token": token}, timeout=90)
    j = p.json()
    if p.status_code != 200:
        raise RuntimeError(j.get("error", j))
    return j.get("id")


def slot_dt(day, time_label, start):
    return (start + dt.timedelta(days=int(day) - 1)).replace(hour=TIME_MAP.get(time_label, 9), minute=0, second=0, microsecond=0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--post-due", action="store_true")
    ap.add_argument("--start", default=None, help="YYYY-MM-DD anchor for Day 1 (default tomorrow)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--allow-before-after", action="store_true",
                    help="opt-in to post Visual/ba-* AI before/after cards (DEFAULT OFF — #1 IG-ban pattern)")
    a = ap.parse_args()

    start = dt.datetime.combine(dt.date.fromisoformat(a.start) if a.start else dt.date.today() + dt.timedelta(days=1), dt.time())
    token = load_token()
    if a.post_due and not token:
        sys.exit("No token. Save a Page token (with IG perms) to mirror-fb/.fb-page-token.")
    igid = ig_account(token) if a.post_due else None
    posted = load_posted()
    now = dt.datetime.now()

    done = todo = 0
    with open(SCHEDULE) as f:
        for r in csv.DictReader(f):
            if r["Asset"].startswith("GENERATE"):
                continue
            if (r.get("Pillar") == "Visual" or r["Asset"].startswith("ba-")) and not a.allow_before_after:
                continue  # SAFETY: no AI before/after cards on the just-unbanned IG (ban pattern)
            key = f"{r['Day']}-{r['Time']}-{r['Asset']}"
            if key in posted:
                continue
            when = slot_dt(r["Day"], r["Time"], start)
            caption = r["Caption"] + ("\n\n" + r["Hashtags"] if r.get("Hashtags") else "")
            url = IMG_BASE + r["Asset"]
            if not a.post_due:
                print(f"  → {when:%a %m/%d %H:%M}  {r['Asset']:<28} [{r['Pillar']}]")
                todo += 1; continue
            if when > now:
                continue
            try:
                mid = publish(token, igid, url, caption)
                posted[key] = {"id": mid, "asset": r["Asset"], "when": when.isoformat()}
                save_posted(posted)
                print(f"  ✓ posted to IG  {r['Asset']}  -> {mid}")
                done += 1
                if a.limit and done >= a.limit:
                    print(f"  (stopped at --limit {a.limit})"); break
                time.sleep(2)
            except Exception as e:
                print(f"  ✗ FAILED  {r['Asset']}: {e}")

    print(f"\n{'Published ' + str(done) if a.post_due else 'DRY RUN: ' + str(todo) + ' due'} to Instagram.")


if __name__ == "__main__":
    main()
