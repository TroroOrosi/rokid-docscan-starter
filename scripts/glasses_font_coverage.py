"""Which characters the glasses' answer display cannot draw, read from the fonts' own cmap tables.

    adb -s <glasses> shell cat /system/etc/fonts.xml > fonts.xml
    adb -s <glasses> pull /system/fonts fonts            (in Git Bash put MSYS_NO_PATHCONV=1 before it)
    py -3.12 -I scripts/glasses_font_coverage.py fonts.xml fonts/fonts [--family monospace] [--chars <text file>]

The answer view draws with the monospace typeface. Such a typeface falls back through its own family and the
families without a name, in order; another named family (Roboto under sans-serif) is never reached, so a
character only Roboto has is a box on the glasses. Prints, per row of candidates, the characters no font of
that chain has. `app/answer_text.py` keeps only the script characters this reports as drawn: run it again
after a firmware update. Reads formats 4, 12 and 13 of the Unicode cmap subtables; .ttc collections face by face.
Firmware 1.29.013, 2026-11-16: no script sign, no script letter but the superscript n, no U+03D5, U+03F5,
U+2153, U+2154, U+2155; every other candidate below is drawn.
"""
import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROWS = [
    ("sup digits", "⁰¹²³⁴⁵⁶⁷⁸⁹"), ("sup signs", "⁺⁻⁼⁽⁾"), ("sup n i", "ⁿⁱ"),
    ("sup letters a", "ᵃᵇᶜᵈᵉᶠᵍʰʲᵏˡᵐ"), ("sup letters b", "ᵒᵖʳˢᵗᵘᵛʷˣʸᶻ"),
    ("sup capitals", "ᴬᴮᴰᴱᴳᴴᴵᴶᴷᴸᴹᴺᴼᴾᴿᵀᵁⱽᵂ"),
    ("sub digits", "₀₁₂₃₄₅₆₇₈₉"), ("sub signs", "₊₋₌₍₎"),
    ("sub letters a", "ₐₑₒₓₕₖₗ"), ("sub letters b", "ₘₙₚₛₜᵢⱼᵣᵤᵥ"), ("sub greek", "ᵦᵧᵨᵩᵪ"),
    ("roots", "√∛∜"), ("compare", "≤≥≠≈≡≦≧≪≫≒∼≃"), ("sets", "∈∉∋⊂⊃⊆⊇∩∪∅∖"),
    ("logic", "∀∃¬∧∨⇒⇔→←↔↑↓⇐↦"), ("calc", "∑∏∫∬∮∂∇∞∝′″‴"), ("greek a", "αβγδεζηθικλμ"),
    ("greek b", "νξπρστυφχψωϕϵϑ"), ("greek cap", "ΓΔΘΛΞΠΣΦΨΩ"), ("misc", "°‰±∓×÷·∙⋅∘⊕⊗∗"),
    ("fractions", "½⅓⅔¼¾⅕⅛"), ("combining", "⃗̄̂̇̈̃"), ("angle etc", "∠⊥∥∦△▽□◯○●∴∵≅∽"),
    ("brackets", "⌊⌋⌈⌉〈〉《》「」『』【】｛｝"), ("circled", "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"),
    ("roman", "ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅰⅱⅲⅳⅴ"), ("blackboard", "ℝℕℤℚℂℙ"), ("script etc", "ℓℏÅ℃℉ℵ"),
    ("vectors bars", "→⃗"), ("chem arrows", "⇄⇌⟶⟵⟷"), ("units", "㎝㎏㎡㎥㎞Ω"),
    ("kana marks", "ー〜～・…‥"), ("minus dash", "−–—―‐"), ("math letters", "𝑥𝑦𝒂𝐚"),
]


def cmap(data: bytes, base: int) -> set[int]:
    count = struct.unpack_from(">H", data, base + 4)[0]
    table = None
    for n in range(count):
        tag, _, offset, _ = struct.unpack_from(">4sIII", data, base + 12 + 16 * n)
        if tag == b"cmap":
            table = offset
    if table is None:
        return set()
    have: set[int] = set()
    for n in range(struct.unpack_from(">H", data, table + 2)[0]):
        platform, encoding, offset = struct.unpack_from(">HHI", data, table + 4 + 8 * n)
        if not (platform == 0 or (platform == 3 and encoding in (1, 10))):
            continue
        at = table + offset
        fmt = struct.unpack_from(">H", data, at)[0]
        if fmt == 4:
            seg = struct.unpack_from(">H", data, at + 6)[0] // 2
            ends = struct.unpack_from(f">{seg}H", data, at + 14)
            starts = struct.unpack_from(f">{seg}H", data, at + 16 + 2 * seg)
            deltas = struct.unpack_from(f">{seg}h", data, at + 16 + 4 * seg)
            ranges_at = at + 16 + 6 * seg
            ranges = struct.unpack_from(f">{seg}H", data, ranges_at)
            for i in range(seg):
                for code in range(starts[i], ends[i] + 1):
                    if code == 0xFFFF:
                        continue
                    if ranges[i] == 0:
                        glyph = (code + deltas[i]) & 0xFFFF
                    else:
                        where = ranges_at + 2 * i + ranges[i] + 2 * (code - starts[i])
                        glyph = struct.unpack_from(">H", data, where)[0]
                        if glyph:
                            glyph = (glyph + deltas[i]) & 0xFFFF
                    if glyph:
                        have.add(code)
        elif fmt in (12, 13):
            groups = struct.unpack_from(">I", data, at + 12)[0]
            for g in range(groups):
                first, last, glyph = struct.unpack_from(">III", data, at + 16 + 12 * g)
                if fmt == 13 and glyph == 0:
                    continue
                have.update(range(first, last + 1))
    return have


def faces(path: Path) -> list[set[int]]:
    data = path.read_bytes()
    if data[:4] == b"ttcf":
        count = struct.unpack_from(">I", data, 8)[0]
        return [cmap(data, off) for off in struct.unpack_from(f">{count}I", data, 12)]
    return [cmap(data, 0)]


def main() -> int:
    # A typeface of a named family falls back through that family and the families without a name, in order; a
    # font marked fallbackFor another family is not in its chain. Another named family (Roboto under sans-serif,
    # for a monospace typeface) is never reached.
    family = sys.argv[sys.argv.index("--family") + 1] if "--family" in sys.argv else "monospace"
    fonts = Path(sys.argv[2])
    names = []
    for node in ET.parse(sys.argv[1]).getroot().iter("family"):
        if node.get("name") not in (None, family):
            continue
        for font in node.iter("font"):
            if font.get("fallbackFor") in (None, family) and (font.text or "").strip():
                names.append((font.text or "").strip())
    names = list(dict.fromkeys(names))
    print(f"chain of {family}: {len(names)} font files, first {names[:4]}")
    union: set[int] = set()
    owner: dict[int, str] = {}
    read = 0
    for name in names:
        path = fonts / name
        if not path.is_file() or path.stat().st_size < 1024:
            continue
        try:
            sets = faces(path)
        except (struct.error, IndexError) as error:
            print(f"unreadable {name}: {error}")
            continue
        read += 1
        for have in sets:
            for code in have - union:
                owner[code] = name
            union |= have
    print(f"{read} of {len(names)} listed font files read; {len(union)} characters covered")
    rows = ROWS
    if "--chars" in sys.argv:
        text = Path(sys.argv[sys.argv.index("--chars") + 1]).read_text(encoding="utf-8")
        rows = [("given", "".join(dict.fromkeys(c for c in text if not c.isspace())))]
    for label, chars in rows:
        missing = [c for c in chars if ord(c) not in union]
        print(f"{label:14} {len(chars) - len(missing):2}/{len(chars):2}  missing: "
              + (" ".join(f"{c}(U+{ord(c):04X})" for c in missing) or "-"))
    probe = "ₘ₂²ⁿ①√"
    print("probe: " + ", ".join(f"{c} {owner.get(ord(c), 'NONE')}" for c in probe))
    return 0


if __name__ == "__main__":
    sys.exit(main())
