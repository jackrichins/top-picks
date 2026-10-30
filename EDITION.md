# How Claude publishes an edition

Claude scheduled tasks follow these steps. Jack can edit this file to change how editions are made.

## Schedule (Pacific time)
| Edition | When | Kindle? |
|---|---|---|
| Weekday morning | Mon to Fri, ready by 10:00 AM | No |
| Weekday evening | Mon to Fri, ready by about 4:30 PM | Yes |
| Weekend | Sat and Sun, ready by 8:00 AM | Yes |

## Steps
1. **Set up.** From the repo root: `pip install -r requirements.txt --break-system-packages -q`
2. **Fetch.** `python3 curate.py --export /tmp/to_score.jsonl`
   - This prints how many items need scores. If it's 0, skip to step 5.
3. **Score.** Read `interests.md`, then read every line of `/tmp/to_score.jsonl`. Score every item from 1 to 10 for how much Jack would want to see it, following the score guide in `interests.md`:
   - Be strict. Most items should score below 7, but timely news the profile asks for counts as 7+.
   - Aim for **8 to 12 items at 7+** per edition (fewer on quiet days is fine).
   - `reason`: one short sentence saying why it matters to Jack. No em dashes.
   - `story`: a short lowercase slug naming the underlying story, so the same news from different sources shares a slug (like `iphone-duo-display-cracks`). Use the item's id for anything that isn't shared news.
   - Write `/tmp/scores.json` as one JSON object keyed by item id:
     `{"<id>": {"score": 7, "reason": "...", "story": "..."}, ...}`
     Use a short script to write it, and check that every id from the export has a score.
4. **Publish.** `python3 curate.py --apply /tmp/scores.json`
5. **Push.** Commit `docs/` and `state/` and push to `main`.
   - Morning edition message: `Morning edition`
   - Evening and weekend edition message: `Evening edition [kindle]` or `Weekend edition [kindle]`
   - The `[kindle]` tag starts the GitHub Action that builds The Richins Reader and emails it to Jack's Kindle.
   - If the push is rejected because the remote changed, `git pull --rebase` and push again.
6. **Check.** Confirm the push succeeded. Report the number of picks and the top 3 titles.
