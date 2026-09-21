#!/usr/bin/env python3
"""
tokenkit - brand-agnostic design-token toolkit (Python 3.8+, stdlib only).

Subcommands
  ingest    CSS or Figma variables JSON  ->  model.json (normalized)
  audit     model.json  ->  audit.json + audit.md (structure, WCAG 2.2 AA, AI-readiness)
  generate  model.json  ->  tokens.css + tokens.manifest.json (+ generate-log.json)

Run `python3 tokenkit.py <cmd> -h` for options.
"""
import argparse
import colorsys
import datetime
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict

VERSION = "0.2.0"

# ----------------------------------------------------------------------------
# Color helpers
# ----------------------------------------------------------------------------

NAMED = {"black": "#000000", "white": "#ffffff", "transparent": "#00000000"}


def _clamp(x):
    return max(0.0, min(1.0, x))


def parse_color(s):
    """Return (r,g,b,a) floats 0..1 or None."""
    if isinstance(s, dict) and {"r", "g", "b"} <= set(s):
        return (float(s["r"]), float(s["g"]), float(s["b"]), float(s.get("a", 1)))
    if not isinstance(s, str):
        return None
    t = s.strip().lower()
    if t in NAMED:
        t = NAMED[t]
    m = re.fullmatch(r"#([0-9a-f]{3,8})", t)
    if m:
        h = m.group(1)
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h)
        if len(h) not in (6, 8):
            return None
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
        a = int(h[6:8], 16) / 255 if len(h) == 8 else 1.0
        return (r, g, b, a)
    m = re.fullmatch(r"(rgba?|hsla?)\((.*)\)", t)
    if not m:
        return None
    fn, body = m.groups()
    parts = [p for p in re.split(r"[\s,/]+", body.strip()) if p]
    if len(parts) < 3:
        return None

    def num(p, scale):
        if p.endswith("%"):
            return float(p[:-1]) / 100
        return float(p) / scale

    try:
        a = num(parts[3], 1) if len(parts) > 3 else 1.0
        if fn.startswith("rgb"):
            r, g, b = (num(p, 255) for p in parts[:3])
        else:
            hdeg = float(parts[0].replace("deg", ""))
            sat, lig = num(parts[1], 100), num(parts[2], 100)
            r, g, b = colorsys.hls_to_rgb((hdeg % 360) / 360, lig, sat)
    except ValueError:
        return None
    return (_clamp(r), _clamp(g), _clamp(b), _clamp(a))


def to_hex(c):
    r, g, b, a = c
    h = "#" + "".join("%02x" % round(_clamp(x) * 255) for x in (r, g, b))
    if round(a * 255) < 255:
        h += "%02x" % round(_clamp(a) * 255)
    return h


def _lin(u):
    return u / 12.92 if u <= 0.04045 else ((u + 0.055) / 1.055) ** 2.4


def luminance(c):
    r, g, b = c[:3]
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def composite(fg, bg):
    a = fg[3]
    return tuple(fg[i] * a + bg[i] * (1 - a) for i in range(3)) + (1.0,)


def contrast(fg, bg, backdrop=(1, 1, 1, 1)):
    bg = composite(bg, backdrop) if bg[3] < 1 else bg
    fg = composite(fg, bg) if fg[3] < 1 else fg
    l1, l2 = luminance(fg), luminance(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def apca_lc(fg, bg, backdrop=(1, 1, 1, 1)):
    """APCA-W3 0.0.98G Lc (WCAG 3 draft candidate; informative only). Positive = dark on light."""
    bg = composite(bg, backdrop) if bg[3] < 1 else bg
    fg = composite(fg, bg) if fg[3] < 1 else fg

    def y(c):
        v = 0.2126729 * c[0] ** 2.4 + 0.7151522 * c[1] ** 2.4 + 0.0721750 * c[2] ** 2.4
        return v + (0.022 - v) ** 1.414 if v < 0.022 else v

    yt, yb = y(fg), y(bg)
    if abs(yb - yt) < 0.0005:
        return 0.0
    if yb > yt:
        sapc = (yb ** 0.56 - yt ** 0.57) * 1.14
        out = 0.0 if sapc < 0.1 else sapc - 0.027
    else:
        sapc = (yb ** 0.65 - yt ** 0.62) * 1.14
        out = 0.0 if sapc > -0.1 else sapc + 0.027
    return out * 100


APCA_MIN = {"text": 60, "heading": 45, "non-text": 30}


def hls(c):
    return colorsys.rgb_to_hls(*c[:3])  # h 0..1, l, s


def chroma(c):
    return max(c[:3]) - min(c[:3])


# ----------------------------------------------------------------------------
# Naming helpers
# ----------------------------------------------------------------------------

HUES = {"red", "blue", "green", "yellow", "orange", "purple", "violet", "pink", "grey", "gray",
        "teal", "cyan", "magenta", "brown", "black", "white", "lime", "indigo", "amber", "rose",
        "emerald", "sky", "slate", "zinc", "stone", "neutral"}
STATES = {"hover", "hovered", "pressed", "active", "selected", "focus", "focused", "disabled",
          "visited", "dragged", "checked"}
ROLE_WORDS = {
    "focus": {"focus", "ring", "focusring"},
    "border": {"border", "outline", "stroke", "divider", "separator"},
    "icon": {"icon", "icons"},
    "text": {"text", "foreground", "fg", "content", "label", "heading", "body", "title", "copy"},
    "bg": {"surface", "background", "bg", "canvas", "container", "fill", "layer", "backdrop", "page"},
}
SCRIM_WORDS = {"scrim", "overlay", "shadow"}


def slug(s):
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", str(s))
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s or "x"


def css_var_for(name):
    return "--" + slug(name.replace("/", "-"))


def segments(name):
    n = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", name).lower()
    return [p for p in re.split(r"[/\-_. ]+", n) if p]


def last_seg(name):
    return name.split("/")[-1].strip()


def on_target(name):
    """'text/on-primary' -> 'primary'; 'onSurface' -> 'surface'."""
    ls = last_seg(name)
    m = re.match(r"^on[-_ ]?(.+)$", ls, re.I)
    if m and (ls[2:3] in "-_ " or ls[2:3].isupper()):
        return slug(m.group(1))
    parts = name.lower().split("/")
    if "on" in parts[:-1]:
        return slug("-".join(parts[parts.index("on") + 1:]))
    return None


def role_of(name):
    segs = set(segments(name))
    if on_target(name):
        return "text" if not segs & ROLE_WORDS["icon"] else "icon"
    for r in ("focus", "border", "icon", "text", "bg"):
        if segs & ROLE_WORDS[r]:
            return r
    return None


def float_kind(name):
    n = "-".join(segments(name))
    rules = [
        ("font-weight", r"weight"), ("line-height", r"line-height|leading"),
        ("letter-spacing", r"letter-spacing|tracking"), ("font-size", r"font-size|text-size|font-.*size|typography.*size|^size-(xs|sm|md|lg|xl)"),
        ("radius", r"radius|corner|rounded"), ("border-width", r"border-width|stroke-width|^border-\d"),
        ("opacity", r"opacity|alpha"), ("z-index", r"z-index|zindex|^z-|elevation-z"),
        ("duration", r"duration|delay|motion-time"), ("spacing", r"spacing|space|gap|padding|margin|inset|gutter"),
        ("size", r"size|width|height|target|icon"),
    ]
    for kind, pat in rules:
        if re.search(pat, n):
            return kind
    return "number"


UNITLESS = {"font-weight", "opacity", "z-index", "number"}


# ----------------------------------------------------------------------------
# Model
# ----------------------------------------------------------------------------

TIER_ORDER = {"primitive": 0, "alias": 1, "other": 1, "mapped": 2, "responsive": 2}


def new_model(kind, path):
    return {"format": "tokenkit/model@1", "source": {"kind": kind, "file": os.path.basename(path) if path else None},
            "collections": [], "tokens": []}


def col_by_name(model):
    return {c["name"]: c for c in model["collections"]}


def tok_index(model):
    return {t["key"]: t for t in model["tokens"]}


def ref_of(t):
    return "%s::%s" % (t["collection"], t["name"])


def guess_tier_from_name(name):
    n = name.lower()
    if re.search(r"primitiv|brand|base|core|palette|foundation|global|raw", n):
        return "primitive"
    if re.search(r"alias|semantic|ramp", n):
        return "alias"
    if re.search(r"mapped|theme|mode|scheme|color", n):
        return "mapped"
    if re.search(r"responsive|breakpoint|device|viewport|layout|density", n):
        return "responsive"
    return None


def infer_tiers(model):
    toks_by_col = defaultdict(list)
    for t in model["tokens"]:
        toks_by_col[t["collection"]].append(t)
    for c in model["collections"]:
        if c.get("tier"):
            continue
        ts = toks_by_col[c["name"]]
        vals = [v for t in ts for v in t["values"].values()]
        lit = sum(1 for v in vals if "value" in v)
        guess = guess_tier_from_name(c["name"])
        if len(c["modes"]) > 1:
            colors = sum(1 for t in ts if t["type"] == "COLOR")
            c["tier"] = guess if guess in ("mapped", "responsive") else ("mapped" if colors >= len(ts) / 2 else "responsive")
        elif guess:
            c["tier"] = guess
        elif vals and lit == len(vals):
            c["tier"] = "primitive"
        else:
            c["tier"] = "alias"


# ----------------------------------------------------------------------------
# Ingest: Figma
# ----------------------------------------------------------------------------

def ingest_figma(data, path):
    model = new_model("figma", path)
    if "meta" in data:  # REST API GET /v1/files/:key/variables/local
        cols = list(data["meta"].get("variableCollections", {}).values())
        vars_ = list(data["meta"].get("variables", {}).values())
    else:  # tokenkit / plugin / use_figma export
        cols, vars_ = data.get("collections", []), data.get("variables", [])
    model["source"]["fileName"] = data.get("fileName")
    col_map = {}
    for c in cols:
        if c.get("remote"):
            continue
        modes = [{"name": m["name"], "figmaId": m.get("modeId") or m.get("id"), "selector": None} for m in c["modes"]]
        default_id = c.get("defaultModeId") or modes[0]["figmaId"]
        modes.sort(key=lambda m: m["figmaId"] != default_id)  # default first
        col = {"name": c["name"], "figmaId": c["id"], "tier": None, "modes": modes}
        col_map[c["id"]] = col
        model["collections"].append(col)
    for v in vars_:
        col = col_map.get(v.get("variableCollectionId"))
        if not col or v.get("remote"):
            continue
        mode_name = {m["figmaId"]: m["name"] for m in col["modes"]}
        values = {}
        for mid, val in (v.get("valuesByMode") or {}).items():
            mname = mode_name.get(mid)
            if mname is None:
                continue
            if isinstance(val, dict) and val.get("type") == "VARIABLE_ALIAS":
                values[mname] = {"alias": val["id"]}
            elif v["resolvedType"] == "COLOR":
                values[mname] = {"value": to_hex(parse_color(val))}
            else:
                values[mname] = {"value": val}
        cs = v.get("codeSyntax") or {}
        model["tokens"].append({
            "key": v["id"], "name": v["name"], "collection": col["name"], "figmaId": v["id"],
            "type": v["resolvedType"], "scopes": v.get("scopes"), "description": v.get("description") or "",
            "codeSyntax": cs, "cssVar": None, "values": values,
            "hidden": bool(v.get("hiddenFromPublishing")),
        })
    keys = {t["key"] for t in model["tokens"]}
    for t in model["tokens"]:
        for m, v in t["values"].items():
            if "alias" in v and v["alias"] not in keys:
                v["external"] = True
    infer_tiers(model)
    assign_css_vars(model)
    return model


# ----------------------------------------------------------------------------
# Ingest: CSS
# ----------------------------------------------------------------------------

def parse_css(text):
    """Yield dicts {media, selector, annot, decls:[(prop, value)]}."""
    out, stack, buf, annot_pending = [], [], "", None
    pos = 0
    tok_re = re.compile(r"/\*.*?\*/|[{};]", re.S)
    for m in tok_re.finditer(text):
        buf += text[pos:m.start()]
        pos = m.end()
        tk = m.group(0)
        if tk.startswith("/*"):
            if "@collection" in tk:
                annot_pending = dict((k, v.strip()) for k, v in re.findall(r"@(\w+)\s+([^@*]*)", tk))
            continue
        if tk == "{":
            prelude = buf.strip()
            buf = ""
            frame = {"prelude": prelude, "annot": annot_pending, "decls": []}
            if not prelude.startswith("@"):
                annot_pending = None
            stack.append(frame)
        elif tk == ";":
            if stack and not stack[-1]["prelude"].startswith("@"):
                d = buf.strip()
                if ":" in d:
                    p, v = d.split(":", 1)
                    stack[-1]["decls"].append((p.strip(), v.strip()))
            buf = ""
        else:  # }
            d = buf.strip()
            if stack and d and ":" in d and not stack[-1]["prelude"].startswith("@"):
                p, v = d.split(":", 1)
                stack[-1]["decls"].append((p.strip(), v.strip()))
            buf = ""
            if not stack:
                continue
            frame = stack.pop()
            if frame["prelude"].startswith("@"):
                continue
            media = " and ".join(f["prelude"] for f in stack if f["prelude"].startswith("@media"))
            annot = frame["annot"] or next((f["annot"] for f in reversed(stack) if f["annot"]), None)
            out.append({"media": media, "selector": frame["prelude"], "annot": annot, "decls": frame["decls"]})
    return out


def css_context(media, selector):
    """-> (family, mode_name, is_base)."""
    sels = [s.strip() for s in selector.split(",")]
    base = any(s in (":root", "html", ":host", "body") for s in sels) and not media
    theme_hint = None
    for s in sels:
        m = re.search(r"data-theme\s*=\s*['\"]?([\w-]+)", s) or re.search(r"\.(?:theme-)?(dark|light|dim|high-contrast)\b", s)
        if m:
            theme_hint = m.group(1)
    if base:
        return ("base", theme_hint, True)
    if media:
        if "prefers-color-scheme" in media:
            return ("theme", "dark" if "dark" in media else "light", False)
        mw = re.search(r"(max|min)-width\s*:\s*([\d.]+)(px|em|rem)?", media)
        if mw:
            return ("viewport", "%s-%s%s" % (mw.group(1), mw.group(2), mw.group(3) or "px"), False)
        return ("media", slug(media), False)
    if theme_hint:
        return ("theme", theme_hint, False)
    for s in sels:
        m = re.search(r"data-([\w-]+)\s*=\s*['\"]?([\w-]+)", s)
        if m:
            return (m.group(1), m.group(2), False)
    return ("selector", slug(selector), False)


def parse_css_value(raw):
    v = re.sub(r"\s*!important\s*$", "", raw.strip())
    m = re.fullmatch(r"var\(\s*(--[\w-]+)\s*(?:,\s*(.+))?\)", v)
    if m:
        return {"alias": m.group(1)}, None, ("fallback ignored" if m.group(2) else None)
    c = parse_color(v)
    if c:
        return {"value": to_hex(c)}, "COLOR", None
    m = re.fullmatch(r"(-?\d*\.?\d+)(px|rem|em)?", v)
    if m:
        n = float(m.group(1))
        note = None
        if m.group(2) in ("rem", "em"):
            n *= 16
            note = "%s converted to px (16px base)" % m.group(2)
        n = int(n) if n == int(n) else round(n, 4)
        return {"value": n}, "FLOAT", note
    complex_ = bool(re.search(r"\(", v))
    note = "expression not representable as a Figma variable" if complex_ else None
    m = re.fullmatch(r"'([^']*)'|\"([^\"]*)\"", v)
    return {"value": (m.group(1) or m.group(2) or "") if m else v}, "STRING", note


def looks_primitive(name):
    segs = segments(name)
    return bool(segs) and (segs[-1].isdigit() or bool(set(segs) & HUES))


def ingest_css(text, path, manifest=None):
    model = new_model("css", path)
    blocks = parse_css(text)
    man_tok = {t["cssVar"]: t for t in (manifest or {}).get("tokens", [])}
    man_col = {c["name"]: c for c in (manifest or {}).get("collections", [])}
    # var -> list of (collection, mode, selector, value)
    defs = defaultdict(list)
    base_theme_hint = None
    annotated = any(b["annot"] for b in blocks)
    for b in blocks:
        props = [(p, v) for p, v in b["decls"] if p.startswith("--")]
        if not props:
            continue
        sel_full = ("%s { %s }" % (b["media"], b["selector"])) if b["media"] else b["selector"]
        if annotated and b["annot"]:
            a = b["annot"]
            col, mode = a.get("collection"), re.sub(r"\s*\(default\)\s*$", "", a.get("mode", "Value"))
            for p, v in props:
                defs[p].append({"col": col, "tier": a.get("tier"), "mode": mode, "sel": sel_full, "raw": v, "default": "(default)" in a.get("mode", "")})
            continue
        fam, mode, is_base = css_context(b["media"], b["selector"])
        if is_base and mode:
            base_theme_hint = mode
        for p, v in props:
            defs[p].append({"fam": "base" if is_base else fam, "mode": mode, "sel": sel_full, "raw": v})

    cols = {}

    def get_col(name, tier):
        if name not in cols:
            mc = man_col.get(name, {})
            cols[name] = {"name": name, "figmaId": mc.get("figmaId"), "tier": tier or mc.get("tier"), "modes": []}
        return cols[name]

    def add_mode(col, mode, sel, default=False):
        for m in col["modes"]:
            if m["name"] == mode:
                return
        mid = next((mm.get("figmaId") for mm in man_col.get(col["name"], {}).get("modes", []) if mm["name"] == mode), None)
        entry = {"name": mode, "figmaId": mid, "selector": sel}
        col["modes"].insert(0, entry) if default else col["modes"].append(entry)

    order = list(defs)
    tokens = []
    if annotated:
        for var in order:
            ds = defs[var]
            col = get_col(ds[0]["col"], ds[0]["tier"])
            for d in ds:
                add_mode(col, d["mode"], d["sel"], d.get("default"))
            tokens.append((var, col["name"], [(d["mode"], d["raw"]) for d in ds]))
    else:
        literal_refd = set()
        for var, ds in defs.items():
            for d in ds:
                m = re.search(r"var\(\s*(--[\w-]+)", d["raw"])
                if m:
                    literal_refd.add(m.group(1))
        fam_modes = defaultdict(set)
        for var, ds in defs.items():
            for d in ds:
                if d["fam"] != "base":
                    fam_modes[d["fam"]].add(d["mode"])
        fam_names = {"theme": "Theme", "viewport": "Responsive"}
        for var, ds in defs.items():
            fams = [d["fam"] for d in ds if d["fam"] != "base"]
            if fams:
                fam = fams[0]
                cname = fam_names.get(fam, fam.replace("-", " ").title())
                tier = "responsive" if fam == "viewport" else "mapped"
                col = get_col(cname, tier)
                if fam == "theme":
                    base_name = base_theme_hint or ("light" if "dark" in fam_modes[fam] else "default")
                elif fam == "viewport":
                    base_name = "desktop" if any(m.startswith("max") for m in fam_modes[fam]) else "mobile"
                else:
                    base_name = "default"
                vals = []
                for d in ds:
                    if d["fam"] == "base":
                        add_mode(col, base_name, ":root", True)
                        vals.append((base_name, d["raw"]))
                    elif d["fam"] == fam:
                        add_mode(col, d["mode"], d["sel"])
                        vals.append((d["mode"], d["raw"]))
                tokens.append((var, cname, vals))
            else:
                raw = ds[-1]["raw"]
                is_ref = raw.strip().startswith("var(")
                if not is_ref and (var in literal_refd or looks_primitive(var[2:])):
                    col = get_col("Primitives", "primitive")
                else:
                    col = get_col("Semantic", "alias")
                add_mode(col, "Value", ":root", True)
                tokens.append((var, col["name"], [("Value", raw)]))
        # ensure default modes of family collections exist
        for c in cols.values():
            if c["tier"] in ("mapped", "responsive") and not any(m["selector"] == ":root" for m in c["modes"]):
                bn = base_theme_hint or "default"
                c["modes"].insert(0, {"name": bn, "figmaId": None, "selector": ":root"})

    model["collections"] = list(cols.values())
    for var, cname, vals in tokens:
        mt = man_tok.get(var, {})
        t = {"key": mt.get("figmaId") or "css:" + var, "name": mt.get("name") or var[2:].replace("-", "/"),
             "collection": cname, "figmaId": mt.get("figmaId"), "type": None, "scopes": mt.get("scopes"),
             "description": mt.get("description", ""), "codeSyntax": mt.get("codeSyntax") or {}, "cssVar": var,
             "values": {}, "notes": []}
        for mode, raw in vals:
            v, typ, note = parse_css_value(raw)
            t["values"][mode] = v
            if typ and not t["type"]:
                t["type"] = typ
            if note:
                t["notes"].append("%s: %s" % (mode, note))
        tokens_list = model["tokens"]
        tokens_list.append(t)
    # resolve alias keys (css var -> token key) and types
    by_var = {t["cssVar"]: t for t in model["tokens"]}
    for t in model["tokens"]:
        for v in t["values"].values():
            if "alias" in v:
                tgt = by_var.get(v["alias"])
                if tgt:
                    v["alias"] = tgt["key"]
                else:
                    v["external"] = True
    for _ in range(10):
        for t in model["tokens"]:
            if not t["type"]:
                for v in t["values"].values():
                    tgt = by_var.get(v.get("alias")) if v.get("external") else next((x for x in model["tokens"] if x["key"] == v.get("alias")), None)
                    if tgt and tgt["type"]:
                        t["type"] = tgt["type"]
                        break
    for t in model["tokens"]:
        t["type"] = t["type"] or "STRING"
    infer_tiers(model)
    return model


def assign_css_vars(model):
    for t in model["tokens"]:
        web = (t.get("codeSyntax") or {}).get("WEB", "")
        m = re.search(r"(--[\w-]+)", web or "")
        t["cssVar"] = t.get("cssVar") or (m.group(1) if m else css_var_for(t["name"]))


def ingest_manifest(man, path):
    model = new_model("manifest", path)
    model["collections"] = [{"name": c["name"], "figmaId": c.get("figmaId"), "tier": c.get("tier"),
                             "modes": [dict(m) for m in c["modes"]]} for c in man["collections"]]
    key_of = {}
    for t in man["tokens"]:
        key_of["%s::%s" % (t["collection"], t["name"])] = t.get("figmaId") or "css:" + t["cssVar"]
    for t in man["tokens"]:
        vals = {}
        for m, v in t["values"].items():
            if "alias" in v:
                a = v["alias"]
                vals[m] = {"alias": a.get("figmaId") or key_of.get("%s::%s" % (a["collection"], a["name"]), "css:" + a.get("cssVar", ""))}
            else:
                vals[m] = {"value": v["value"]}
        model["tokens"].append({"key": key_of["%s::%s" % (t["collection"], t["name"])], "name": t["name"],
                                "collection": t["collection"], "figmaId": t.get("figmaId"), "type": t["type"],
                                "scopes": t.get("scopes"), "description": t.get("description", ""),
                                "codeSyntax": t.get("codeSyntax") or {}, "cssVar": t["cssVar"], "values": vals})
    infer_tiers(model)
    return model


# ----------------------------------------------------------------------------
# Resolution
# ----------------------------------------------------------------------------

class Resolver:
    def __init__(self, model):
        self.m = model
        self.idx = tok_index(model)
        self.cols = col_by_name(model)

    def mode_for(self, tok, mode):
        modes = [m["name"] for m in self.cols[tok["collection"]]["modes"]]
        return mode if mode in modes else (modes[0] if modes else None)

    def resolve(self, key, mode, seen=()):
        """-> dict(value=..., chain=[keys], error=None|'missing'|'broken'|'cycle'|'external')"""
        tok = self.idx.get(key)
        if tok is None:
            return {"value": None, "chain": list(seen), "error": "broken"}
        if key in seen:
            return {"value": None, "chain": list(seen) + [key], "error": "cycle"}
        m = self.mode_for(tok, mode)
        entry = tok["values"].get(m)
        if entry is None:
            return {"value": None, "chain": list(seen) + [key], "error": "missing", "mode": m}
        if "alias" in entry:
            if entry.get("external"):
                return {"value": None, "chain": list(seen) + [key], "error": "external"}
            return self.resolve(entry["alias"], mode, tuple(seen) + (key,))
        return {"value": entry["value"], "chain": list(seen) + [key], "error": None}

    def color(self, key, mode):
        r = self.resolve(key, mode)
        return parse_color(r["value"]) if r["error"] is None else None


# ----------------------------------------------------------------------------
# Audit
# ----------------------------------------------------------------------------

def F(area, fid, severity, title, detail="", tokens=None, fix="decision"):
    return {"area": area, "id": fid, "severity": severity, "title": title, "detail": detail,
            "tokens": sorted(set(tokens or []))[:60], "count": len(set(tokens or [])), "fix": fix}


def eval_modes(res, *toks):
    names = []
    for t in toks:
        for m in res.cols[t["collection"]]["modes"]:
            if m["name"] not in names:
                names.append(m["name"])
    multi = [n for t in toks for n in [m["name"] for m in res.cols[t["collection"]]["modes"]] if len(res.cols[t["collection"]]["modes"]) > 1]
    return list(dict.fromkeys(multi)) or names[:1]


def audit_structure(model, res):
    out = []
    tiers = {c["name"]: c["tier"] for c in model["collections"]}
    present = set(tiers.values())
    idx = res.idx
    if "primitive" not in present:
        out.append(F("structure", "S1", "error", "No primitive layer", "Every value is defined directly in semantic tokens; there is no palette/scale to reference."))
    if not present & {"alias", "mapped", "responsive"}:
        out.append(F("structure", "S1b", "warning", "No semantic layer", "Only raw values exist; components would bind to primitives directly."))
    hard = defaultdict(list)
    for t in model["tokens"]:
        if tiers[t["collection"]] != "primitive" and any("value" in v for v in t["values"].values()):
            hard[t["type"]].append(ref_of(t))
    for typ, lst in hard.items():
        out.append(F("structure", "S2", "error" if typ == "COLOR" else "warning",
                     "Hardcoded %s values in semantic tokens" % typ.lower(),
                     "These tokens hold a raw value instead of referencing a primitive.", lst, fix="auto"))
    broken, cycles, external, missing, upward, skip, deep = [], [], [], [], [], [], []
    has_alias_tier = "alias" in present
    for t in model["tokens"]:
        col = res.cols[t["collection"]]
        for m in col["modes"]:
            if m["name"] not in t["values"]:
                missing.append("%s (%s)" % (ref_of(t), m["name"]))
        for mname, v in t["values"].items():
            if "alias" not in v:
                continue
            if v.get("external"):
                external.append(ref_of(t))
                continue
            tgt = idx.get(v["alias"])
            if not tgt:
                broken.append(ref_of(t))
                continue
            r = res.resolve(t["key"], mname)
            if r["error"] == "cycle":
                cycles.append(ref_of(t))
            if len(r["chain"]) > 4:
                deep.append(ref_of(t))
            ta, tb = TIER_ORDER[tiers[t["collection"]]], TIER_ORDER[tiers[tgt["collection"]]]
            if tb > ta:
                upward.append("%s -> %s" % (ref_of(t), ref_of(tgt)))
            if tiers[t["collection"]] in ("mapped", "responsive") and tiers[tgt["collection"]] == "primitive" and has_alias_tier and t["type"] == "COLOR":
                skip.append(ref_of(t))
    if broken:
        out.append(F("structure", "S4", "error", "Broken aliases", "Alias targets that do not exist.", broken))
    if cycles:
        out.append(F("structure", "S4b", "error", "Circular aliases", "", cycles))
    if external:
        out.append(F("structure", "S4c", "info", "Aliases to external libraries", "Targets live in another file/library and cannot be resolved here.", external))
    if missing:
        out.append(F("structure", "S5", "error", "Missing values per mode", "Token has no value in some mode of its collection.", missing))
    if upward:
        out.append(F("structure", "S3", "error", "Upward references", "A lower tier references a higher tier (e.g. primitive -> semantic). Breaks theming.", upward))
    if skip:
        out.append(F("structure", "S3b", "info", "Tier skipping", "Mapped tokens point at primitives directly although an alias tier exists.", skip))
    if deep:
        out.append(F("structure", "S10", "warning", "Alias chains deeper than 3", "", deep))
    # naming
    upper = [ref_of(t) for t in model["tokens"] if re.search(r"[A-Z]", t["name"])]
    spaces = [ref_of(t) for t in model["tokens"] if " " in t["name"]]
    style = Counter()
    per_style = defaultdict(list)
    for t in model["tokens"]:
        for s in t["name"].split("/"):
            st = "camel" if re.search(r"[a-z][A-Z]", s) else "snake" if "_" in s else "kebab" if "-" in s else None
            if st:
                style[st] += 1
                per_style[st].append(ref_of(t))
    if upper:
        out.append(F("structure", "S6a", "warning", "Uppercase in token names", "Mixed case makes names harder to map to code.", upper, fix="decision"))
    if spaces:
        out.append(F("structure", "S6b", "warning", "Spaces in token names", "", spaces))
    if len(style) > 1:
        dom = style.most_common(1)[0][0]
        odd = [x for st, l in per_style.items() if st != dom for x in l]
        out.append(F("structure", "S6c", "warning", "Mixed word separators (dominant: %s)" % dom, "", odd))
    seen_css = defaultdict(list)
    for t in model["tokens"]:
        seen_css[t["cssVar"]].append(ref_of(t))
    coll = [x for l in seen_css.values() if len(l) > 1 for x in l]
    if coll:
        out.append(F("structure", "S6d", "error", "CSS name collisions", "Different tokens map to the same CSS custom property.", coll))
    depth = defaultdict(set)
    for t in model["tokens"]:
        depth[(t["collection"], t["name"].split("/")[0])].add(t["name"].count("/") + 1)
    irregular = ["%s::%s/* depths %s" % (c, g, sorted(d)) for (c, g), d in depth.items() if len(d) > 2]
    if irregular:
        out.append(F("structure", "S6e", "info", "Irregular naming depth", "Groups whose tokens use more than two different path depths.", irregular))
    # ramps
    ramps = defaultdict(list)
    for t in model["tokens"]:
        if tiers[t["collection"]] == "primitive" and t["type"] == "COLOR" and last_seg(t["name"]).isdigit():
            ramps["%s::%s" % (t["collection"], t["name"].rsplit("/", 1)[0])].append(t)
    step_sets = Counter(tuple(sorted(int(last_seg(t["name"])) for t in ts)) for ts in ramps.values() if len(ts) > 3)
    if step_sets:
        canonical = set(step_sets.most_common(1)[0][0])
        gaps, nonmono = [], []
        for rname, ts in ramps.items():
            steps = {int(last_seg(t["name"])) for t in ts}
            miss = canonical - steps
            if len(ts) > 3 and miss:
                gaps.append("%s missing %s" % (rname, sorted(miss)))
            ls = [hls(res.color(t["key"], None) or (0, 0, 0, 1))[1] for t in sorted(ts, key=lambda x: int(last_seg(x["name"])))]
            diffs = [b - a for a, b in zip(ls, ls[1:]) if abs(b - a) > 0.005]
            if diffs and any(d > 0 for d in diffs) and any(d < 0 for d in diffs):
                nonmono.append(rname)
        if gaps:
            out.append(F("structure", "S7", "info", "Ramp gaps", "Ramps missing steps that most other ramps have.", gaps))
        if nonmono:
            out.append(F("structure", "S7b", "warning", "Non-monotonic ramps", "Lightness does not change in one direction along the steps.", nonmono))
    # duplicates among primitives
    by_val = defaultdict(list)
    for t in model["tokens"]:
        if tiers[t["collection"]] == "primitive":
            v = next(iter(t["values"].values()), {}).get("value")
            if v is not None:
                by_val[(t["type"], json.dumps(v))].append(ref_of(t))
    dups = ["%s = %s" % (json.loads(k[1]), ", ".join(v)) for k, v in by_val.items() if len(v) > 1 and k[0] == "COLOR"]
    if dups:
        out.append(F("structure", "S8", "warning", "Duplicate primitive colors", "Same value under several names.", dups))
    refd = {v["alias"] for t in model["tokens"] for v in t["values"].values() if "alias" in v}
    unused = [ref_of(t) for t in model["tokens"] if tiers[t["collection"]] == "primitive" and t["key"] not in refd]
    if unused and len(unused) < len([t for t in model["tokens"] if tiers[t["collection"]] == "primitive"]):
        out.append(F("structure", "S9", "info", "Unused primitives", "Not referenced by any semantic token (fine for palette completeness).", unused))
    return out


def semantic_colors(model):
    tiers = {c["name"]: c["tier"] for c in model["collections"]}
    return [t for t in model["tokens"] if t["type"] == "COLOR" and tiers[t["collection"]] != "primitive"]


def backdrop_for(mode):
    return (0, 0, 0, 1) if mode and re.search(r"dark|night|dim", mode, re.I) else (1, 1, 1, 1)


def audit_accessibility(model, res, pairs_file=None):
    sem = semantic_colors(model)
    checks, findings = [], []
    if not sem:
        findings.append(F("accessibility", "A0", "warning", "No semantic color tokens",
                          "Contrast pairs cannot be inferred from primitives alone. Provide a pairs file or add semantic tokens."))
        return findings, checks
    roles = {t["key"]: role_of(t["name"]) for t in sem}
    inverse = {t["key"] for t in sem if {"inverse", "inverted"} & set(segments(t["name"]))}

    def is_neutral(t):
        for m in eval_modes(res, t):
            c = res.color(t["key"], m)
            if c is None or chroma(c) > 0.1 or c[3] < 0.99:
                return False
        return True

    bgs = [t for t in sem if roles[t["key"]] == "bg" and not set(segments(t["name"])) & SCRIM_WORDS]
    neutral_bgs = [t for t in bgs if is_neutral(t) and t["key"] not in inverse
                   and not set(segments(t["name"])) & {"disabled", "inactive"}]
    by_last = defaultdict(list)
    for t in sem:
        if roles[t["key"]] not in ("text", "icon", "border", "focus"):
            by_last[slug(last_seg(t["name"]))].append(t)
        if roles[t["key"]] == "bg":
            by_last[slug("-".join(t["name"].split("/")[1:]) or t["name"])].append(t)

    def add_check(fg, bg, minimum, kind, note=""):
        for m in eval_modes(res, fg, bg):
            cf, cb = res.color(fg["key"], m), res.color(bg["key"], m)
            if cf is None or cb is None:
                continue
            r = contrast(cf, cb, backdrop_for(m))
            lc = apca_lc(cf, cb, backdrop_for(m))
            akind = "heading" if note.startswith("3:1") else ("text" if minimum >= 4.5 else "non-text")
            checks.append({"fg": ref_of(fg), "bg": ref_of(bg), "mode": m, "ratio": round(r, 2), "min": minimum,
                           "pass": r >= minimum - 1e-9, "kind": kind, "note": note,
                           "fgHex": to_hex(cf), "bgHex": to_hex(cb),
                           "apca": round(lc, 1), "apcaMin": APCA_MIN[akind], "apcaPass": abs(lc) >= APCA_MIN[akind]})

    paired_bg = set()
    for t in sem:
        role = roles[t["key"]]
        if role not in ("text", "icon", "border", "focus"):
            continue
        segs = set(segments(t["name"]))
        disabled = bool(segs & {"disabled", "inactive"})
        tgt = on_target(t["name"])
        parent = t["name"].rsplit("/", 1)[0] if "/" in t["name"] else None
        siblings = [b for b in bgs if parent and b["collection"] == t["collection"] and b["name"].rsplit("/", 1)[0] == parent] if not tgt else []
        if siblings and not disabled:
            for b in siblings:
                paired_bg.add(b["key"])
                add_check(t, b, {"text": 4.5}.get(role, 3.0), "on-pair")
            continue
        if tgt:
            partners = [b for b in by_last.get(tgt, []) if b["key"] != t["key"]]
            for b in partners:
                paired_bg.add(b["key"])
                add_check(t, b, 3.0 if role == "icon" else 4.5, "on-pair")
            continue
        if t["key"] in inverse:
            for b in [b for b in bgs if b["key"] in inverse]:
                add_check(t, b, 4.5 if role == "text" else 3.0, "inverse")
            continue
        if disabled:
            continue
        for b in neutral_bgs:
            if role == "text":
                heading = bool(segs & {"heading", "display", "headline", "large", "xl"})
                add_check(t, b, 4.5, "text", "3:1 suffices only for large text (>=24px or >=18.66px bold)" if heading else "")
            elif role == "icon":
                add_check(t, b, 3.0, "icon")
            elif role == "focus":
                add_check(t, b, 3.0, "focus")
            else:
                interactive = bool(segs & {"input", "control", "field", "interactive", "strong", "emphasis", "checkbox", "radio"})
                add_check(t, b, 3.0, "border" if interactive else "border-decorative",
                          "" if interactive else "decorative borders are exempt from 1.4.11; required if it is the only boundary of a control")
    if pairs_file:
        by_ref = {}
        for t in model["tokens"]:
            for k in (ref_of(t), t["name"], t["cssVar"]):
                by_ref[k] = t
        for p in pairs_file:
            fg, bg = by_ref.get(p["fg"]), by_ref.get(p["bg"])
            if fg and bg:
                add_check(fg, bg, float(p.get("min", 4.5)), "declared")
            else:
                findings.append(F("accessibility", "A9", "warning", "Declared pair not found", json.dumps(p)))
    fails = [c for c in checks if not c["pass"] and c["kind"] != "border-decorative"]
    deco = [c for c in checks if not c["pass"] and c["kind"] == "border-decorative"]
    for kind, sc, title in (("on-pair", "A1", "Foreground on its paired surface below AA"),
                            ("text", "A2", "Text on neutral surfaces below 4.5:1"),
                            ("inverse", "A2b", "Inverse text below AA"),
                            ("icon", "A3", "Icons below 3:1 (1.4.11)"),
                            ("focus", "A4", "Focus indicator below 3:1 (1.4.11)"),
                            ("border", "A5", "Interactive borders below 3:1 (1.4.11)"),
                            ("declared", "A6", "Declared pairs below minimum")):
        lst = [c for c in fails if c["kind"] == kind]
        if lst:
            findings.append(F("accessibility", sc, "error", title,
                              "; ".join("%s on %s [%s] %.2f<%.1f" % (c["fg"].split("::")[1], c["bg"].split("::")[1], c["mode"], c["ratio"], c["min"])
                                        for c in sorted(lst, key=lambda c: c["ratio"])[:12]),
                              [c["fg"] for c in lst]))
    if deco:
        findings.append(F("accessibility", "A5b", "info", "Decorative borders below 3:1",
                          "OK if purely decorative. Must reach 3:1 if it is the only visual boundary of an input or control.",
                          [c["fg"] for c in deco]))
    w3 = [c for c in checks if c["pass"] and not c["apcaPass"] and c["kind"] != "border-decorative"]
    if w3:
        findings.append(F("accessibility", "A12", "info", "Pass WCAG 2.2 but low APCA contrast (WCAG 3 draft preview)",
                          "Informative only: WCAG 3 is a Working Draft and its contrast method is not final. Lc shown with APCA guidance (text 60, large 45, non-text 30).",
                          [c["fg"] for c in w3]))
    sat_bgs = [b for b in bgs if b["key"] not in paired_bg and not is_neutral(b) and b["key"] not in inverse]
    if sat_bgs:
        findings.append(F("accessibility", "A7", "warning", "Colored surfaces without a paired foreground",
                          "Add an on-* token (e.g. text/on-<surface>) so contrast is guaranteed and testable.",
                          [ref_of(b) for b in sat_bgs]))
    if not any(roles[t["key"]] == "focus" for t in sem):
        findings.append(F("accessibility", "A4b", "warning", "No focus token", "Define a focus-ring color token and test it at 3:1 against every surface."))
    # state distinctness
    groups = defaultdict(list)
    for t in sem:
        segs = t["name"].split("/")
        base = "/".join(s for s in segs if slug(s) not in STATES and not any(slug(s).endswith("-" + st) for st in STATES))
        groups[(t["collection"], base)].append(t)
    collide = []
    for (col, base), ts in groups.items():
        if len(ts) < 2 or not any(set(segments(t["name"])) & STATES for t in ts):
            continue
        for i in range(len(ts)):
            for j in range(i + 1, len(ts)):
                a, b = ts[i], ts[j]
                if not (set(segments(a["name"])) & STATES or set(segments(b["name"])) & STATES):
                    continue
                modes = eval_modes(res, a, b)
                same = all(to_hex(res.color(a["key"], m) or (0, 0, 0, 0)) == to_hex(res.color(b["key"], m) or (1, 1, 1, 0)) for m in modes)
                if same:
                    collide.append("%s == %s" % (ref_of(a), ref_of(b)))
    if collide:
        findings.append(F("accessibility", "A8", "warning", "States that look identical",
                          "Different states resolve to the same color in every mode; users cannot tell them apart.", collide))
    # non-color
    small, target = [], []
    for t in model["tokens"]:
        if t["type"] != "FLOAT":
            continue
        k = float_kind(t["name"])
        for m in res.cols[t["collection"]]["modes"]:
            r = res.resolve(t["key"], m["name"])
            if not isinstance(r["value"], (int, float)):
                continue
            if k == "font-size" and r["value"] < 12:
                small.append("%s [%s] = %s" % (ref_of(t), m["name"], r["value"]))
            if re.search(r"target|touch|hit|control-height|min-size", "-".join(segments(t["name"]))) and r["value"] < 24:
                target.append("%s [%s] = %s" % (ref_of(t), m["name"], r["value"]))
    if small:
        findings.append(F("accessibility", "A10", "info", "Font sizes below 12px", "Not a WCAG failure but hurts legibility; check 1.4.4 resize behavior.", small))
    if target:
        findings.append(F("accessibility", "A11", "warning", "Target sizes below 24px (2.5.8)", "", target))
    return findings, checks


def suggest_fixes(model, res, checks):
    """For each failing fg/mode: nearest passing step in the same ramp, else minimal lightness shift."""
    tiers = {c["name"]: c["tier"] for c in model["collections"]}
    req = [c for c in checks if c["kind"] != "border-decorative"]
    by = defaultdict(list)
    for c in req:
        by[(c["fg"], c["mode"])].append(c)
    refs = {ref_of(t): t for t in model["tokens"]}
    out = []
    for fg, mode in sorted({(c["fg"], c["mode"]) for c in req if not c["pass"]}):
        t = refs[fg]
        r = res.resolve(t["key"], mode)
        if r["error"]:
            continue
        cur = parse_color(r["value"])
        prim = res.idx[r["chain"][-1]]
        bd = backdrop_for(mode)
        cs = by[(fg, mode)]
        need = [(parse_color(c["bgHex"]), c["min"]) for c in cs]

        def ok(col):
            return all(contrast(col, b, bd) >= mn - 1e-9 for b, mn in need)

        step_ref, step_hex = None, None
        if last_seg(prim["name"]).isdigit():
            ramp, step = prim["name"].rsplit("/", 1)[0], int(last_seg(prim["name"]))
            cands = sorted((p for p in model["tokens"] if p["collection"] == prim["collection"] and "/" in p["name"]
                            and p["name"].rsplit("/", 1)[0] == ramp and last_seg(p["name"]).isdigit()),
                           key=lambda p: abs(int(last_seg(p["name"])) - step))
            for p in cands:
                col = res.color(p["key"], None)
                if col and ok(col):
                    mirror = next((a for a in model["tokens"] if tiers[a["collection"]] == "alias"
                                   and any(v.get("alias") == p["key"] for v in a["values"].values())), None)
                    use = mirror if (mirror and tiers[t["collection"]] in ("mapped", "responsive")) else p
                    step_ref, step_hex = ref_of(use), to_hex(col)
                    break
        h, l, sat = hls(cur)
        shift = None
        for i in range(1, 401):
            for nl in (l - i / 400, l + i / 400):
                if 0 <= nl <= 1:
                    col = colorsys.hls_to_rgb(h, nl, sat) + (cur[3],)
                    if ok(col):
                        shift = col
                        break
            if shift:
                break
        worst = min(cs, key=lambda c: c["ratio"])
        s = {"token": fg, "mode": mode, "current": to_hex(cur), "worst": "%s %.2f<%.1f" % (worst["bg"], worst["ratio"], worst["min"]),
             "nearestStep": step_ref, "nearestStepHex": step_hex, "minimalShift": to_hex(shift) if shift else None}
        if step_ref:
            s["change"] = {"op": "alias", "token": fg, "mode": mode, "to": step_ref}
        elif shift:
            s["change"] = {"op": "set", "token": fg, "mode": mode, "value": to_hex(shift)}
        out.append(s)
    return out


def audit_ai(model, res, structure, a11y):
    tiers = {c["name"]: c["tier"] for c in model["collections"]}
    toks = model["tokens"]
    sem = [t for t in toks if tiers[t["collection"]] != "primitive"]
    crit = []

    def pct(n, d):
        return 100.0 if d == 0 else round(100.0 * n / d, 1)

    sem_vals = [v for t in sem for v in t["values"].values()]
    crit.append({"id": "AI1", "name": "Semantic tokens reference primitives", "weight": 20,
                 "score": pct(sum(1 for v in sem_vals if "alias" in v), len(sem_vals)) if sem else 0,
                 "why": "Agents can reason about intent (surface/danger) and trace it to a value."})
    bad = {x for f in structure if f["id"] in ("S6a", "S6b", "S6c", "S6d") for x in f["tokens"]}
    crit.append({"id": "AI2", "name": "Predictable, code-safe naming", "weight": 15,
                 "score": pct(len(toks) - len(bad), len(toks)),
                 "why": "One separator, lowercase, no spaces: names map 1:1 to CSS and code."})
    crit.append({"id": "AI3", "name": "Descriptions on semantic tokens", "weight": 15,
                 "score": pct(sum(1 for t in sem if (t.get("description") or "").strip()), len(sem)),
                 "why": "Descriptions tell an agent when to use a token, not only what it is."})
    has_scopes = model["source"]["kind"] in ("figma", "manifest") and any(t.get("scopes") is not None for t in toks)
    if has_scopes:
        crit.append({"id": "AI4", "name": "Figma scopes set (not ALL_SCOPES)", "weight": 10,
                     "score": pct(sum(1 for t in toks if t.get("scopes") is not None and t["scopes"] != ["ALL_SCOPES"]), len(toks)),
                     "why": "Scopes restrict where a token may be applied, so generated designs bind correctly."})
    crit.append({"id": "AI5", "name": "Explicit code syntax / CSS parity", "weight": 10,
                 "score": pct(sum(1 for t in toks if (t.get("codeSyntax") or {}).get("WEB")), len(toks)) if model["source"]["kind"] != "css" else 100.0,
                 "why": "Figma WEB code syntax lets Dev Mode and MCP return the exact CSS variable."})
    leak = []
    for t in sem:
        segs = set(segments(t["name"]))
        if tiers[t["collection"]] in ("mapped", "responsive") and (segs & HUES or any(s.isdigit() for s in segs)):
            leak.append(ref_of(t))
        elif tiers[t["collection"]] == "alias" and segs & HUES and t["type"] == "COLOR":
            leak.append(ref_of(t))
    positional = [ref_of(t) for t in sem if role_of(t["name"]) == "bg" and set(segments(t["name"])) & {"secondary", "tertiary", "quaternary"}]
    crit.append({"id": "AI6", "name": "Role-based (not value-based) semantic names", "weight": 10,
                 "score": pct(len(sem) - len(set(leak)), len(sem)) if sem else 0,
                 "why": "Names like surface/danger survive a rebrand; names like surface/red do not.", "tokens": leak})
    integ = sum(f["count"] for f in structure if f["id"] in ("S4", "S4b", "S5", "S3"))
    crit.append({"id": "AI7", "name": "Integrity (no broken, circular, missing or upward refs)", "weight": 10,
                 "score": max(0.0, 100.0 - 10 * integ), "why": "Any unresolved value forces an agent to guess."})
    unpaired = next((f["count"] for f in a11y if f["id"] == "A7"), 0)
    bgs = [t for t in sem if role_of(t["name"]) == "bg"]
    crit.append({"id": "AI8", "name": "Explicit foreground/background pairs", "weight": 10,
                 "score": pct(len(bgs) - unpaired, len(bgs)) if bgs else 0,
                 "why": "on-* tokens let an agent pick an accessible text color without computing contrast."})
    total_w = sum(c["weight"] for c in crit)
    score = round(sum(c["score"] * c["weight"] for c in crit) / total_w)
    extra = []
    if positional:
        extra.append(F("ai", "AI6b", "info", "Positional surface names", "secondary/tertiary say nothing about purpose; prefer a role (e.g. surface/brand, surface/accent).", positional))
    return {"score": score, "criteria": crit}, extra


def score_structure(findings):
    s = 100
    for f in findings:
        s -= {"error": 15, "warning": 5, "info": 1}[f["severity"]]
    return max(0, s)


def cmd_audit(a):
    model = json.load(open(a.model))
    res = Resolver(model)
    pairs = json.load(open(a.pairs)) if a.pairs else None
    st = audit_structure(model, res)
    ac, checks = audit_accessibility(model, res, pairs)
    ai, ai_extra = audit_ai(model, res, st, ac)
    required = [c for c in checks if c["kind"] != "border-decorative"]
    a11y_score = round(100.0 * sum(1 for c in required if c["pass"]) / len(required)) if required else None
    tiers = Counter(c["tier"] for c in model["collections"])
    summary = {
        "source": model["source"], "generatedAt": datetime.datetime.now().isoformat(timespec="seconds"),
        "counts": {"collections": len(model["collections"]), "tokens": len(model["tokens"]),
                   "byType": dict(Counter(t["type"] for t in model["tokens"])),
                   "byTier": {c["name"]: c["tier"] for c in model["collections"]},
                   "modes": {c["name"]: [m["name"] for m in c["modes"]] for c in model["collections"]}},
        "scores": {"structure": score_structure(st), "accessibility": a11y_score, "aiReady": ai["score"]},
        "contrastChecks": {"total": len(required), "failed": sum(1 for c in required if not c["pass"])},
    }
    out = {"summary": summary, "findings": st + ac + ai_extra, "ai": ai, "contrast": checks,
           "suggestions": suggest_fixes(model, res, checks)}
    os.makedirs(a.out, exist_ok=True)
    json.dump(out, open(os.path.join(a.out, "audit.json"), "w"), indent=2, ensure_ascii=False)
    open(os.path.join(a.out, "audit.md"), "w").write(render_audit_md(out))
    print(json.dumps(summary["scores"]), file=sys.stderr)
    print(os.path.join(a.out, "audit.json"))


def render_audit_md(o):
    s = o["summary"]
    L = ["# Token audit (full findings)", "",
         "Source: %s `%s`  |  Tokens: %d in %d collections  |  Generated %s" % (
             s["source"]["kind"], s["source"].get("file"), s["counts"]["tokens"], s["counts"]["collections"], s["generatedAt"]), "",
         "| Score | Value |", "|---|---|"]
    for k, v in s["scores"].items():
        L.append("| %s | %s |" % (k, "n/a" if v is None else "%s/100" % v))
    L += ["", "Collections: " + ", ".join("%s (%s; %s)" % (n, t, "/".join(s["counts"]["modes"][n])) for n, t in s["counts"]["byTier"].items()), ""]
    for area, label in (("structure", "Structure"), ("accessibility", "Accessibility (WCAG 2.2 AA)"), ("ai", "AI-readiness")):
        fs = [f for f in o["findings"] if f["area"] == area]
        L += ["## %s" % label, ""]
        if not fs:
            L += ["No findings.", ""]
        for f in sorted(fs, key=lambda f: ["error", "warning", "info"].index(f["severity"])):
            L.append("- **[%s] %s %s** (%d)%s" % (f["severity"], f["id"], f["title"], f["count"], " - auto-fixable" if f["fix"] == "auto" else ""))
            if f["detail"]:
                L.append("  - %s" % f["detail"])
            if f["tokens"]:
                L.append("  - " + ", ".join("`%s`" % x for x in f["tokens"][:15]) + (" ..." if f["count"] > 15 else ""))
        L.append("")
    L += ["## AI-readiness criteria", "", "| Criterion | Weight | Score |", "|---|---|---|"]
    for c in o["ai"]["criteria"]:
        L.append("| %s %s | %d | %s |" % (c["id"], c["name"], c["weight"], c["score"]))
    if o.get("suggestions"):
        L += ["", "## Contrast fix proposals", "", "| Token | Mode | Current | Worst pair | Nearest passing step | Minimal shift |", "|---|---|---|---|---|---|"]
        for x in o["suggestions"]:
            L.append("| %s | %s | `%s` | %s | %s | %s |" % (x["token"], x["mode"], x["current"], x["worst"],
                     "%s `%s`" % (x["nearestStep"], x["nearestStepHex"]) if x["nearestStep"] else "none",
                     "`%s`" % x["minimalShift"] if x["minimalShift"] else "none"))
    fails = [c for c in o["contrast"] if not c["pass"]]
    L += ["", "## Contrast failures (%d of %d checks)" % (len(fails), len(o["contrast"])), "",
          "| Foreground | Background | Mode | Ratio | Min | Kind | APCA Lc (WCAG 3 draft, informative) |", "|---|---|---|---|---|---|---|"]
    for c in sorted(fails, key=lambda c: c["ratio"])[:80]:
        L.append("| %s `%s` | %s `%s` | %s | %.2f | %.1f | %s | %.1f |" % (c["fg"], c["fgHex"], c["bg"], c["bgHex"], c["mode"], c["ratio"], c["min"], c["kind"], c["apca"]))
    return "\n".join(L) + "\n"


# ----------------------------------------------------------------------------
# Generate
# ----------------------------------------------------------------------------

def find_token(model, ref):
    ts = model["tokens"]
    if "::" in ref:
        c, n = ref.split("::", 1)
        hit = [t for t in ts if t["collection"] == c and t["name"] == n]
    elif ref.startswith("--"):
        hit = [t for t in ts if t["cssVar"] == ref]
    else:
        hit = [t for t in ts if t["name"] == ref]
    if len(hit) != 1:
        raise SystemExit("change refers to %r: %d matches (use Collection::name)" % (ref, len(hit)))
    return hit[0]


def apply_changes(model, changes, log):
    cols = col_by_name(model)
    for ch in changes:
        op = ch["op"]
        if op == "add":
            col = cols[ch["collection"]]
            t = {"key": "new:%s::%s" % (ch["collection"], ch["name"]), "name": ch["name"], "collection": ch["collection"],
                 "figmaId": None, "type": ch["type"], "scopes": ch.get("scopes"), "description": ch.get("description", ""),
                 "codeSyntax": {}, "cssVar": ch.get("cssVar") or css_var_for(ch["name"]), "values": {}, "status": "new"}
            vals = ch["values"] if isinstance(ch["values"], dict) else {m["name"]: ch["values"] for m in col["modes"]}
            model["tokens"].append(t)
            for m, v in vals.items():
                t["values"][m] = {"alias": find_token(model, v["alias"])["key"]} if isinstance(v, dict) else {"value": norm_value(t["type"], v)}
            log.append({"op": "add", "token": ref_of(t)})
            continue
        t = find_token(model, ch["token"])
        modes = [ch["mode"]] if ch.get("mode") else [m["name"] for m in cols[t["collection"]]["modes"]]
        if op == "set":
            for m in modes:
                t["values"][m] = {"value": norm_value(t["type"], ch["value"])}
        elif op == "alias":
            tgt = find_token(model, ch["to"])
            for m in modes:
                t["values"][m] = {"alias": tgt["key"]}
        elif op == "rename":
            old = ref_of(t)
            t["name"] = ch["to"]
            t["cssVar"] = ch.get("cssVar") or css_var_for(ch["to"])
            t["codeSyntax"] = {k: v for k, v in (t.get("codeSyntax") or {}).items() if k != "WEB"}
            t["status"] = "renamed"
            log.append({"op": "rename", "from": old, "to": ref_of(t)})
            continue
        elif op == "describe":
            t["description"] = ch["description"]
        elif op == "scopes":
            t["scopes"] = ch["scopes"]
        else:
            raise SystemExit("unknown op %s" % op)
        t.setdefault("status", "changed")
        log.append(dict(ch, token=ref_of(t)))


def norm_value(typ, v):
    if typ == "COLOR":
        c = parse_color(v)
        if not c:
            raise SystemExit("invalid color %r" % v)
        return to_hex(c)
    return v


def value_key(typ, v):
    return to_hex(parse_color(v)) if typ == "COLOR" else json.dumps(v)


def new_primitive_name(model, prim_col, typ, value, sem_tok):
    names = {t["name"] for t in model["tokens"] if t["collection"] == prim_col}
    if typ == "COLOR":
        c = parse_color(value)
        h, l, s = hls(c)
        s = chroma(c)
        cprims = [t for t in model["tokens"] if t["collection"] == prim_col and t["type"] == "COLOR"]
        rp = Counter(t["name"].rsplit("/", 2)[0] + "/" if t["name"].count("/") >= 2 else "" for t in cprims if last_seg(t["name"]).isdigit())
        prefix = rp.most_common(1)[0][0] if rp else "color/"
        if c[3] < 1:
            base = to_hex(c[:3] + (1.0,))
            for t in cprims:
                v = next(iter(t["values"].values()), {}).get("value")
                if v and to_hex(parse_color(v)) == base:
                    cand = "%s-a%d" % (t["name"], round(c[3] * 100))
                    if cand not in names:
                        return cand
            return "%salpha/%s" % (prefix, to_hex(c)[1:])
        hx = to_hex(c)
        if hx in ("#ffffff", "#000000"):
            cand = prefix + ("white" if hx == "#ffffff" else "black")
            if cand not in names:
                return cand
        ramps = defaultdict(list)
        for t in model["tokens"]:
            if t["collection"] == prim_col and t["type"] == "COLOR" and last_seg(t["name"]).isdigit():
                tc = parse_color(t["values"][next(iter(t["values"]))].get("value", "#000"))
                if tc:
                    ramps[t["name"].rsplit("/", 1)[0]].append((int(last_seg(t["name"])), hls(tc)[:2] + (chroma(tc),)))
        best, bd = None, 1e9
        for rn, entries in ramps.items():
            if len(entries) < 3:
                continue
            rs = sum(e[1][2] for e in entries) / len(entries)
            if (s < 0.08) != (rs < 0.08):
                continue
            if s < 0.08:
                d = abs(rs - s)
            else:
                rh = math.atan2(sum(math.sin(2 * math.pi * e[1][0]) for e in entries), sum(math.cos(2 * math.pi * e[1][0]) for e in entries)) / (2 * math.pi) % 1
                d = min(abs(rh - h), 1 - abs(rh - h)) * 360
                if d > 20:
                    continue
            if d < bd:
                best, bd = rn, d
        if best:
            ent = sorted(ramps[best])
            dark_up = ent[0][1][1] > ent[-1][1][1]  # lightness decreases as step grows
            for (s1, h1), (s2, h2) in zip(ent, ent[1:]):
                lo, hi = sorted((h1[1], h2[1]))
                if lo <= l <= hi:
                    step = (s1 + s2) // 2
                    break
            else:
                first, last = ent[0][0], ent[-1][0]
                lighter = l > ent[0][1][1] if dark_up else l < ent[0][1][1]
                step = max(1, first // 2) if lighter else last + (last - ent[-2][0])
            cand = "%s/%d" % (best, step)
            if cand not in names:
                return cand
        return "%sextra/%s" % (prefix, to_hex(c)[1:])
    if typ == "FLOAT":
        kind = float_kind(sem_tok["name"])
        return "%s/%s" % (kind, str(value).replace(".", "_").replace("-", "neg"))
    kind = "font-family" if re.search(r"font|family|typeface", sem_tok["name"], re.I) else "string"
    base = "%s/%s" % (kind, slug(str(value))[:40])
    return base if base not in names else base + "-2"


def enforce_primitives(model, log, types):
    """Every semantic literal becomes an alias to a (new or existing) primitive."""
    tiers = {c["name"]: c["tier"] for c in model["collections"]}
    prim_cols = [c["name"] for c in model["collections"] if c["tier"] == "primitive"]
    if not prim_cols:
        model["collections"].insert(0, {"name": "Primitives", "figmaId": None, "tier": "primitive",
                                        "modes": [{"name": "Value", "figmaId": None, "selector": None}]})
        prim_cols = ["Primitives"]
        tiers["Primitives"] = "primitive"
        log.append({"op": "add-collection", "collection": "Primitives"})
    prim_col = prim_cols[0]
    pmode = col_by_name(model)[prim_col]["modes"][0]["name"]
    lookup = {}
    for t in model["tokens"]:
        if tiers[t["collection"]] == "primitive":
            v = t["values"].get(col_by_name(model)[t["collection"]]["modes"][0]["name"], {})
            if "value" in v:
                k = (t["type"], value_key(t["type"], v["value"]))
                prev = lookup.get(k)
                if prev is None or (len(t["name"]), t["name"]) < (len(prev["name"]), prev["name"]):
                    lookup[k] = t
    # alias-tier tokens (single mode) by resolved value: mapped tokens prefer these to keep the 3-tier chain
    res = Resolver(model)
    alias_lookup = {}
    for t in model["tokens"]:
        c = res.cols[t["collection"]]
        if tiers[t["collection"]] == "alias" and len(c["modes"]) == 1:
            r = res.resolve(t["key"], c["modes"][0]["name"])
            if r["error"] is None and len(r["chain"]) > 1:
                k = (t["type"], value_key(t["type"], r["value"]))
                prev = alias_lookup.get(k)
                if prev is None or (len(t["name"]), t["name"]) < (len(prev["name"]), prev["name"]):
                    alias_lookup[k] = t
    alias_col = next((c["name"] for c in model["collections"] if c["tier"] == "alias" and len(c["modes"]) == 1), None)

    def mirror_alias(p):
        """New primitive color/grey/650 -> create neutral/650 if the alias tier mirrors color/grey/*."""
        if not alias_col or not last_seg(p["name"]).isdigit():
            return None
        ramp = p["name"].rsplit("/", 1)[0]
        prefixes = Counter()
        for t in model["tokens"]:
            if t["collection"] != alias_col or not last_seg(t["name"]).isdigit():
                continue
            v = next(iter(t["values"].values()), {})
            tgt = res.idx.get(v.get("alias"))
            if tgt and tgt["name"].rsplit("/", 1)[0] == ramp:
                prefixes[t["name"].rsplit("/", 1)[0]] += 1
        if not prefixes:
            return None
        name = "%s/%s" % (prefixes.most_common(1)[0][0], last_seg(p["name"]))
        if any(t["collection"] == alias_col and t["name"] == name for t in model["tokens"]):
            return None
        amode = col_by_name(model)[alias_col]["modes"][0]["name"]
        a = {"key": "new:%s::%s" % (alias_col, name), "name": name, "collection": alias_col, "figmaId": None,
             "type": p["type"], "scopes": None, "description": "", "codeSyntax": {}, "cssVar": css_var_for(name),
             "values": {amode: {"alias": p["key"]}}, "status": "new"}
        model["tokens"].append(a)
        res.idx[a["key"]] = a
        log.append({"op": "add-alias", "token": ref_of(a), "to": ref_of(p)})
        return a

    for t in list(model["tokens"]):
        if tiers[t["collection"]] == "primitive" or t["type"] not in types:
            continue
        upper = tiers[t["collection"]] in ("mapped", "responsive")
        for m, v in t["values"].items():
            if "value" not in v:
                continue
            if t["type"] == "STRING" and (not re.search(r"font|family|typeface", t["name"], re.I) or "(" in str(v["value"])):
                continue  # shadows, gradients etc. stay literal (Figma cannot hold them as variables)
            k = (t["type"], value_key(t["type"], v["value"]))
            if upper and k in alias_lookup:
                t["values"][m] = {"alias": alias_lookup[k]["key"]}
                t.setdefault("status", "changed")
                log.append({"op": "literal-to-alias", "token": ref_of(t), "mode": m, "to": ref_of(alias_lookup[k])})
                continue
            p = lookup.get(k)
            if p is None:
                name = new_primitive_name(model, prim_col, t["type"], v["value"], t)
                p = {"key": "new:%s::%s" % (prim_col, name), "name": name, "collection": prim_col, "figmaId": None,
                     "type": t["type"], "scopes": None, "description": "", "codeSyntax": {}, "cssVar": css_var_for(name),
                     "values": {pmode: {"value": v["value"]}}, "status": "new"}
                model["tokens"].append(p)
                res.idx[p["key"]] = p
                lookup[k] = p
                log.append({"op": "add-primitive", "token": ref_of(p), "value": v["value"], "for": ref_of(t)})
                if upper and t["type"] == "COLOR":
                    a = mirror_alias(p)
                    if a:
                        alias_lookup[k] = a
            if upper and k in alias_lookup:
                p = alias_lookup[k]
            t["values"][m] = {"alias": p["key"]}
            t.setdefault("status", "changed")
            log.append({"op": "literal-to-alias", "token": ref_of(t), "mode": m, "to": ref_of(p)})


SCOPE_BY_ROLE = {"bg": ["FRAME_FILL", "SHAPE_FILL"], "text": ["TEXT_FILL"], "icon": ["SHAPE_FILL", "STROKE_COLOR"],
                 "border": ["STROKE_COLOR"], "focus": ["STROKE_COLOR", "EFFECT_COLOR"]}
SCOPE_BY_KIND = {"spacing": ["GAP"], "radius": ["CORNER_RADIUS"], "font-size": ["FONT_SIZE"], "line-height": ["LINE_HEIGHT"],
                 "font-weight": ["FONT_WEIGHT"], "letter-spacing": ["LETTER_SPACING"], "border-width": ["STROKE_FLOAT"],
                 "opacity": ["OPACITY"], "size": ["WIDTH_HEIGHT"]}


def infer_scopes(model, log):
    tiers = {c["name"]: c["tier"] for c in model["collections"]}
    for t in model["tokens"]:
        if t.get("scopes") not in (None, ["ALL_SCOPES"]):
            continue
        if tiers[t["collection"]] == "primitive":
            s = []
        elif t["type"] == "COLOR":
            s = SCOPE_BY_ROLE.get(role_of(t["name"]), ["ALL_FILLS", "STROKE_COLOR"])
        elif t["type"] == "FLOAT":
            s = SCOPE_BY_KIND.get(float_kind(t["name"]), ["ALL_SCOPES"])
        elif re.search(r"font|family", t["name"], re.I):
            s = ["FONT_FAMILY"]
        else:
            continue
        if s != t.get("scopes"):
            t["scopes"] = s
            t.setdefault("status", "changed")
            log.append({"op": "scopes", "token": ref_of(t), "scopes": s})


def mode_selector(col, i, mode, overrides):
    key = "%s:%s" % (col["name"], mode["name"])
    if key in overrides:
        return overrides[key]
    if mode.get("selector"):
        return mode["selector"]
    n = mode["name"].lower()
    ms = slug(mode["name"])
    themey = re.search(r"dark|light|dim|contrast|night|day|\bhc\b", n)
    if i == 0:
        return ':root, [data-theme="%s"]' % ms if themey else ":root"
    if themey:
        return '[data-theme="%s"]' % ms
    if re.search(r"mobile|phone|small|compact|\bsm\b|\bs\b", n):
        return "@media (max-width: 767px) { :root }"
    if re.search(r"tablet|medium|\bmd\b|\bm\b", n):
        return "@media (min-width: 768px) and (max-width: 1023px) { :root }"
    if re.search(r"desktop|large|wide|\blg\b|\bl\b|xl", n):
        return "@media (min-width: 1024px) { :root }"
    return '[data-%s="%s"]' % (slug(col["name"]), ms)


def fmt_value(t, v):
    typ = t["type"]
    if typ == "COLOR":
        return to_hex(parse_color(v))
    if typ == "FLOAT":
        kind = float_kind(t["name"])
        num = int(v) if float(v) == int(v) else round(float(v), 4)
        if kind in UNITLESS:
            return str(num)
        if kind == "duration":
            return "%sms" % num if num >= 10 else "%ss" % num
        return "%spx" % num if num != 0 else "0"
    if typ == "BOOLEAN":
        return "1" if v else "0"
    s = str(v)
    if re.search(r"font|family", t["name"], re.I) and " " in s and not re.search(r"[,'\"]", s):
        return '"%s"' % s
    return s


def build_manifest_and_css(model, overrides, src_label):
    idx = tok_index(model)
    order = sorted(model["collections"], key=lambda c: TIER_ORDER.get(c["tier"], 1))
    man = {"format": "token-foundry/manifest@1", "generator": "tokenkit %s" % VERSION,
           "generatedAt": datetime.datetime.now().isoformat(timespec="seconds"), "source": model["source"],
           "css": "tokens.css", "collections": [], "tokens": []}
    css = ["/*", " * Design tokens. Generated by token-foundry (tokenkit %s) from %s." % (VERSION, src_label),
           " * Regenerate instead of editing by hand. Figma IDs, scopes and descriptions: tokens.manifest.json", " */", ""]
    for col in order:
        modes = []
        for i, m in enumerate(col["modes"]):
            modes.append({"name": m["name"], "figmaId": m.get("figmaId"), "selector": mode_selector(col, i, m, overrides)})
        man["collections"].append({"name": col["name"], "figmaId": col.get("figmaId"), "tier": col["tier"], "modes": modes})
        ctoks = [t for t in model["tokens"] if t["collection"] == col["name"]]
        for i, m in enumerate(modes):
            lines = []
            for t in ctoks:
                v = t["values"].get(m["name"])
                if v is None:
                    continue
                if "alias" in v:
                    tgt = idx.get(v["alias"])
                    if tgt is None:
                        continue
                    lines.append("  %s: var(%s);" % (t["cssVar"], tgt["cssVar"]))
                else:
                    lines.append("  %s: %s;" % (t["cssVar"], fmt_value(t, v["value"])))
            if not lines:
                continue
            css.append("/* @collection %s @tier %s @mode %s%s */" % (col["name"], col["tier"], m["name"], " (default)" if i == 0 else ""))
            sel = m["selector"]
            mm = re.match(r"^(@media[^{]+)\{\s*(.+?)\s*\}?$", sel)
            if mm:
                css.append("%s {\n  %s {\n%s\n  }\n}\n" % (mm.group(1).strip(), mm.group(2).strip(" }") or ":root",
                                                         "\n".join("  " + x for x in lines)))
            else:
                css.append("%s {\n%s\n}\n" % (sel, "\n".join(lines)))
    for t in model["tokens"]:
        vals = {}
        for m, v in t["values"].items():
            if "alias" in v:
                tgt = idx.get(v["alias"])
                if tgt is None:
                    vals[m] = {"alias": {"figmaId": v["alias"], "external": True}}
                else:
                    vals[m] = {"alias": {"collection": tgt["collection"], "name": tgt["name"], "cssVar": tgt["cssVar"], "figmaId": tgt.get("figmaId")}}
            else:
                vals[m] = {"value": v["value"]}
        man["tokens"].append({"cssVar": t["cssVar"], "name": t["name"], "collection": t["collection"], "figmaId": t.get("figmaId"),
                              "type": t["type"], "scopes": t.get("scopes"), "description": t.get("description", ""),
                              "codeSyntax": t.get("codeSyntax") or {}, "status": t.get("status", "unchanged"), "values": vals})
    return man, "\n".join(css)


def cmd_generate(a):
    model = json.load(open(a.model))
    log = []
    if a.changes:
        apply_changes(model, json.load(open(a.changes)), log)
    types = {"COLOR"} if a.colors_only else {"COLOR", "FLOAT", "STRING"}
    if not a.keep_literals:
        enforce_primitives(model, log, types)
    if a.infer_scopes:
        infer_scopes(model, log)
    # css names: keep existing, fix collisions
    seen = {}
    for t in model["tokens"]:
        t["cssVar"] = t.get("cssVar") or css_var_for(t["name"])
        if t["cssVar"] in seen:
            nv = "--%s-%s" % (slug(t["collection"]), t["cssVar"][2:])
            log.append({"op": "css-rename", "token": ref_of(t), "from": t["cssVar"], "to": nv})
            t["cssVar"] = nv
        seen[t["cssVar"]] = t
    if not a.no_code_syntax:
        for t in model["tokens"]:
            want = "var(%s)" % t["cssVar"]
            if (t.get("codeSyntax") or {}).get("WEB") != want:
                t["codeSyntax"] = dict(t.get("codeSyntax") or {}, WEB=want)
                t["codeSyntaxChanged"] = True
    overrides = {}
    for o in a.mode_selector or []:
        k, v = o.split("=", 1)
        overrides[k] = v
    man, css = build_manifest_and_css(model, overrides, "%s %s" % (model["source"]["kind"], model["source"].get("file") or ""))
    man["changes"] = log
    os.makedirs(a.out, exist_ok=True)
    open(os.path.join(a.out, a.css_name), "w").write(css)
    man["css"] = a.css_name
    json.dump(man, open(os.path.join(a.out, "tokens.manifest.json"), "w"), indent=2, ensure_ascii=False)
    json.dump(log, open(os.path.join(a.out, "generate-log.json"), "w"), indent=2, ensure_ascii=False)
    stats = Counter(c["op"] for c in log)
    print(json.dumps({"tokens": len(man["tokens"]), "changes": dict(stats)}), file=sys.stderr)
    print(os.path.join(a.out, a.css_name))


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def cmd_ingest(a):
    raw = open(a.input, encoding="utf-8").read()
    man = json.load(open(a.manifest)) if a.manifest else None
    kind = a.kind
    if kind == "auto":
        s = raw.lstrip()
        if s.startswith("{"):
            d = json.loads(raw)
            kind = "manifest" if str(d.get("format", "")).startswith("token-foundry/manifest") else "figma"
        else:
            kind = "css"
    if kind == "css":
        model = ingest_css(raw, a.input, man)
    elif kind == "manifest":
        model = ingest_manifest(json.loads(raw), a.input)
    else:
        model = ingest_figma(json.loads(raw), a.input)
        if man:  # recover CSS selectors and css names from the previous manifest
            sel = {(c["name"], m["name"]): m.get("selector") for c in man["collections"] for m in c["modes"]}
            for c in model["collections"]:
                for m in c["modes"]:
                    m["selector"] = m.get("selector") or sel.get((c["name"], m["name"]))
            css_by_id = {t["figmaId"]: t["cssVar"] for t in man["tokens"] if t.get("figmaId")}
            for t in model["tokens"]:
                if t["figmaId"] in css_by_id and not (t.get("codeSyntax") or {}).get("WEB"):
                    t["cssVar"] = css_by_id[t["figmaId"]]
    for spec in a.tier or []:
        n, t = spec.split("=", 1)
        for c in model["collections"]:
            if c["name"] == n:
                c["tier"] = t
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(model, open(a.out, "w"), indent=2, ensure_ascii=False)
    print(json.dumps({"kind": kind, "collections": [(c["name"], c["tier"], [m["name"] for m in c["modes"]]) for c in model["collections"]],
                      "tokens": len(model["tokens"])}, ensure_ascii=False), file=sys.stderr)
    print(a.out)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    i = sp.add_parser("ingest", help="normalize CSS / Figma JSON / manifest into model.json")
    i.add_argument("input")
    i.add_argument("--kind", choices=["auto", "css", "figma", "manifest"], default="auto")
    i.add_argument("--manifest", help="previous tokens.manifest.json to recover Figma names/IDs for CSS input")
    i.add_argument("--tier", action="append", help="override tier: 'Collection=primitive|alias|mapped|responsive'")
    i.add_argument("-o", "--out", default="model.json")
    i.set_defaults(fn=cmd_ingest)
    au = sp.add_parser("audit", help="structure + WCAG 2.2 AA + AI-readiness")
    au.add_argument("model")
    au.add_argument("--pairs", help="JSON list of {fg, bg, min} pairs to test in addition to inferred ones")
    au.add_argument("-o", "--out", default="out")
    au.set_defaults(fn=cmd_audit)
    g = sp.add_parser("generate", help="tokens.css + tokens.manifest.json")
    g.add_argument("model")
    g.add_argument("--changes", help="JSON list of approved changes (set/alias/rename/add/describe/scopes)")
    g.add_argument("--colors-only", action="store_true", help="only convert COLOR literals to primitive aliases")
    g.add_argument("--keep-literals", action="store_true", help="do not convert semantic literals")
    g.add_argument("--infer-scopes", action="store_true", help="set Figma scopes on tokens with none/ALL_SCOPES")
    g.add_argument("--no-code-syntax", action="store_true", help="do not set Figma WEB code syntax")
    g.add_argument("--mode-selector", action="append", help="'Collection:Mode=<selector>' e.g. 'Theme:Dark=.dark'")
    g.add_argument("--css-name", default="tokens.css")
    g.add_argument("-o", "--out", default="out")
    g.set_defaults(fn=cmd_generate)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
