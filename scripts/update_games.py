#!/usr/bin/env python3
"""Refresh the games shown on arcaneblast.com from the two store accounts.

Sources
  * App Store: developer "Arcane Blast" (id 1685863359), via Apple's public
    iTunes Lookup API.
  * Google Play: developer "Lucky Potion", read from the public developer page
    and each game's store page.

What it writes
  * data/games.json             the merged list (one entry per game)
  * assets/games/<slug>/*.webp  icon, feature graphic and screenshots
  * index.html                  the parts between the "games:" markers

Hand edits go in data/overrides.json (hide a game, change a tagline, pin the
order). Run it with Python 3.9+; Pillow is optional but makes the images much
smaller (pip install pillow):

    python3 scripts/update_games.py

If one store can't be read, that store's games are kept from the last good run,
so a temporary outage or a store page change never empties the site.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import re
import shutil
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "games.json"
OVERRIDES_FILE = ROOT / "data" / "overrides.json"
ASSET_DIR = ROOT / "assets" / "games"
INDEX_FILE = ROOT / "index.html"

APPLE_DEVELOPER_ID = 1685863359
# The first country that lists a game provides its metadata; the others only
# catch games that are not released everywhere.
APPLE_COUNTRIES = ["us", "gb", "de", "cz", "my"]
GOOGLE_DEVELOPER = "Lucky Potion"
GOOGLE_COUNTRIES = ["us", "gb"]

MAX_SHOTS = 5
SHOT_WIDTH = 540
ICON_SIZE = 256
FEATURE_WIDTH = 960

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)


class StoreError(Exception):
    pass


# --------------------------------------------------------------------------
# HTTP


def fetch(url: str, *, tries: int = 3) -> bytes:
    last: Exception | None = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en"}
            )
            with urllib.request.urlopen(req, timeout=40) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise
            last = exc
        except Exception as exc:  # network hiccup
            last = exc
        time.sleep(2 + attempt * 3)
    raise StoreError(f"{url}: {last}")


# --------------------------------------------------------------------------
# App Store


def apple_games() -> list[dict]:
    found: dict[str, dict] = {}
    ok = False
    for country in APPLE_COUNTRIES:
        url = (
            "https://itunes.apple.com/lookup?"
            f"id={APPLE_DEVELOPER_ID}&entity=software&limit=200&country={country}"
        )
        try:
            payload = json.loads(fetch(url))
        except Exception as exc:
            print(f"  App Store {country}: {exc}", file=sys.stderr)
            continue
        ok = True
        for r in payload.get("results", []):
            if r.get("wrapperType") != "software" or r.get("kind") != "software":
                continue
            key = r["bundleId"].lower()
            if key not in found:
                found[key] = r
    if not ok:
        raise StoreError("App Store lookup failed in every country")
    if not found:
        raise StoreError("App Store returned no games")

    games = []
    for key, r in found.items():
        genres = [g for g in r.get("genres", []) if g != "Games"]
        icon = r.get("artworkUrl512") or r.get("artworkUrl100")
        games.append(
            {
                "key": key,
                "title": r["trackName"].strip(),
                "genre": genres[0] if genres else r.get("primaryGenreName", ""),
                "released": (r.get("releaseDate") or "")[:10],
                "tagline": first_sentence(r.get("description", "")),
                "icon_src": apple_base(icon),
                "shot_srcs": [
                    apple_base(u)
                    for u in (r.get("screenshotUrls") or r.get("ipadScreenshotUrls") or [])[:MAX_SHOTS]
                ],
                "ios": {
                    "id": r["trackId"],
                    "url": f"https://apps.apple.com/app/id{r['trackId']}",
                },
            }
        )
    return games


def apple_base(url: str) -> str:
    # https://is1-ssl.mzstatic.com/image/thumb/.../name.png/512x512bb.jpg -> drop the size part
    return url.rsplit("/", 1)[0]


# --------------------------------------------------------------------------
# Google Play

_DS_RE = re.compile(
    r"AF_initDataCallback\(\{key: '(ds:\d+)', hash: '\d+', data:(.*?), sideChannel: \{\}\}\);",
    re.S,
)


def _ds_blocks(page: str) -> dict:
    return {k: v for k, v in _DS_RE.findall(page)}


def _dig(obj, *path):
    try:
        for p in path:
            obj = obj[p]
        return obj
    except (IndexError, KeyError, TypeError):
        return None


def google_ids() -> list[str]:
    dev = urllib.parse.quote_plus(GOOGLE_DEVELOPER)
    ids: list[str] = []
    for country in GOOGLE_COUNTRIES:
        url = f"https://play.google.com/store/apps/developer?id={dev}&hl=en&gl={country}"
        page = fetch(url).decode("utf-8", "replace")
        for app_id in re.findall(r"/store/apps/details\?id=([A-Za-z0-9_.]+)", page):
            if app_id not in ids:
                ids.append(app_id)
    return ids


def google_app(app_id: str) -> dict | None:
    page = None
    for country in GOOGLE_COUNTRIES:
        url = f"https://play.google.com/store/apps/details?id={app_id}&hl=en&gl={country}"
        try:
            page = fetch(url).decode("utf-8", "replace")
            break
        except urllib.error.HTTPError:
            continue
    if page is None:
        return None
    raw = _ds_blocks(page).get("ds:5")
    if not raw:
        raise StoreError(f"Google Play page layout changed ({app_id})")
    a = _dig(json.loads(raw), 1, 2)
    title = _dig(a, 0, 0)
    if not title:
        raise StoreError(f"Google Play page layout changed ({app_id})")
    developer = _dig(a, 68, 0) or ""
    if developer.strip().lower() != GOOGLE_DEVELOPER.lower():
        print(f"  skip {app_id}: developer is {developer!r}", file=sys.stderr)
        return None

    shots = []
    for s in _dig(a, 78, 0) or []:
        src = _dig(s, 3, 2)
        if src:
            shots.append(src)
    feature = _dig(a, 96, 0, 3, 2)
    icon = _dig(a, 95, 0, 3, 2)
    return {
        "key": app_id.lower(),
        "title": title.strip(),
        "genre": _dig(a, 79, 0, 0, 0) or "",
        "released": parse_play_date(_dig(a, 10, 0)),
        "tagline": (_dig(a, 73, 0, 1) or "").strip()
        or first_sentence(_dig(a, 72, 0, 1) or ""),
        "icon_src": icon,
        "feature_src": feature,
        "shot_srcs": shots[:MAX_SHOTS],
        "android": {
            "id": app_id,
            "url": f"https://play.google.com/store/apps/details?id={app_id}",
        },
    }


def google_games() -> list[dict]:
    ids = google_ids()
    if not ids:
        raise StoreError("Google Play developer page listed no games (layout change?)")
    games = []
    for app_id in ids:
        game = google_app(app_id)
        if game:
            games.append(game)
    if not games:
        raise StoreError("Google Play returned no games")
    return games


def parse_play_date(text: str | None) -> str:
    if not text:
        return ""
    for fmt in ("%b %d, %Y", "%d %b %Y", "%B %d, %Y"):
        try:
            return dt.datetime.strptime(text.strip(), fmt).date().isoformat()
        except ValueError:
            pass
    return ""


# --------------------------------------------------------------------------
# Merging


def first_sentence(text: str, limit: int = 120) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text or "")
    text = re.sub(r"<[^>]+>", "", text)
    for line in text.splitlines():
        line = line.strip()
        if len(line) < 30:
            continue
        sentence = re.split(r"(?<=[.!?])\s", line, maxsplit=1)[0]
        if len(sentence) > limit:
            sentence = sentence[:limit].rsplit(" ", 1)[0].rstrip(",;:-") + "…"
        return sentence
    return ""


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "game"


def merge(ios: list[dict], android: list[dict], overrides: dict) -> list[dict]:
    by_key: dict[str, dict] = {}
    by_title: dict[str, str] = {}

    def norm_title(t: str) -> str:
        return slugify(re.split(r"[:\-–—]", t)[0])

    for g in android + ios:  # Google Play first: it has feature graphics and taglines
        key = g["key"]
        same_name = by_title.get(norm_title(g["title"]))
        platform = "ios" if "ios" in g else "android"
        # Both stores normally share the bundle id; the name is only a fallback
        # for a game whose ids differ, and never merges two games of one store.
        if key not in by_key and same_name and platform not in by_key[same_name]:
            key = same_name
        cur = by_key.setdefault(key, {"key": key})
        for field in ("title", "genre", "tagline", "icon_src", "feature_src"):
            if g.get(field) and not cur.get(field):
                cur[field] = g[field]
        if g.get("shot_srcs") and not cur.get("shot_srcs"):
            cur["shot_srcs"] = g["shot_srcs"]
        for platform in ("ios", "android"):
            if platform in g:
                cur[platform] = g[platform]
        if g.get("released") and (not cur.get("released") or g["released"] < cur["released"]):
            cur["released"] = g["released"]
        by_title.setdefault(norm_title(cur["title"]), key)

    hidden = {str(h).lower() for h in overrides.get("hide", [])}
    per_game = {k.lower(): v for k, v in overrides.get("games", {}).items()}
    games = []
    slugs: set[str] = set()
    for g in sorted(by_key.values(), key=lambda x: (x.get("released", ""), x["key"])):
        ids = {g["key"], str(g.get("ios", {}).get("id", "")), str(g.get("android", {}).get("id", "")).lower()}
        if ids & hidden:
            continue
        extra = next((per_game[i] for i in ids if i in per_game), {})
        for field in ("title", "tagline", "genre"):
            if extra.get(field):
                g[field] = extra[field]
        # two games with one name still get their own image folders (oldest keeps the plain one)
        slug, n = slugify(g["title"]), 2
        while slug in slugs:
            slug, n = f"{slugify(g['title'])}-{n}", n + 1
        slugs.add(slug)
        g["slug"] = slug
        games.append(g)

    order = [str(o).lower() for o in overrides.get("order", [])]

    def sort_key(g):
        ids = [g["key"], str(g.get("ios", {}).get("id", ""))]
        pinned = min((order.index(i) for i in ids if i in order), default=len(order))
        newest_first = -int(g.get("released", "").replace("-", "") or 0)
        return (pinned, newest_first, g["title"].lower())

    games.sort(key=sort_key)
    return games


# --------------------------------------------------------------------------
# Images


# Target sizes per image kind: (App Store size segment, Google Play size option, max width)
IMAGE_KINDS = {
    "icon": (f"{ICON_SIZE}x{ICON_SIZE}bb", f"s{ICON_SIZE}", ICON_SIZE),
    "feature": (f"{FEATURE_WIDTH}x0w", f"w{FEATURE_WIDTH}", FEATURE_WIDTH),
    "shot": (f"{SHOT_WIDTH}x0w", f"w{SHOT_WIDTH}", SHOT_WIDTH),
}
WEBP_QUALITY = 80

try:  # Pillow makes the images 2-5x smaller; without it the stores' own WebP is used
    from PIL import Image  # type: ignore
except ImportError:  # pragma: no cover
    Image = None


def store_variant(base: str, kind: str, fmt: str) -> str:
    apple, google, _ = IMAGE_KINDS[kind]
    if "mzstatic.com" in base:
        return f"{base}/{apple}.{fmt}"
    return f"{base}={google}-" + ("rj-l92" if fmt == "jpg" else "rw")


def download_image(base: str, kind: str) -> bytes:
    if Image is None:
        return fetch(store_variant(base, kind, "webp"))
    import io

    raw = fetch(store_variant(base, kind, "jpg"))
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    max_w = IMAGE_KINDS[kind][2]
    if im.width > max_w:
        im = im.resize((max_w, round(im.height * max_w / im.width)), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, "WEBP", quality=WEBP_QUALITY, method=6)
    return out.getvalue()


def shot_number(name: str) -> int:
    return int(name.split("-")[1]) if name.startswith("shot-") else 0


def sync_images(games: list[dict], previous: dict[str, dict]) -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    keep = set()
    for g in games:
        folder = ASSET_DIR / g["slug"]
        keep.add(folder.name)
        folder.mkdir(exist_ok=True)
        prev_src = previous.get(g["key"], {}).get("_src", {})
        src: dict[str, str] = {}
        wanted = [("icon", g.get("icon_src"))]
        if g.get("feature_src"):
            wanted.append(("feature", g["feature_src"]))
        wanted += [(f"shot-{i + 1}", u) for i, u in enumerate(g.get("shot_srcs", []))]

        files = {}
        for name, url in wanted:
            if not url:
                continue
            path = folder / f"{name}.webp"
            if not path.exists() or prev_src.get(name) != url:
                try:
                    path.write_bytes(download_image(url, name.split("-")[0]))
                    print(f"  image {g['slug']}/{path.name}")
                except Exception as exc:
                    print(f"  image failed {url}: {exc}", file=sys.stderr)
                    if not path.exists():
                        continue
            src[name] = url
            files[name] = f"assets/games/{g['slug']}/{path.name}"
        # drop files that the store no longer has (e.g. fewer screenshots)
        for f in folder.glob("*.webp"):
            if f.stem not in files:
                f.unlink()
        g["images"] = {
            "icon": files.get("icon"),
            "feature": files.get("feature"),
            "shots": [files[k] for k in sorted(files, key=shot_number) if k.startswith("shot-")],
        }
        g["_src"] = src
    for folder in ASSET_DIR.iterdir():
        if folder.is_dir() and folder.name not in keep:
            shutil.rmtree(folder)
            print(f"  removed {folder.name}")


def image_size(path: Path) -> tuple[int, int] | None:
    """Width and height of a WebP file, read from its header."""
    try:
        head = path.read_bytes()[:40]
    except OSError:
        return None
    if head[:4] != b"RIFF" or head[8:12] != b"WEBP":
        return None
    chunk = head[12:16]
    if chunk == b"VP8X":
        w = 1 + int.from_bytes(head[24:27], "little")
        h = 1 + int.from_bytes(head[27:30], "little")
        return w, h
    if chunk == b"VP8 ":
        w = int.from_bytes(head[26:28], "little") & 0x3FFF
        h = int.from_bytes(head[28:30], "little") & 0x3FFF
        return w, h
    if chunk == b"VP8L":
        b = head[21:25]
        w = 1 + (((b[1] & 0x3F) << 8) | b[0])
        h = 1 + (((b[3] & 0x0F) << 10) | (b[2] << 2) | ((b[1] & 0xC0) >> 6))
        return w, h
    return None


# --------------------------------------------------------------------------
# HTML


def esc(text) -> str:
    return html.escape(str(text), quote=True)


def img_tag(path: str, alt: str, cls: str = "", lazy: bool = True) -> str:
    size = image_size(ROOT / path)
    dims = f' width="{size[0]}" height="{size[1]}"' if size else ""
    loading = ' loading="lazy"' if lazy else ""
    klass = f' class="{cls}"' if cls else ""
    return f'<img{klass} src="{esc(path)}" alt="{esc(alt)}"{dims}{loading} decoding="async">'


# Store genre names that read oddly on their own
GENRE_NAMES = {"Card": "Card game", "Roleplaying": "RPG", "Role Playing": "RPG", "Board": "Board game"}


def render_card(g: dict, index: int) -> str:
    platforms = [p for p in ("ios", "android") if p in g]
    imgs = g["images"]
    shots = imgs.get("shots", [])
    title = g["title"].replace(" - ", " – ")
    lazy = index >= 3

    backdrop = img_tag(imgs["icon"], "", "game-backdrop", lazy) if imgs.get("icon") else ""
    if imgs.get("feature"):
        media = backdrop + img_tag(imgs["feature"], "", "game-feature", lazy)
    else:
        trio = "".join(img_tag(s, "", "", lazy) for s in shots[:3])
        media = f'{backdrop}<span class="game-trio">{trio}</span>'

    if shots:
        media = (
            f'<button class="game-media" type="button" data-shots="{esc(json.dumps(shots))}" '
            f'data-title="{esc(title)}" aria-label="Screenshots of {esc(title)}">{media}</button>'
        )
    else:
        media = f'<div class="game-media">{media}</div>'

    year = g.get("released", "")[:4]
    genre = GENRE_NAMES.get(g.get("genre", ""), g.get("genre", ""))
    meta = " · ".join(x for x in (genre, year) if x)
    links = []
    if "ios" in g:
        links.append(
            f'<a class="store" href="{esc(g["ios"]["url"])}" target="_blank" rel="noopener" '
            f'aria-label="{esc(title)} on the App Store">'
            f'App Store<svg aria-hidden="true"><use href="#i-arrow"/></svg></a>'
        )
    if "android" in g:
        links.append(
            f'<a class="store" href="{esc(g["android"]["url"])}" target="_blank" rel="noopener" '
            f'aria-label="{esc(title)} on Google Play">'
            f'Google Play<svg aria-hidden="true"><use href="#i-arrow"/></svg></a>'
        )
    if shots:
        links.append(
            f'<button class="shots-link" type="button" data-shots="{esc(json.dumps(shots))}" '
            f'data-title="{esc(title)}" aria-label="Screenshots of {esc(title)}" title="Screenshots">'
            f'<svg aria-hidden="true"><use href="#i-shots"/></svg><span>Screenshots</span></button>'
        )
    icon = img_tag(imgs["icon"], "", "game-icon", lazy) if imgs.get("icon") else ""
    return (
        f'<article class="game" data-platforms="{" ".join(platforms)}">'
        f"{media}"
        f'<div class="game-body">{icon}'
        f'<div class="game-head"><h3>{title_html(title)}</h3><p class="game-meta">{esc(meta)}</p></div>'
        f'<p class="game-tagline">{esc(finish_sentence(g.get("tagline", "")))}</p>'
        f'<p class="game-links">{"".join(links)}</p>'
        f"</div></article>"
    )


def finish_sentence(text: str) -> str:
    """Store taglines end calmly: a full stop, never an exclamation mark."""
    text = text.strip()
    if text.endswith("!"):
        text = text[:-1].rstrip()
    return text + "." if text and text[-1].isalnum() else text


def title_html(title: str) -> str:
    """'Log Rush: Build & Battle' -> the name, then the subtitle on its own softer line.
    The separator stays in the text for screen readers and copy-paste."""
    m = re.match(r"^(.+?)(:|!| –| -)\s+(.+)$", title)
    if not m or len(m.group(1)) < 3:
        return esc(title)
    main, sep, sub = m.group(1), m.group(2), m.group(3)
    if sep == "!":
        main, hidden = main + "!", " "
    elif sep == ":":
        hidden = ": "
    else:
        hidden = " – "
    return (
        f'{esc(main)}<span class="sep">{esc(hidden)}</span>'
        f'<span class="sub">{esc(sub)}</span>'
    )


def render_icons(games: list[dict]) -> str:
    out = []
    for i, g in enumerate(games):
        if g["images"].get("icon"):
            out.append(
                f'<li style="--i:{i}">{img_tag(g["images"]["icon"], g["title"], "", False)}</li>'
            )
    return "".join(out)


def replace_block(page: str, name: str, content: str) -> str:
    pattern = re.compile(rf"(<!-- {name}:start -->)(.*?)(<!-- {name}:end -->)", re.S)
    if not pattern.search(page):
        raise SystemExit(f"index.html is missing the <!-- {name}:start/end --> markers")
    return pattern.sub(lambda m: m.group(1) + content + m.group(3), page, count=1)


def render_page(games: list[dict]) -> None:
    page = INDEX_FILE.read_text(encoding="utf-8")
    cards = "\n".join(render_card(g, i) for i, g in enumerate(games))
    page = replace_block(page, "games", "\n" + cards + "\n")
    page = replace_block(page, "icons", render_icons(games))
    counts = {
        "all": len(games),
        "ios": sum("ios" in g for g in games),
        "android": sum("android" in g for g in games),
    }
    for name, n in counts.items():
        page = re.sub(
            rf'(<[^>]*data-count="{name}"[^>]*>)[^<]*(<)', rf"\g<1>{n}\g<2>", page
        )
    INDEX_FILE.write_text(page, encoding="utf-8", newline="\n")


# --------------------------------------------------------------------------


def public_view(games: list[dict]) -> list[dict]:
    fields = ("slug", "title", "genre", "released", "tagline", "ios", "android", "images", "_src", "key")
    return [{k: g[k] for k in fields if k in g} for g in games]


def main() -> int:
    previous_doc = json.loads(DATA_FILE.read_text(encoding="utf-8")) if DATA_FILE.exists() else {}
    previous = {g["key"]: g for g in previous_doc.get("games", [])}
    overrides = (
        json.loads(OVERRIDES_FILE.read_text(encoding="utf-8")) if OVERRIDES_FILE.exists() else {}
    )

    status = {}
    try:
        ios = apple_games()
        status["ios"] = "ok"
        print(f"App Store: {len(ios)} games")
    except Exception as exc:
        print(f"App Store unavailable, keeping last list: {exc}", file=sys.stderr)
        status["ios"] = "kept"
        ios = [restore(g, "ios") for g in previous.values() if "ios" in g]
    try:
        android = google_games()
        status["android"] = "ok"
        print(f"Google Play: {len(android)} games")
    except Exception as exc:
        print(f"Google Play unavailable, keeping last list: {exc}", file=sys.stderr)
        status["android"] = "kept"
        android = [restore(g, "android") for g in previous.values() if "android" in g]

    if not ios and not android:
        print("No games from either store and no previous list; nothing written.", file=sys.stderr)
        return 1

    games = merge(ios, android, overrides)
    sync_images(games, previous)
    view = public_view(games)

    digest = hashlib.sha256(json.dumps(view, sort_keys=True).encode()).hexdigest()
    if digest == previous_doc.get("digest"):
        updated = previous_doc.get("updated")
    else:
        updated = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    doc = {
        "updated": updated,
        "digest": digest,
        "sources": {
            "app_store": f"https://apps.apple.com/developer/id{APPLE_DEVELOPER_ID}",
            "google_play": "https://play.google.com/store/apps/developer?id="
            + urllib.parse.quote_plus(GOOGLE_DEVELOPER),
        },
        "games": view,
    }
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    render_page(games)
    print(f"{len(games)} games written ({status})")
    return 0


def restore(g: dict, platform: str) -> dict:
    """Rebuild a store record from the last good run, for one platform."""
    src = g.get("_src", {})
    shots = [src[k] for k in sorted(src, key=shot_number) if k.startswith("shot-")]
    out = {
        "key": g["key"],
        "title": g["title"],
        "genre": g.get("genre", ""),
        "released": g.get("released", ""),
        "tagline": g.get("tagline", ""),
        "icon_src": src.get("icon"),
        "shot_srcs": shots,
        platform: g[platform],
    }
    if src.get("feature"):
        out["feature_src"] = src["feature"]
    return out


if __name__ == "__main__":
    sys.exit(main())
