# Rockstar HQ feed (TGA x GTA VI)

Posts every new GTA VI item from Rockstar into the #rockstar-hq channel of your Discord server, by itself,
every 15 minutes, for free. You set it up once (about 15 minutes) and never touch it again.

## What it watches
- Rockstar Games on YouTube (GTA VI videos only; set YT_FILTER=0 for every upload)
- Rockstar's GTA VI site: home, media, music, Only in Leonida, the newswire GTA VI tag
- The Rockstar Store GTA VI collection
- Fallback: if Rockstar's site cannot be reached, a Google News search limited to rockstargames.com

Newswire posts arrive as an embed: Rockstar's own title and summary, the picture, a link.
Rockstar offers no public RSS feed for its newswire, so this reads the public pages the way a browser does.

## Setup (once)
1. Run the Discord setup script (tga_leonida_setup.py). It prints a WEBHOOK URL for #rockstar-hq.
2. Create a new PUBLIC repository on github.com (public = unlimited free Action minutes), e.g. tga-rockstar-hq.
3. Put these files in it. The easy way, with Terminal in this folder:
       git init -b main
       git add .
       git commit -m "Rockstar HQ feed"
       git remote add origin https://github.com/YOUR-NAME/tga-rockstar-hq.git
       git push -u origin main
   (No git? On the repo page choose Add file > Upload files for everything except the hidden .github folder,
   then Add file > Create new file, type the name  .github/workflows/rockstar-hq.yml  and paste that file's text.)
4. In the repo: Settings > Secrets and variables > Actions > New repository secret.
   Name DISCORD_WEBHOOK_URL, value = the webhook URL. Never paste it anywhere else.
5. Optional pings: Actions > Variables > New variable  PING_ROLE_ID = the id of your "Announcements Ping" role
   (Discord: User Settings > Advanced > Developer Mode on, then right-click the role > Copy Role ID).
6. In the repo open the Actions tab, enable workflows if asked, choose "Rockstar HQ feed", Run workflow.
   Leave backfill at 0 to start silently, or type 3 to also post Rockstar's 3 newest items right now.
   The first run records everything that already exists so you do not get a flood.
7. Check #rockstar-hq. From now on new items appear on their own.

## Optional: AI TL;DR under each newswire post (free)
Get a free key at aistudio.google.com/apikey. In your GitHub repo: Settings > Secrets and variables > Actions > New repository secret,
name GEMINI_API_KEY. Each new newswire post then gets three bullets (what, when, where) from Gemini under it.
If the page reveals story details, it posts a one-line notice and no summary. Remove the secret to turn it off. If Google retires the model
name, add a variable GEMINI_MODEL with the new name.

## Also saved for the TGA VI Bot
Each run saves the last 20 posted items (title, link, time) in recent.json in your repo. The TGA VI Bot's /whatsnew reads it from
https://raw.githubusercontent.com/YOUR-NAME/tga-rockstar-hq/main/recent.json

## Checking it
- Test the webhook only:  DISCORD_WEBHOOK_URL="..." python3 rockstar_hq_poster.py --test-webhook
- See what it would post without posting:  python3 rockstar_hq_poster.py --dry-run
- Offline self-test (no internet needed):  python3 tests/test_poster.py

## If something goes quiet
- The Action fails once (you get a GitHub email) after about 2 hours of every source failing. Open the run log.
- GitHub pauses scheduled workflows in a repo with no activity for 60 days. State commits count as activity;
  if it ever stops, press Run workflow once.
- If Rockstar blocks GitHub's servers, you will see "403" in the log. The Google News fallback keeps posting
  headlines, and YouTube keeps posting videos. Do not work around a block; ask a mod to paste big news by hand.
- Wrong channel id? The script refuses to run on a YouTube channel that is not named Rockstar and says so.
