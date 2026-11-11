# arcaneblast.com

The Arcane Blast studio website, served by GitHub Pages from this repository (`master`, root, custom domain in `CNAME`).

It's one static page with no build step: `index.html`, `assets/css/site.css`, `assets/js/site.js`.

## Updating the games list

`scripts/update_games.py` reads both store accounts:

- App Store: developer **Arcane Blast** (`id1685863359`), through Apple's public lookup API
- Google Play: developer **Lucky Potion**, from its public developer page

It merges them into one list (a game on both stores becomes one card with both buttons), downloads the icon, feature graphic and screenshots into `assets/games/<game>/`, and rewrites the parts of `index.html` between the `<!-- games:… -->` and `<!-- icons:… -->` markers, plus the game counts. `data/games.json` holds the merged list.

It runs on request, not on a schedule: run it (or ask Claude to "update the website"), check the page, then commit and push. New releases appear and games removed from a store disappear.

If one store can't be read (outage, page change), that store's games are kept from the last good run, so the site never empties itself.

### Hand edits

`data/overrides.json`:

- `hide`: bundle ids (or App Store ids) of games to leave off the site
- `order`: ids to pin at the top, in this order; the rest follow newest first
- `games`: per-game changes keyed by bundle id, such as a shorter `tagline` or `title`

Edit the file, then run the script to apply it.

### Run it locally

```bash
python scripts/update_games.py
```

Python 3.9+. Pillow (`pip install pillow`) is optional but makes the images several times smaller.

## Other files that must stay

- `app-ads.txt`: tells ad networks which sellers may sell ads in our games; removing it can cut ad revenue
- Privacy policies and terms, linked from the store listings (checked 11 Nov 2026):
  `privacy_policy.html` (Olympush, Mob Smash, Runestone Heroes), `privacy_policy_gp.html` (all other Google Play games),
  `bladefall_privacy_policy.html`, `fable_arena_privacy_policy.html`, plus `rise_of_necromancer_privacy_policy.html`,
  `idle_archer_privacy_policy.html`, `idle_archer_terms_and_conditions.html`, `privacy_policy_volleycraft.html`
  and `OLD/idle-archer-privacy-policy.html` for older links
- `e6trqq66h6bw97s2ltalp6ia5di6xe.html` (and its copy in `OLD/`): Facebook Business domain verification
- `resources/`, `other/images/`, `DeeplinkTest.html`: may be loaded by games or old links
- `CNAME`: the custom domain
