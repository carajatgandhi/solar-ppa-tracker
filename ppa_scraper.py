"""
India Solar PPA Tracker - Auto Scraper
=======================================
Scrapes solar PPA news from Google News, Mercom India, and PV Tech
and adds new entries to your Supabase database.

Run manually:  python ppa_scraper.py
Auto-schedule: See README instructions below

SOURCES:
- Google News RSS (solar PPA India)
- Mercom India RSS feed
- PV Tech RSS feed
- NTPC tender page headlines
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime, date
import re
import time
import json

# ─────────────────────────────────────────────
# YOUR SUPABASE CREDENTIALS
# ─────────────────────────────────────────────
SUPABASE_URL = "https://aycudevttcsyrckgfnaj.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImF5Y3VkZXZ0dGNzeXJja2dmbmFqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzYyMjcyMTUsImV4cCI6MjA5MTgwMzIxNX0.TaW5xYIGwpBywrFJRNtf7m9PR3cTEYnXViDxEncEpyw"
TABLE = "ppa_entries"

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

# ─────────────────────────────────────────────
# KEYWORDS TO DETECT PPA-RELATED ARTICLES
# ─────────────────────────────────────────────
PPA_KEYWORDS = [
    "ppa", "power purchase agreement",
    "solar tender", "wind tender",
    "mw solar", "gw solar",
    "allot", "awarded", "wins bid",
    "seci", "ntpc renewable", "reci",
    "guvnl", "msedcl", "tangedco", "bescom",
    "tariff", "l1 bidder", "lowest bid"
]

COMPANY_PATTERNS = [
    # Large IPPs
    ("adani green", "Adani Green Energy"),
    ("adani renewable", "Adani Renewable"),
    ("renew power", "ReNew Power"),
    ("renew energy", "ReNew Power"),
    ("greenko", "Greenko"),
    ("acme solar", "Acme Solar"),
    ("acme renewables", "Acme Solar"),
    ("tata power solar", "Tata Power Solar"),
    ("tata power", "Tata Power"),
    ("ntpc renewable", "NTPC Renewable"),
    ("ntpc", "NTPC"),
    ("torrent power", "Torrent Power"),
    ("amp energy", "Amp Energy"),
    ("waaree", "Waaree Energies"),
    ("o2 power", "O2 Power"),
    ("azure power", "Azure Power"),
    ("hero future", "Hero Future Energies"),
    ("avaada", "Avaada Energy"),
    ("sprng energy", "Sprng Energy"),
    ("eden renewable", "Eden Renewables"),
    ("ayana renewable", "Ayana Renewable"),
    ("cleanmax", "CleanMax"),
    ("ib vogt", "IB Vogt"),
    ("ostro energy", "Ostro Energy"),
    ("serentica", "Serentica Renewables"),
    ("engie", "Engie"),
    ("sembcorp", "Sembcorp"),
    ("sterlite power", "Sterlite Power"),
    ("gail", "GAIL"),
    ("welspun renewable", "Welspun Renewable"),
    ("welspun", "Welspun"),
    ("nlc india", "NLC India"),
    ("nlc", "NLC India"),
    ("sunsure energy", "Sunsure Energy"),
    ("sunsure", "Sunsure Energy"),
    ("jayram industries", "Jayram Industries"),
    ("power grid", "Power Grid Corporation"),
    ("sjvn", "SJVN"),
    ("nhpc", "NHPC"),
    ("seci", "SECI"),
    ("ireda", "IREDA"),
    ("reci", "RECI"),
    ("torrent", "Torrent Power"),
    ("bosch", "Bosch"),
    ("mahindra susten", "Mahindra Susten"),
    ("mahindra", "Mahindra"),
    ("bajaj", "Bajaj Electricals"),
    ("cesc", "CESC"),
    ("jsw energy", "JSW Energy"),
    ("jsw", "JSW Energy"),
    ("vedanta", "Vedanta"),
    ("sterling", "Sterling and Wilson"),
    ("enerparc", "Enerparc"),
    ("amp solar", "Amp Solar"),
    ("amplus", "AmPlus Energy"),
]

# ─────────────────────────────────────────────
# RSS FEED SOURCES (free, no API key needed)
# ─────────────────────────────────────────────
RSS_FEEDS = [
    {
        "name": "Google News - Solar PPA India",
        "url": "https://news.google.com/rss/search?q=solar+PPA+India+renewable+energy&hl=en-IN&gl=IN&ceid=IN:en",
        "source": "News"
    },
    {
        "name": "Google News - SECI Tender",
        "url": "https://news.google.com/rss/search?q=SECI+solar+tender+awarded+India&hl=en-IN&gl=IN&ceid=IN:en",
        "source": "SECI"
    },
    {
        "name": "Google News - NTPC Renewable",
        "url": "https://news.google.com/rss/search?q=NTPC+renewable+solar+tender+allot&hl=en-IN&gl=IN&ceid=IN:en",
        "source": "NTPC"
    },
    {
        "name": "Google News - Solar Tariff India",
        "url": "https://news.google.com/rss/search?q=solar+tariff+bid+awarded+India+MW&hl=en-IN&gl=IN&ceid=IN:en",
        "source": "News"
    },
    {
        "name": "Mercom India",
        "url": "https://mercomindia.com/feed/",
        "source": "Mercom"
    },
    {
        "name": "PV Tech",
        "url": "https://www.pv-tech.org/feed/",
        "source": "News"
    },
]

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def is_ppa_relevant(text):
    """Check if article is relevant to solar PPAs in India."""
    text_lower = text.lower()
    india_terms = ["india", "indian", "rajasthan", "gujarat", "maharashtra",
                   "karnataka", "andhra", "telangana", "tamil", "madhya pradesh",
                   "seci", "ntpc", "mnre", "guvnl", "msedcl"]
    has_india = any(t in text_lower for t in india_terms)
    has_ppa = any(k in text_lower for k in PPA_KEYWORDS)
    return has_india and has_ppa

def extract_company(text):
    """Try to extract company name from article title."""
    text_lower = text.lower()
    # Check against known patterns (ordered longest first to avoid partial matches)
    for keyword, proper_name in sorted(COMPANY_PATTERNS, key=lambda x: len(x[0]), reverse=True):
        if keyword in text_lower:
            return proper_name

    # Fallback: try to extract "X wins", "X awarded", "X bags", "X secures" pattern
    win_patterns = [
        r'^([A-Z][A-Za-z\s&]+?)\s+(?:wins|awarded|bags|secures|signs|gets|clinches)',
        r'^([A-Z][A-Za-z\s&]+?)\s+(?:to develop|to build|to set up)',
    ]
    for pattern in win_patterns:
        match = re.search(pattern, text)
        if match:
            name = match.group(1).strip()
            if 3 < len(name) < 40:  # Sanity check on length
                return name

    return None

def extract_mw(text):
    """Try to extract MW/GW capacity from text."""
    # Match patterns like "500 MW", "1.2 GW", "2GW"
    mw_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:mw|megawatt)', text.lower())
    gw_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:gw|gigawatt)', text.lower())
    if gw_match:
        return float(gw_match.group(1)) * 1000
    if mw_match:
        return float(mw_match.group(1))
    return None

def extract_tariff(text):
    """Try to extract tariff from text."""
    # Match patterns like "₹2.15/kWh", "Rs 2.15", "2.15 per unit"
    tariff_match = re.search(r'(?:rs\.?|₹|inr)\s*(\d+\.\d+)', text.lower())
    if tariff_match:
        val = float(tariff_match.group(1))
        if 1.0 <= val <= 6.0:  # Sanity check - solar tariffs in India range
            return val
    return None

def detect_entry_type(text):
    """Auto-detect entry type from article headline."""
    text_lower = text.lower()
    allotted_keywords = ["allot", "awarded", "wins bid", "bags", "secures bid",
                         "wins tender", "selected as", "l1 bidder", "lowest bidder",
                         "win contract", "clinches", "gets order"]
    issued_keywords = ["issues tender", "floats tender", "invites bid", "rfp issued",
                       "issues rfq", "calls for bid", "new tender", "tender out",
                       "seeks developer", "invited tender"]
    signed_keywords = ["ppa signed", "signs ppa", "signs power purchase", "agreement signed",
                       "inks ppa", "power deal signed"]
    policy_keywords = ["regulation", "policy", "amendment", "directive", "cerc", "uperc",
                       "merc", "tnerc", "kerc", "approve tariff", "tariff order"]
    if any(k in text_lower for k in allotted_keywords):
        return "Tender Allotted"
    if any(k in text_lower for k in signed_keywords):
        return "PPA Signed"
    if any(k in text_lower for k in issued_keywords):
        return "Tender Issued"
    if any(k in text_lower for k in policy_keywords):
        return "Policy / Regulation"
    return "General News"


    """Try to extract Indian state from text."""
    states = {
        "rajasthan": "Rajasthan", "gujarat": "Gujarat",
        "maharashtra": "Maharashtra", "karnataka": "Karnataka",
        "andhra pradesh": "Andhra Pradesh", "telangana": "Telangana",
        "tamil nadu": "Tamil Nadu", "madhya pradesh": "Madhya Pradesh",
        "uttar pradesh": "Uttar Pradesh", "punjab": "Punjab",
        "haryana": "Haryana", "odisha": "Odisha",
        "jharkhand": "Jharkhand", "chhattisgarh": "Chhattisgarh",
    }
    text_lower = text.lower()
    for key, val in states.items():
        if key in text_lower:
            return val
    return None

def get_existing_links():
    """Get all existing source links from database to avoid duplicates."""
    try:
        resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/{TABLE}?select=link",
            headers=HEADERS
        )
        if resp.status_code == 200:
            data = resp.json()
            return set(d.get("link", "") for d in data if d.get("link"))
    except Exception as e:
        print(f"  Warning: Could not fetch existing links: {e}")
    return set()

def get_existing_notes():
    """Get all notes (used to store article titles) to avoid duplicates."""
    try:
        resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/{TABLE}?select=notes",
            headers=HEADERS
        )
        if resp.status_code == 200:
            data = resp.json()
            return set(d.get("notes", "")[:80] for d in data if d.get("notes"))
    except Exception as e:
        print(f"  Warning: Could not fetch existing notes: {e}")
    return set()

def insert_entry(entry):
    """Insert a single entry into Supabase."""
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/{TABLE}",
        headers={**HEADERS, "Prefer": "return=minimal"},
        data=json.dumps(entry)
    )
    return resp.status_code in (200, 201)

def parse_rss(feed_url, source_name):
    """Parse an RSS feed and return list of (title, link, date) tuples."""
    items = []
    try:
        resp = requests.get(feed_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(resp.content, "xml")
        for item in soup.find_all("item")[:20]:  # Max 20 per feed
            title = item.find("title")
            link  = item.find("link")
            pub   = item.find("pubDate")
            if title and link:
                pub_date = ""
                if pub:
                    try:
                        from email.utils import parsedate_to_datetime
                        pub_date = parsedate_to_datetime(pub.text).strftime("%Y-%m-%d")
                    except:
                        pub_date = date.today().strftime("%Y-%m-%d")
                items.append({
                    "title": title.text.strip(),
                    "link": link.text.strip() if link.text else (link.next_sibling or "").strip(),
                    "date": pub_date or date.today().strftime("%Y-%m-%d"),
                    "source": source_name
                })
    except Exception as e:
        print(f"  Error fetching {source_name}: {e}")
    return items

# ─────────────────────────────────────────────
# MAIN SCRAPER
# ─────────────────────────────────────────────

def run_scraper():
    print("\n" + "="*60)
    print("  INDIA SOLAR PPA TRACKER — AUTO SCRAPER")
    print(f"  Running at: {datetime.now().strftime('%d %b %Y, %I:%M %p')}")
    print("="*60)

    print("\n[1/3] Connecting to database...")
    existing_links = get_existing_links()
    existing_notes = get_existing_notes()
    print(f"  Found {len(existing_links)} existing entries in database")

    print("\n[2/3] Scanning news sources...")
    all_articles = []
    for feed in RSS_FEEDS:
        print(f"  Checking: {feed['name']}...")
        articles = parse_rss(feed["url"], feed["source"])
        print(f"    → Found {len(articles)} articles")
        all_articles.extend(articles)
        time.sleep(1)  # Be polite to servers

    print(f"\n  Total articles scanned: {len(all_articles)}")

    print("\n[3/3] Filtering & adding relevant PPA entries...")
    added = 0
    skipped_duplicate = 0
    skipped_irrelevant = 0

    for article in all_articles:
        title = article["title"]
        link  = article["link"]

        # Skip duplicates
        if link in existing_links or title[:80] in existing_notes:
            skipped_duplicate += 1
            continue

        # Skip irrelevant articles
        if not is_ppa_relevant(title):
            skipped_irrelevant += 1
            continue

        # Extract what we can automatically
        company    = extract_company(title) or f"📰 {title[:40]}..."
        capacity   = extract_mw(title)
        tariff     = extract_tariff(title)
        state      = extract_state(title)
        entry_type = detect_entry_type(title)

        entry = {
            "company":    company,
            "state":      state or "—",
            "capacity":   capacity or 0,
            "tariff":     tariff,
            "offtaker":   "",
            "tender":     "",
            "date":       article["date"],
            "status":     "Allotted" if entry_type in ("Tender Allotted", "Bid Won") else "PPA signed" if entry_type == "PPA Signed" else "",
            "source":     article["source"],
            "link":       link,
            "notes":      f"[AUTO] {title[:200]}",
            "entry_type": entry_type,
        }

        if insert_entry(entry):
            added += 1
            existing_links.add(link)
            existing_notes.add(title[:80])
            print(f"  ✓ Added: {title[:70]}...")
        else:
            print(f"  ✗ Failed to add: {title[:70]}...")

        time.sleep(0.3)  # Rate limit

    print("\n" + "="*60)
    print(f"  DONE! Summary:")
    print(f"  ✓ New entries added:     {added}")
    print(f"  → Duplicates skipped:    {skipped_duplicate}")
    print(f"  → Irrelevant skipped:    {skipped_irrelevant}")
    print("="*60)
    print(f"\n  Open your dashboard to review new entries:")
    print(f"  https://solar-ppa-tracker.vercel.app")
    print(f"\n  TIP: Entries marked '⚠️ Review needed' need")
    print(f"  manual update of company name, state, and MW.")
    print("="*60 + "\n")

if __name__ == "__main__":
    run_scraper()
