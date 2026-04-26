# Reddit Monitor

Scrape any subreddit for keywords you care about, analyze the discussion with Claude AI, and send a daily HTML email digest to yourself and your team.

**No Reddit account needed. No Reddit API key needed. Claude is optional.**

---

## What you get

A daily email with:
- **AI Summary** — 3–4 sentence overview of what Reddit is saying
- **Sentiment bar** — positive / negative / neutral score (-1 to +1)
- **Key Themes** — recurring topics with frequency (high / medium / low)
- **Top Concerns** — what people are actually worried about
- **Recommended Actions** — Claude's suggested next steps
- **All Posts** — clickable table of every post found, sorted by score

Works for any topic — brand monitoring, competitor tracking, category pulse, policy research, anything.

---

## Quickstart

```bash
git clone https://github.com/Arijeet1301/reddit-monitor.git
cd reddit-monitor
pip install -r requirements.txt
cp .env.example .env
```

Open `reddit_monitor.py` and fill in the config block at the top:

```python
TOPIC       = "your topic"               # e.g. "Zomato complaints"
KEYWORDS    = ["keyword 1", "keyword 2"] # what to search for (OR logic)
SUBREDDITS  = ["india", "bangalore"]     # which subreddits to search
```

Then run:

```bash
python reddit_monitor.py          # preview email in browser (nothing sent)
python reddit_monitor.py --send   # send to your recipients
```

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

Two packages: `anthropic` (for Claude AI) and `python-dotenv`.

### 2. Configure your topic

Edit the config block at the top of `reddit_monitor.py`:

```python
TOPIC       = "YOUR TOPIC HERE"
KEYWORDS    = ["keyword 1", "keyword 2"]
SUBREDDITS  = ["subreddit1", "subreddit2"]
LIMIT       = 25          # max posts per subreddit
TIME_FILTER = "week"      # day | week | month | year | all
```

**Examples:**

```python
# Brand monitoring
TOPIC      = "Swiggy mentions"
KEYWORDS   = ["Swiggy", "swiggy app", "swiggy delivery"]
SUBREDDITS = ["india", "bangalore", "mumbai", "delhi"]

# Competitor tracking
TOPIC      = "Zomato pulse"
KEYWORDS   = ["Zomato", "food delivery app"]
SUBREDDITS = ["india", "bangalore"]

# Quick commerce
TOPIC      = "quick commerce"
KEYWORDS   = ["Blinkit", "Zepto", "quick commerce", "10 minute delivery"]
SUBREDDITS = ["india", "bangalore", "mumbai"]

# UPI / fintech
TOPIC      = "UPI issues"
KEYWORDS   = ["UPI failed", "UPI down", "payment failed"]
SUBREDDITS = ["india", "IndiaInvestments", "personalfinanceindia"]

# Anything else
TOPIC      = "AI regulation"
KEYWORDS   = ["AI ban", "AI regulation", "deepfake law"]
SUBREDDITS = ["india", "worldnews", "technology"]
```

### 3. Set up your secrets

```bash
cp .env.example .env
```

Fill in `.env`:

```env
ANTHROPIC_API_KEY=sk-ant-...        # optional — tool works without it
GMAIL_USER=you@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx   # see below
EMAIL_RECIPIENTS=you@email.com,colleague@email.com
```

**Getting a Gmail App Password** (your normal password won't work):
1. Google Account → Security → 2-Step Verification (must be ON)
2. Search "App Passwords" → create one for "Mail"
3. Paste the 16-character code into `GMAIL_APP_PASSWORD`

> Tip: use a dedicated Gmail address for sending rather than your personal inbox.

---

## Running it

```bash
# Preview the email in your browser — nothing is sent
python reddit_monitor.py

# Actually send to everyone in EMAIL_RECIPIENTS
python reddit_monitor.py --send

# Skip Claude AI (faster, no API key needed)
python reddit_monitor.py --no-ai

# Override config from command line
python reddit_monitor.py --topic "UPI issues" --keywords "UPI" "NPCI" --subreddits india --time month
```

---

## Daily automation

### Option A — GitHub Actions (recommended, always-on)

No server needed. Runs every day at 8 AM IST even when your laptop is off. History and seen-IDs persist automatically across runs via the Actions cache.

**Setup (one time):**

1. Push this repo to GitHub (already done if you cloned it)
2. Go to **Settings → Secrets and variables → Actions → New repository secret** and add:

| Secret name | Value |
|---|---|
| `ANTHROPIC_API_KEY` | your Claude API key |
| `GMAIL_USER` | your Gmail address |
| `GMAIL_APP_PASSWORD` | your 16-character app password |
| `EMAIL_RECIPIENTS` | comma-separated recipient list |

3. Go to **Actions → Daily Reddit Digest → Run workflow** to trigger the first run manually and verify it works.

After that it runs automatically at 08:00 IST every day. Logs are visible under the Actions tab.

**To change the topic/keywords without touching the code**, edit the config block at the top of `reddit_monitor.py`, commit, and push — the next scheduled run picks it up.

---

### Option B — Mac cron (laptop must be on)

Run automatically every morning at 8 AM:

```bash
crontab -e
```

Add:
```
0 8 * * * cd /path/to/reddit-monitor && /usr/bin/python3 reddit_monitor.py --send >> output/cron.log 2>&1
```

Find your Python path: `which python3`

> **Mac users:** grant Terminal full disk access for cron to work — System Settings → Privacy & Security → Full Disk Access.

---

## How it works

### Reddit scraping

Uses Reddit's public JSON API — every Reddit URL has a `.json` equivalent that returns structured data. No account, no OAuth, no API key.

```
reddit.com/r/india/search.json?q="keyword"&t=week&limit=25
```

- Fetches top 3 comments per post
- Deduplicates across subreddits
- Waits 1.5s between requests to stay within rate limits
- Auto-retries on 429, skips a subreddit after 2 failures

### Claude AI analysis

If `ANTHROPIC_API_KEY` is set, all posts (up to 40) are sent to **Claude Opus 4.6** in a single prompt. Claude returns:

```json
{
  "summary": "3-4 sentence overview",
  "overall_sentiment": "negative",
  "sentiment_score": -0.72,
  "key_themes": [{"theme": "...", "description": "...", "frequency": "high"}],
  "top_concerns": ["...", "..."],
  "notable_quotes": ["...", "..."],
  "recommended_actions": ["...", "..."]
}
```

The prompt uses your `TOPIC` as context — no domain-specific instructions. Claude figures out what's relevant on its own.

If no key is set, the tool still runs and produces a raw post digest without the AI layer.

### Email

Built with inline HTML styles (renders correctly in Gmail, Outlook, Apple Mail). Sent via Gmail SMTP.

---

## Output files

Each run saves to `output/` (gitignored):

| File | Contents |
|------|----------|
| `email_preview.html` | Full email HTML — open in browser to review |
| `email_subject.txt` | Subject line |
| `reddit_data_<timestamp>.json` | Raw posts + full analysis JSON |

---

## Troubleshooting

**No posts found**
- Try `--time month` or `--time year`
- Test your query in a browser: `reddit.com/r/india/search.json?q="your keyword"&t=week`

**Rate limited (429)**
- Wait 10–15 minutes, then retry
- Reduce `LIMIT` to 10

**Email not sending**
- Make sure you're using an App Password, not your normal Gmail password
- Check all three env vars are set: `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `EMAIL_RECIPIENTS`
- Run without `--send` first to confirm scraping works

**Cron not running**
- Test the exact cron command manually in terminal first
- Check `output/cron.log` for errors
- Verify Python path with `which python3`

---

## Requirements

- Python 3.11+
- `anthropic` — for Claude AI analysis (optional)
- `python-dotenv` — for reading `.env`
- Gmail account with App Password — for sending email
