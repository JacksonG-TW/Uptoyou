#!/usr/bin/env python3
"""Draw the README pictures: `<name>.readme.svg` beside this file, and on request their `<name>.png`.

**What lives where.** The look is `style.json` beside this file (design tokens, W3C Design Tokens
Format Module 2025.10): every colour, family, size, stroke, radius and dash below is read from a
token's `$value`, and nothing visual is written here as a literal. What this file owns is the
drawing: where each box, frame and arrow sits, and which meaning colour each box carries. The facts
(what connects to what) are the archify specifications beside each picture (`<name>.json`), which
`--labels` names as each label's source.

**Why by hand.** A README column on GitHub is 838 px wide. archify's fixed text sizes rendered at
4–12 px there, against a 12 px floor, and no crop reaches it. These pictures are drawn on an
840-unit sheet instead, with 15 px box titles and 13 px for everything else, so every word renders
at about its own size. archify no longer checks their geometry: each drawing is read by eye at
838 px before it ships.

**The idiom** is a white sheet, black lines and arrows, dashed frames for groups, and a few colours
that each mean one thing in every picture. Changing the idiom, as against its tokens, is a structure
change.

    python3 docs/diagrams/draw.py            # write every <name>.readme.svg
    python3 docs/diagrams/draw.py --check    # change nothing; exit 1 if a committed SVG differs
    python3 docs/diagrams/draw.py --labels   # print {picture: [{text, source}]} as JSON
    python3 docs/diagrams/draw.py --png      # also rasterise each SVG to <name>.png at 2x

Run from `app/` or anywhere: paths resolve from this file. The SVG modes are the standard library
alone. `--png` needs Playwright with its Chromium, and a Noto Sans TC font file named by
`UPTO_DIAGRAM_FONT` (the repository carries no full CJK face): every family the texts name is mapped
to it for the run, and without it the Chinese labels rasterise as empty boxes.

The architecture picture is drawn elsewhere for now; it joins this file once its vendor marks have a
home under `marks/` (read `marks/NOTICE.md`).
"""
import html
import json
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
TOKENS = json.loads((HERE / "style.json").read_text(encoding="utf-8"))


def tok(path):
    """A token's `$value`, by its dotted path."""
    node = TOKENS
    for part in path.split("."):
        node = node[part]
    return node["$value"]


def color(path):
    return tok(path)["hex"]


def num(path):
    """A dimension token's number, written the way the drawing writes it (15, not 15.0)."""
    v = tok(path)["value"]
    return int(v) if float(v).is_integer() else v


def dash(path):
    return " ".join(str(num_of(d)) for d in tok(path)["dashArray"])


def num_of(d):
    v = d["value"]
    return int(v) if float(v).is_integer() else v


INK, MUTED, DASH = color("color.ink"), color("color.muted"), color("color.dash")
FILL, GROUND = color("color.fill"), color("color.background")
W = num("size.canvas")
HEAD, TITLE, BODY = num("font.size.heading"), num("font.size.title"), num("font.size.body")
W_HEAD, W_TITLE = tok("font.weight.heading"), tok("font.weight.title")
W_LABEL, W_BODY = tok("font.weight.label"), tok("font.weight.body")
FAMILY = tok("font.family")
CJK = tok("font.familyCJK")
TEXT_FAMILY = ", ".join(FAMILY)
SHEET_FAMILY = ", ".join(FAMILY[:-1] + [f"'{CJK}'", FAMILY[-1]])

# Each meaning, as (border, tint, label). The keys are the tokens' own names under color.key.
KEY = {k: (color(f"color.key.{k}.border"), color(f"color.key.{k}.tint"), color(f"color.key.{k}.label"))
       for k in ("public", "weather", "product", "stored", "pipeline", "alert")}

_labels = []   # every text drawn into the current picture, for --labels


def text(x, y, s, size, weight, fill=INK, anchor="middle"):
    _labels.append(s)
    return (f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="{size}" '
            f'font-weight="{weight}" fill="{fill}" '
            f'font-family="{TEXT_FAMILY}">{html.escape(s)}</text>')


def box(x, y, w, h, label, caption=None, key=None):
    """A box. `key` names its meaning colour; with none it is the neutral fill."""
    border, tint = (KEY[key][0], KEY[key][1]) if key else (INK, FILL)
    width = num("stroke.alert") if key == "alert" else num("stroke.box")
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{num("radius.box")}" fill="{tint}" '
           f'stroke="{border}" stroke-width="{width}"/>']
    cy = y + h / 2
    if caption:
        out.append(text(x + w / 2, cy - 3, label, TITLE, W_TITLE))
        out.append(text(x + w / 2, cy + 15, caption, BODY, W_BODY, MUTED))
    else:
        out.append(text(x + w / 2, cy + 5, label, TITLE, W_TITLE))
    return "".join(out)


def frame(x, y, w, h, label, key=None):
    """A dashed group outline, in its meaning colour when it has one."""
    stroke, fill = (KEY[key][0], KEY[key][2]) if key else (DASH, MUTED)
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{num("radius.frame")}" fill="none" '
            f'stroke="{stroke}" stroke-width="{num("stroke.frameDashed")}" stroke-dasharray="{dash("dash.frame")}"/>'
            + text(x + 10, y + 18, label, BODY, W_TITLE, fill, "start"))


def line(pts, label=None, at=None, dashed=False, anchor="middle"):
    d = " ".join(("M" if i == 0 else "L") + f"{x},{y}" for i, (x, y) in enumerate(pts))
    out = [f'<path d="{d}" fill="none" stroke="{INK}" stroke-width="{num("stroke.line")}"'
           + (f' stroke-dasharray="{dash("dash.line")}"' if dashed else "") + ' marker-end="url(#a)"/>']
    if label:
        x, y = at
        out.append(text(x, y, label, BODY, W_LABEL, MUTED, anchor))
    return "".join(out)


def sheet(h, title):
    return [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h}" viewBox="0 0 {W} {h}" '
            f'font-family="{SHEET_FAMILY}">',
            f'<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
            f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{INK}"/></marker></defs>',
            f'<rect width="{W}" height="{h}" fill="{GROUND}"/>',
            text(20, 34, title, HEAD, W_HEAD, INK, "start")]


def notes(q, y, heading, bullets):
    """A note block in the README's own text sizes."""
    q.append(text(20, y, heading, TITLE, W_TITLE, INK, "start"))
    for i, b in enumerate(bullets):
        q.append(text(32, y + 24 + 20 * i, "• " + b, BODY, W_BODY, MUTED, "start"))
    return y + 24 + 20 * len(bullets) + 26


# === The pictures ===================================================================================

def etl_flow():
    q = sheet(500, "Up to You — the scheduled pipeline")
    for x, label in ((20, "PUBLIC SOURCES"), (228, "AIRFLOW"), (452, "POSTGRESQL"), (655, "READ BY")):
        q.append(text(x, 66, label, BODY, W_TITLE, MUTED, "start"))
    q.append(box(20, 96, 180, 64, "中央氣象署 · 2 sources", "forecast + observation", "weather"))
    q.append(box(20, 226, 180, 64, "5 daily sources", "zip, csv · nightly", "public"))
    q.append(box(228, 161, 150, 64, "6 ingest DAGs", "one per source", "pipeline"))
    q.append(box(452, 161, 160, 64, "PostgreSQL", "publications + ledger", "stored"))
    q.append(box(228, 336, 160, 64, "Value + freshness", "each ingest · nightly", "pipeline"))
    q.append(box(655, 80, 165, 56, "The product", "reads names, weather", "product"))
    q.append(box(655, 160, 165, 56, "Nightly backup", "pg_dump → S3", "stored"))
    q.append(box(655, 240, 165, 56, "Dataset export", "places → Parquet", "stored"))
    q.append(box(655, 340, 165, 56, "Telegram", "alerts", "alert"))
    q.append(line([(200, 128), (214, 128), (214, 181), (224, 181)], "hourly", (207, 118), anchor="start"))
    q.append(line([(200, 258), (214, 258), (214, 205), (224, 205)]))
    q.append(line([(378, 193), (448, 193)], "new only", (410, 185)))
    q.append(line([(612, 193), (634, 193), (634, 108), (651, 108)]))
    q.append(line([(634, 188), (651, 188)]))
    q.append(line([(634, 193), (634, 268), (651, 268)]))
    q.append(line([(532, 225), (532, 368), (392, 368)], "counts, hours", (462, 386)))
    q.append(line([(308, 400), (308, 436), (737, 436), (737, 400)], "a rule breaks", (522, 428), dashed=True))
    # Any task that fails after its 2 retries alerts too (the on_failure_callback in every ingest DAG).
    q.append(line([(240, 225), (240, 315), (220, 315), (220, 462), (790, 462), (790, 400)], "a task fails, after 2 retries",
                  (505, 486)))
    q.append("</svg>")
    return "\n".join(q)


def schema_glance():
    q = sheet(560, "The schema at a glance — 13 of its 33 tables")
    q.append(frame(16, 60, 200, 96, "Ledger", "stored"))
    q.append(box(30, 86, 172, 56, "ingest_run", "one row per fetch", "stored"))
    q.append(frame(16, 166, 200, 288, "Reference", "public"))
    q.append(box(30, 192, 172, 56, "publications", "one per source", "public"))
    q.append(box(30, 290, 172, 56, "reference_place", "as published", "public"))
    q.append(box(30, 388, 172, 56, "place", "ours, 3 origins", "public"))
    q.append(frame(318, 60, 506, 330, "Product", "product"))
    q.append(box(334, 86, 190, 56, "circle", "the table", "product"))
    q.append(box(616, 86, 190, 56, "member", "a seat, a nickname", "product"))
    q.append(box(334, 166, 190, 56, "round", "at most one open", "product"))
    q.append(box(334, 246, 190, 56, "proposal", "the pool", "product"))
    q.append(box(616, 246, 190, 56, "trip", "where they went", "product"))
    q.append(box(334, 326, 190, 56, "weight_contribution", "one row per reason", "product"))
    q.append(box(616, 326, 190, 56, "preference", "append-only", "product"))
    q.append(frame(236, 418, 500, 130, "Weather", "weather"))
    q.append(box(252, 450, 220, 56, "forecast_reading", "township · hour", "weather"))
    q.append(box(500, 450, 220, 56, "observation_reading", "station · hour", "weather"))
    q.append(line([(116, 142), (116, 188)]))
    q.append(line([(116, 248), (116, 286)]))
    q.append(line([(116, 346), (116, 384)]))
    q.append(line([(202, 404), (226, 404), (226, 274), (330, 274)]))
    q.append(line([(524, 114), (612, 114)]))
    q.append(line([(429, 142), (429, 162)]))
    q.append(line([(429, 222), (429, 242)]))
    q.append(line([(429, 302), (429, 322)]))
    q.append(line([(524, 346), (570, 346), (570, 274), (612, 274)]))
    q.append(line([(524, 362), (612, 362)]))
    q.append(line([(400, 382), (400, 446)]))
    q.append(line([(470, 382), (470, 410), (610, 410), (610, 446)]))
    q.append("</svg>")
    return "\n".join(q)


def name_ladder():
    q = sheet(690, "How a restaurant gets the name you would recognise")
    q.append(text(20, 60, "Three public sources, one ladder. The highest rung that exists for a site wins:", BODY, W_BODY, MUTED, "start"))
    q.append(text(20, 78, "nothing is invented, and the registered name is always there as the floor.", BODY, W_BODY, MUTED, "start"))
    q.append(frame(20, 104, 270, 340, "What the city publishes", "public"))
    q.append(frame(540, 104, 280, 340, "What a person reads, best rung first", "product"))
    rows = ((136, "餐飲衛生分級評核", "one row per shopfront", "the sign", "摩斯漢堡-南港環球店", "the shop's own sign"),
            (236, "臺北市食材登錄平台", "brand ↔ company", "the brand", "摩斯漢堡", "the brand behind the company"),
            (336, "食品業者登錄", "the registered site", "the registered name", "安心食品服務股份有限公司",
             "the name on the register"))
    for y, src, cap, rung, example, label in rows:
        q.append(box(36, y, 238, 64, src, cap, "public"))
        q.append(box(556, y, 248, 64, rung, example, "product"))
        q.append(line([(274, y + 32), (552, y + 32)], label, (413, y + 24)))
    q.append(line([(680, 200), (680, 232)], dashed=True))
    q.append(line([(680, 300), (680, 332)], dashed=True))
    q.append(text(690, 222, "none? falls to", BODY, W_LABEL, MUTED, "start"))
    q.append(text(690, 322, "none? falls to", BODY, W_LABEL, MUTED, "start"))
    y = notes(q, 480, "Why three rungs and not one", [
        "A register knows 安心食品服務股份有限公司; a hungry person knows 摩斯漢堡",
        "No sign on file falls to the brand; no brand falls to the registered name",
        "A branch sign is the only name that tells two shops of one chain apart",
        "Every rung comes from a published source; no name here is written by us"])
    notes(q, y, "When two branches share one name", [
        "Sign-less sites of one company get the district, road and section in brackets",
        "Same road, same section: then the house number, and only then"])
    q.append("</svg>")
    return "\n".join(q)


def evaluation_flow():
    q = sheet(512, "Up to You — how a classifier candidate is scored")
    q.append(box(20, 70, 240, 64, "testset_v3.json", "200 rows · 13 values · frozen", "stored"))
    q.append(box(560, 70, 260, 64, "four candidates", "gemma · llama · qwen · qwen7b", "alert"))
    q.append(box(560, 190, 260, 64, "round_<name>.json", "one per candidate", "stored"))
    q.append(box(20, 190, 240, 64, "score → report.md", "per layer, per value", "stored"))
    q.append(line([(260, 102), (556, 102)], "the same 200 rows", (408, 94)))
    q.append(line([(690, 134), (690, 186)], "one round each", (700, 166), anchor="start"))
    q.append(line([(560, 222), (264, 222)], "scored, never re-run", (412, 214)))
    y = notes(q, 300, "The v7 table, as measured", [
        "qwen7b 72.0 · gemma2:2b 71.0 · llama3.2:3b 70.5 · qwen2.5:3b 65.5",
        "The 7B did not move while every small model gained 5–9: a 10.5-point gap became 1.0, inside the band"])
    notes(q, y, "What makes two numbers comparable", [
        "A round file names its own test set; read that field before comparing anything",
        "The crib: labelled examples handed to the model (example_embedding, pgvector, k=5, leave-one-out)",
        "A prompt or label change makes the crib stale, and a round refuses a stale crib",
        "gemini is the hosted baseline: host-side only, and --rag is refused (the crib is the answer key)"])
    q.append("</svg>")
    return "\n".join(q)


PICTURES = {"etl-flow": etl_flow, "schema-glance": schema_glance,
            "name-ladder": name_ladder, "evaluation-flow": evaluation_flow}


def draw(name):
    """One picture's SVG text, and the labels drawn into it."""
    _labels.clear()
    svg = PICTURES[name]()
    return svg, list(_labels)


# === Rasterising ====================================================================================

def rasterise(svg_path, png_path):
    """SVG to PNG at 2x in Chromium: the sheet's own size as the viewport, the CJK face as every family.

    A fontconfig file written for this run maps the generic family and each family the texts name to
    the font in `UPTO_DIAGRAM_FONT`, so Latin and Chinese set in one face and no width depends on what
    the machine happens to have; without it the Chinese labels rasterise as empty boxes.
    """
    import re
    import tempfile
    font = os.environ.get("UPTO_DIAGRAM_FONT")
    if not font or not pathlib.Path(font).is_file():
        sys.exit("--png needs UPTO_DIAGRAM_FONT set to a Noto Sans TC font file; without it the "
                 "Chinese labels rasterise as empty boxes")
    from playwright.sync_api import sync_playwright
    svg = svg_path.read_text(encoding="utf-8")
    w, h = (int(v) for v in re.search(r'width="(\d+)" height="(\d+)"', svg).groups())
    with tempfile.TemporaryDirectory() as tmp:
        aliases = "".join(f'<alias binding="strong"><family>{f}</family><prefer><family>{CJK}</family></prefer></alias>'
                          for f in FAMILY)
        conf = pathlib.Path(tmp) / "fonts.conf"
        conf.write_text(f'<?xml version="1.0"?><fontconfig><cachedir>{tmp}</cachedir>'
                        f'<dir>{pathlib.Path(font).resolve().parent}</dir>{aliases}</fontconfig>')
        with sync_playwright() as pw:
            browser = pw.chromium.launch(env={**os.environ, "FONTCONFIG_FILE": str(conf)})
            pg = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=2)
            pg.goto(svg_path.resolve().as_uri())
            pg.wait_for_timeout(300)
            pg.screenshot(path=str(png_path))
            browser.close()


def main(argv):
    if "--labels" in argv:
        print(json.dumps({n: [{"text": t, "source": f"docs/diagrams/{n}.json"} for t in draw(n)[1]]
                          for n in PICTURES}, ensure_ascii=False, indent=1))
        return 0
    stale = []
    for name in PICTURES:
        svg = draw(name)[0]
        path = HERE / f"{name}.readme.svg"
        if "--check" in argv:
            if not path.is_file() or path.read_text(encoding="utf-8") != svg:
                stale.append(path.name)
            continue
        path.write_text(svg, encoding="utf-8")
        print(f"{path.name}: drawn")
        if "--png" in argv:
            rasterise(path, HERE / f"{name}.png")
            print(f"{name}.png: rasterised at 2x")
    if "--check" in argv:
        for s in stale:
            print(f"stale: {s} differs from what draw.py draws")
        print(f"draw.py --check: {len(PICTURES) - len(stale)} of {len(PICTURES)} pictures match")
        return 1 if stale else 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
