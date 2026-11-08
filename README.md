# arcaneblast.com

The Arcane Blast studio website, served by GitHub Pages from this repository (`master`, root, custom domain in `CNAME`).

It's one static page with no build step: `index.html`, `assets/css/site.css`, `assets/js/site.js`.

## The games list updates itself

`scripts/update_games.py` reads both store accounts:

- App Store: developer **Arcane Blast** (`id1685863359`), through Apple's public lookup API
- Google Play: developer **Lucky Potion**, from its public developer page

It merges them into one list (a game on both stores becomes one card with both buttons), downloads the icon, feature graphic and screenshots into `assets/games/<game>/`, and rewrites the parts of `index.html` between the `<!-- games:… -->` and `<!-- icons:… -->` markers, plus the game counts. `data/games.json` holds the merged list.

The GitHub Action `.github/workflows/update-games.yml` runs it every day at 04:23 UTC and commits only when something changed, so a new release shows up the next morning and a game removed from a store disappears. To run it right away, open **Actions → Update games list → Run workflow**.

If one store can't be read (outage, page change), that store's games are kept from the last good run, so the site never empties itself.

### Hand edits

`data/overrides.json`:

- `hide`: bundle ids (or App Store ids) of games to leave off the site
- `order`: ids to pin at the top, in this order; the rest follow newest first
- `games`: per-game changes keyed by bundle id, such as a shorter `tagline` or `title`

Edit the file, then run the action (or the script) to apply it.

### Run it locally

```bash
python scripts/update_games.py
```

Python 3.9+. Pillow (`pip install pillow`) is optional but makes the images several times smaller.

## Other files that must stay

- `app-ads.txt`: ad network verification
- `privacy_policy*.html`, `*_privacy_policy.html`, `idle_archer_terms_and_conditions.html`: linked from the store listings
- `CNAME`: the custom domain
