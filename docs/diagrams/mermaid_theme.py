#!/usr/bin/env python3
"""Print mermaid-cli's `-c` config for the ER diagrams, derived from `style.json`.

The README pictures and the ER diagrams share one look, and `style.json` (design tokens, W3C
Design Tokens Format 2025.10) is where it is decided. Mermaid does not read tokens, so this maps
the few it needs onto mermaid's `base` theme, the one theme whose variables are all honoured:

- an entity is the colour key's "stored" meaning (the database): its tint fills the box, its
  border draws the edge;
- text is `color.ink`, relationship lines `color.muted`, the sheet `color.background`;
- attribute rows alternate between the background and `color.fill`;
- the font is `font.family`, at `font.size.body`.

    python3 docs/diagrams/mermaid_theme.py [style.json] > config.json

Standard library only. A token missing from style.json stops it with the token's path, so a
renamed token cannot quietly fall back to mermaid's own defaults.
"""

import json
import os
import sys


def token(tokens, path):
    node = tokens
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            sys.exit("mermaid_theme: style.json has no {}".format(path))
        node = node[part]
    return node["$value"]


def hex_colour(tokens, path):
    return token(tokens, path)["hex"]


def px(tokens, path):
    value = token(tokens, path)
    if value.get("unit") != "px":
        sys.exit("mermaid_theme: {} is not in px".format(path))
    return "{:g}px".format(value["value"])


def config(tokens):
    family = token(tokens, "font.family")
    family = family if isinstance(family, str) else ", ".join(
        '"{}"'.format(f) if " " in f else f for f in family)
    ink, muted = hex_colour(tokens, "color.ink"), hex_colour(tokens, "color.muted")
    return {
        "theme": "base",
        "themeVariables": {
            "background": hex_colour(tokens, "color.background"),
            "primaryColor": hex_colour(tokens, "color.key.stored.tint"),
            "primaryBorderColor": hex_colour(tokens, "color.key.stored.border"),
            "primaryTextColor": ink,
            "textColor": ink,
            "lineColor": muted,
            "attributeBackgroundColorOdd": hex_colour(tokens, "color.background"),
            "attributeBackgroundColorEven": hex_colour(tokens, "color.fill"),
            "fontFamily": family,
            "fontSize": px(tokens, "font.size.body"),
        },
    }


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "style.json")
    with open(path, encoding="utf-8") as f:
        print(json.dumps(config(json.load(f)), indent=2))


if __name__ == "__main__":
    main()
