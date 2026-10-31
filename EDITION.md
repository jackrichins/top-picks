# How Claude publishes an edition

Claude scheduled tasks follow these steps. The evening and weekend tasks run with access to Jack's Mac so Mail can send the Kindle edition. Jack can edit this file to change how editions are made.

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
5. **Push.** Commit `docs/` and `state/` and push to `main` with the message `Morning edition`, `Evening edition`, or `Weekend edition`.
   - If the push is rejected because the remote changed, `git pull --rebase` and push again.
6. **Kindle edition (evening and weekend editions only).** Mail on Jack's Mac sends it.
   1. **Get the private Reeder links.** Read them from Jack's Mac with the `osascript` tool:
      `do shell script "cat /Users/jackr/RichinsReader/later-feed-url.txt"`
      These links are private. Never write them into the repo, a commit, or your report.
   2. **Write "The Day in Tech" (Techmeme briefing).**
      - Run `python3 kindle.py --techmeme-export /tmp/techmeme.json` and read the stories it saves (Techmeme's ranked Top News: headline, lede, source, link).
      - Pick the 8 to 12 most important stories. Merge stories about the same event.
      - For each, write a short `topic` (a few words, like a headline) and a `summary` of 1 to 2 sentences in your own words: what happened, and why it matters, especially to Jack (security, Apple, AI, Microsoft, the Pacific Northwest). Don't copy Techmeme's or the source's wording. No em dashes.
      - Keep the `link` and `source` (the publication name only, like "Reuters") from the export.
      - Write `/tmp/briefing.json` as `{"items": [{"topic": "...", "summary": "...", "link": "...", "source": "..."}]}`, most important first.
      - If Techmeme can't be reached, skip the briefing and build without it.
   3. **Build it** (this adds new articles Jack saved to Later or Links in Reeder, and the briefing):
      `mkdir -p /mnt/user-data/outputs && REEDER_LATER_FEED="<the links>" python3 kindle.py --no-send --briefing /tmp/briefing.json --out /mnt/user-data/outputs/The-Richins-Reader-YYYY-MM-DD.epub`
      Use today's date. It prints JSON with the title. If it says there are too few articles, skip the rest of this step.
   4. **Copy it to the Mac** with `device_commit_files`: stagedPath is the file above, devicePath is `/Users/jackr/RichinsReader/<same file name>`.
   5. **Send it** with the Mac's `osascript` tool, filling in the file name and title:
      ```applescript
      set f to POSIX file "/Users/jackr/RichinsReader/<file name>"
      tell application "Mail"
        set m to make new outgoing message with properties {subject:"<title>", content:"Your Richins Reader is attached.", visible:false, sender:"jack@jackrichins.com"}
        tell m
          make new to recipient at end of to recipients with properties {address:"jack_FDL360@kindle.com"}
          make new attachment with properties {file name:f} at after the last paragraph of content
        end tell
        delay 3
        send m
      end tell
      ```
   6. **Record it.** Only if the send succeeded: `python3 kindle.py --mark-sent`, then commit `state/` (the send time and which saved articles were delivered) with the message `Kindle edition sent` and push.
   7. If the Mac can't be reached, skip the send and don't mark it sent. The next Kindle edition will include these articles.
7. **Check.** Confirm the pushes succeeded. Report the number of picks, the top 3 titles, and whether the Kindle edition was sent.
