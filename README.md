# Reddit Monitor

**Track any topic on Reddit and get a daily email summary — no coding experience needed beyond the one-time setup.**

Point it at any keywords ("Swiggy delivery", "UPI failed", "AI regulation") and it scrapes Reddit, runs AI analysis, and delivers a clean email digest every morning.

---

## What lands in your inbox every day

- **AI Summary** — 3–4 sentences on what Reddit is actually saying about your topic
- **Sentiment score** — is the mood positive, negative, or neutral? Is it getting better or worse vs yesterday?
- **Key Themes** — the main topics being discussed, with a NEW or RECURRING badge so you spot ghost issues
- **Top Concerns** — what people are genuinely worried about
- **Recommended Actions** — specific next steps suggested by the AI
- **All Posts** — every post found, clickable, sorted by upvotes
- **Urgent alert** — a separate red email if sentiment crashes below a critical threshold

Works for any topic. Brand monitoring, competitor tracking, policy research, category pulse — anything.

---

## What you need before starting

- **A computer with Python installed** (Python 3.11 or newer — [download here](https://www.python.org/downloads/))
  - **Windows users — important:** During Python installation, you'll see a checkbox at the very bottom of the first screen that says **"Add Python.exe to PATH"**. You MUST check this box or nothing will work.
- **A Gmail account** — you'll create a special "App Password" for sending (takes 2 minutes, instructions below)
- **A Claude API key** from [console.anthropic.com](https://console.anthropic.com) — optional, the tool works without it, just no AI summary

---

## Setup (do this once)

### Step 1 — Download the tool

1. Click the green **Code** button at the top of this GitHub page and select **Download ZIP**
2. Unzip the downloaded file and move the folder to your **Desktop**
3. Open your **Terminal**
   - Mac: press `Cmd + Space`, type "Terminal", hit Enter
   - Windows: press the Windows key, search "Command Prompt", open it
4. Type this command and hit Enter to navigate into the folder:

```bash
cd Desktop/reddit-monitor-main
```

5. Install the required files by running:

```bash
pip3 install -r requirements.txt
```

---

### Step 2 — Create your settings file

In the `reddit-monitor-main` folder on your Desktop, find the file named `.env.example`.

> **Can't see it?** Files starting with a dot are hidden by default.
> - **Mac:** Open the folder in Finder and press `Cmd + Shift + .` (that's a period) to reveal hidden files
> - **Windows:** In File Explorer, click **View → Show → Hidden items**

Once you can see it:
- **Duplicate** the file (right-click → Duplicate on Mac, or Copy + Paste on Windows)
- **Rename** the copy to exactly `.env` — just `.env`, with a dot at the start and nothing after it (no `.txt`)

---

### Step 3 — Add your credentials

Open the `.env` file in any text editor and fill in the values:

```
ANTHROPIC_API_KEY=sk-ant-...        ← paste your Claude key here (skip if you don't have one)
GMAIL_USER=you@gmail.com            ← the Gmail address that will send the emails
GMAIL_APP_PASSWORD=xxxx xxxx xxxx   ← see instructions below
EMAIL_RECIPIENTS=you@email.com,colleague@email.com   ← who gets the email
```

**Getting a Gmail App Password** (you can't use your normal Gmail password here):
1. Go to your Google Account → **Security**
2. Make sure **2-Step Verification is ON** (required)
3. Search for **"App Passwords"** in the search bar at the top
4. Create one → choose "Mail" → copy the 16-character code it gives you
5. Paste that code into `GMAIL_APP_PASSWORD` in your `.env` file

> Tip: If you have a spare Gmail address, use that for sending so your personal inbox stays clean.

Save the file when done.

---

### Step 4 — Tell it what to track

Open the file `reddit_monitor.py` in any text editor (TextEdit on Mac, Notepad on Windows, or VS Code if you have it).

Find the section near the top that looks like this and fill it in:

```python
TOPIC       = "YOUR TOPIC HERE"           # Give your topic a name
KEYWORDS    = ["keyword 1", "keyword 2"]  # What to search for on Reddit
SUBREDDITS  = ["subreddit1", "subreddit2"] # Which Reddit communities to search
```

**Examples to copy-paste and adapt:**

```python
# Swiggy brand monitoring
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

# UPI / payments
TOPIC      = "UPI issues"
KEYWORDS   = ["UPI failed", "UPI down", "payment failed"]
SUBREDDITS = ["india", "IndiaInvestments", "personalfinanceindia"]

# Anything else
TOPIC      = "AI regulation"
KEYWORDS   = ["AI ban", "AI regulation", "deepfake law"]
SUBREDDITS = ["india", "worldnews", "technology"]
```

Save the file when done.

---

### Step 5 — Test it

In your terminal, make sure you're inside the `reddit-monitor-main` folder (if you closed it, run `cd Desktop/reddit-monitor-main` again), then run:

```bash
python3 reddit_monitor.py
```

This scrapes Reddit and **opens a preview of the email in your browser — nothing is sent yet.** Check that it looks right.

When you're happy, send it for real:

```bash
python3 reddit_monitor.py --send
```

---

## Running it daily (pick one option)

### Option A — GitHub Actions (runs even when your laptop is off) ✅ Recommended

This runs the script automatically at 11 AM every day using GitHub's free servers — no laptop needed.

**One-time setup:**

1. Create a free account at [github.com](https://github.com) if you don't have one
2. Make a copy of this tool into your own GitHub account — click the **Fork** button at the top-right of this page, then click **Create fork**
3. In your forked copy, go to **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

Add these secrets one by one (click "New repository secret", enter the name and value, save, repeat):

| Secret name | What to put |
|---|---|
| `GMAIL_USER` | your Gmail address |
| `GMAIL_APP_PASSWORD` | your 16-character App Password |
| `EMAIL_RECIPIENTS` | comma-separated list of recipients |
| `ANTHROPIC_API_KEY` | your Claude key (optional) |
| `REDDIT_CLIENT_ID` | see note below |
| `REDDIT_CLIENT_SECRET` | see note below |

> **Reddit credentials:** GitHub's servers are blocked by Reddit's public API, so you need a free Reddit app to get around this. Go to [old.reddit.com/prefs/apps](https://old.reddit.com/prefs/apps), scroll to the very bottom, click **"are you a developer? create an app"**, choose type **script**, set redirect URI to `http://localhost`, tick the reCAPTCHA, and hit create. The `client_id` is the short string directly under the app name. The `client_secret` is labeled "secret". After creating, open `reddit_monitor.py` and change `reddit_monitor_bot` in the `_UA` line near the top to your actual Reddit username.

4. Go to the **Actions** tab → **Daily Reddit Digest** → **Run workflow** to do your first manual test run and confirm an email arrives

After that it fires automatically at 11 AM IST every day. You can see the logs under the Actions tab.

---

### Option B — Mac cron (laptop must be on at 11 AM)

In your terminal, run this command (this opens a friendlier text editor called nano):

```bash
env EDITOR=nano crontab -e
```

Add this line at the bottom — replace `/path/to/reddit-monitor-main` with the actual folder path (e.g. `/Users/yourname/Desktop/reddit-monitor-main`):

```
0 11 * * * cd /path/to/reddit-monitor-main && /usr/bin/python3 reddit_monitor.py --send >> output/cron.log 2>&1
```

To save: press `Ctrl + O` then `Enter`. To exit: press `Ctrl + X`.

To find your Python path if needed, run: `which python3`

> **Mac users:** You may need to grant Terminal full disk access for cron to work — System Settings → Privacy & Security → Full Disk Access → add Terminal.

---

## Other useful commands

All of these are run in your terminal, inside the `reddit-monitor-main` folder:

```bash
# Preview email in browser without sending
python3 reddit_monitor.py

# Send the email
python3 reddit_monitor.py --send

# Run without AI analysis (faster, no Claude key needed)
python3 reddit_monitor.py --no-ai

# Try a different topic without editing the file
python3 reddit_monitor.py --topic "UPI issues" --keywords "UPI" "NPCI" --subreddits india

# Search further back in time
python3 reddit_monitor.py --time month

# Show all posts again even if already sent before
python3 reddit_monitor.py --no-dedup --send
```

---

## Troubleshooting

**"You haven't configured the script yet"**
- Open `reddit_monitor.py` and fill in `TOPIC`, `KEYWORDS`, and `SUBREDDITS` at the top

**No posts found**
- Try a longer time range: add `--time month` to your command
- Check your spelling — keywords must match how people actually write on Reddit

**Email not arriving**
- Make sure you used an App Password, not your normal Gmail password
- Check your spam/promotions folder
- Run without `--send` first to confirm the scraping is working

**"Nothing new since last run"**
- The tool remembers posts it already sent and skips them
- Add `--no-dedup` to your command to include everything

**Scheduled run not firing (Mac cron)**
- Run the command manually in terminal first to confirm it works
- Check `output/cron.log` for error messages
- Verify your Python path: `which python3`

**GitHub Actions getting a 403 error from Reddit**
- You need to add `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` as GitHub secrets — see setup instructions above

**Windows: "python is not recognized"**
- Re-install Python from [python.org](https://www.python.org/downloads/) and make sure to check **"Add Python.exe to PATH"** during installation

---

## Files saved after each run

Everything goes into an `output/` folder that gets created automatically:

| File | What it is |
|---|---|
| `email_preview.html` | Open this in your browser to preview the email |
| `reddit_data_[date].json` | Raw posts and AI analysis — useful for deeper dives |
| `history.json` | Tracks sentiment across runs — powers the trend tracking |
| `seen_ids.txt` | Remembers which posts were already sent so you don't get duplicates |

---

## Requirements

- Python 3.11+
- Gmail account with an App Password
- Claude API key from [console.anthropic.com](https://console.anthropic.com) — optional, but recommended for the AI summary
