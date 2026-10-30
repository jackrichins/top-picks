# Top Picks

An AI-curated RSS feed built from your subscriptions. Four times a day (6 AM, 11:30 AM, 4 PM, and 7 PM Pacific), a GitHub Action fetches your feeds, has Claude score each new item against `interests.md`, merges duplicate stories, and publishes the best ones to a single feed you read in Reeder.

At 4:50 PM it also emails a **Kindle edition** to your Kindle: the day's picks as a text-only book with a dated cover, a front page, and sections. It arrives around 5:15 PM, in time for dinner.

## Setup (about 10 minutes)

1. **Create a repo.** Make a new GitHub repo named `top-picks` and push these files to it.
2. **Add your API key.** Get a key at [console.anthropic.com](https://console.anthropic.com). In the repo, go to **Settings > Secrets and variables > Actions** and add a secret named `ANTHROPIC_API_KEY`.
3. **Turn on Pages.** Go to **Settings > Pages**, choose **Deploy from a branch**, then pick `main` and `/docs`.
4. **Set your URL.** In `config.yaml`, set `site_url` to `https://jackrichins.github.io/top-picks`.
5. **Run it once.** Go to **Actions > Curate feeds > Run workflow**.
6. **Subscribe in Reeder** to `https://jackrichins.github.io/top-picks/top-picks.xml`.

## Kindle edition setup (about 5 minutes)

1. **Find your Kindle address.** On Amazon, go to **Manage Your Content and Devices > Preferences > Personal Document Settings**. Copy your Send to Kindle email (like `name_abc@kindle.com`).
2. **Approve the sender.** On the same page, add the Gmail address that will send the edition to the **Approved Personal Document Email List**.
3. **Make a Gmail app password.** Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords). This requires 2-Step Verification.
4. **Add three repo secrets:** `KINDLE_EMAIL`, `SMTP_USER` (the Gmail address), and `SMTP_PASSWORD` (the app password).
5. **Test it.** Go to **Actions > Curate feeds > Run workflow**, check **Also send the Kindle edition now**, and run it.

Notes:
- **It's text only.** YouTube links, podcast episodes, and embedded audio or video players are left out.
- **Quiet days are skipped.** If fewer than 3 articles were picked, no edition is sent.
- **Paywalled articles** show their summary and a link instead of the full text.

The first run only picks from the last 24 hours. After that, it only scores new items.

## Tuning

| To change | Edit |
|---|---|
| What counts as good | `interests.md` (plain English; add examples you loved) |
| How many picks | `min_score` and `max_per_run` in `config.yaml` |
| Feeds that always get through | `always_include` in `config.yaml` |
| Your subscriptions | Export OPML from Reeder and replace `feeds.opml` |
| Kindle sections and limits | `kindle` in `config.yaml` |
| Podcasts for Overcast | Set `podcasts.enabled: true`, then subscribe to `top-podcasts.xml` |

Each item in the feed starts with a **Why:** line and its score, so you can see the reasoning and adjust `interests.md` when a pick misses.

## Test locally

```sh
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...
python curate.py --dry-run     # prints picks, changes nothing
```

## Privacy note

Free GitHub Pages needs a public repo, so `interests.md` and your feed list are visible to anyone who finds the repo. The members-only British History Podcast feed (its URL holds your password) was left out of `feeds.opml` on purpose.
