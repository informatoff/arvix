import io
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

W, H = 1600, 651
BG = (8, 8, 8)
PANEL_TOP, PANEL_BOTTOM = (58, 58, 58), (24, 24, 24)
CARD = (33, 33, 33)
WHITE = (255, 255, 255)
MUTED = (190, 190, 190)
DIM = (110, 110, 110)
TRACK = (50, 50, 50)

ROWS = [(114, 260), (277, 423), (440, 586)]

STATIC_FONTS = {
    400: "Montserrat-Regular.ttf",
    500: "Montserrat-Medium.ttf",
    600: "Montserrat-SemiBold.ttf",
    700: "Montserrat-Bold.ttf",
    800: "Montserrat-ExtraBold.ttf",
}


@lru_cache(maxsize=None)
def font(size: int, weight: int = 700) -> ImageFont.FreeTypeFont:
    static = FONT_DIR / STATIC_FONTS.get(weight, "Montserrat-Bold.ttf")
    if static.exists():
        return ImageFont.truetype(str(static), size)

    for name in ("Montserrat.ttf", "Montserrat[wght].ttf"):
        variable = FONT_DIR / name
        if variable.exists():
            try:
                f = ImageFont.truetype(str(variable), size)
                f.set_variation_by_axes([weight])
                return f
            except (OSError, AttributeError):
                pass

    for c in ("arialbd.ttf" if weight >= 600 else "arial.ttf",
              "DejaVuSans-Bold.ttf" if weight >= 600 else "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(c, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _rounded_mask(size, radius, scale=4) -> Image.Image:
    big = Image.new("L", (size[0] * scale, size[1] * scale), 0)
    ImageDraw.Draw(big).rounded_rectangle(
        (0, 0, big.width - 1, big.height - 1), radius * scale, fill=255
    )
    return big.resize(size, Image.LANCZOS)


def _gradient_panel(img, box, radius):
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    grad = Image.linear_gradient("L").resize((w, h))
    fill = Image.composite(
        Image.new("RGB", (w, h), PANEL_BOTTOM), Image.new("RGB", (w, h), PANEL_TOP), grad
    )
    img.paste(fill, (x0, y0), _rounded_mask((w, h), radius))


def _solid_card(img, box, radius, color=CARD):
    x0, y0, x1, y1 = box
    img.paste(color, box, _rounded_mask((x1 - x0, y1 - y0), radius))


@lru_cache(maxsize=None)
def _icon(kind: str, size: int = 24) -> Image.Image:
    custom = Path(__file__).resolve().parent.parent / "assets" / "icons" / f"{kind}.png"
    if custom.exists():
        return Image.open(custom).convert("RGBA").resize((size, size), Image.LANCZOS)

    s = 4
    big = Image.new("RGBA", (24 * s, 24 * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    c = MUTED + (255,)
    p = lambda *v: [x * s for x in v]  # noqa: E731

    if kind == "balance":
        d.polygon(p(8, 2, 16, 2, 14, 8, 10, 8), fill=c)
        d.ellipse(p(3, 7, 21, 23), fill=c)
        d.text((12 * s, 15.5 * s), "$", font=font(11 * s, 800), fill=(0, 0, 0, 0), anchor="mm")
    elif kind == "messages":
        d.polygon(p(1, 11, 23, 2, 16, 22, 11, 14), fill=c)
    elif kind == "voice":
        d.rounded_rectangle(p(8, 1, 16, 14), radius=4 * s, fill=c)
        d.arc(p(5, 6, 19, 19), 0, 180, fill=c, width=2 * s)
        d.line(p(12, 19, 12, 22), fill=c, width=2 * s)
        d.line(p(8, 22, 16, 22), fill=c, width=2 * s)
    else:
        d.polygon(p(6, 2, 18, 2, 17, 11, 12, 14, 7, 11), fill=c)
        d.ellipse(p(2, 3, 8, 9), outline=c, width=2 * s)
        d.ellipse(p(16, 3, 22, 9), outline=c, width=2 * s)
        d.rectangle(p(11, 14, 13, 18), fill=c)
        d.rectangle(p(7, 19, 17, 22), fill=c)
    return big.resize((size, size), Image.LANCZOS)


def render_profile(
    avatar_bytes: bytes | None,
    coins: int,
    messages: int,
    voice_hours: int,
    level: int,
    xp: int,
    xp_need: int,
    rank_level: int,
    rank_coins: int,
    rank_voice: int,
    username: str = ".",
) -> io.BytesIO:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    for box in [(70, 55, 490, 610), (527, 55, 1046, 353), (527, 381, 1046, 610), (1082, 55, 1530, 610)]:
        _gradient_panel(img, box, 46)

    def column(x0, x1, cx, title, items):
        d.text((cx, 90), title, font=font(28, 700), fill=WHITE, anchor="mm")
        for (kind, label, value), (y0, y1) in zip(items, ROWS):
            _solid_card(img, (x0, y0, x1, y1), 24)
            ic = _icon(kind)
            img.paste(ic, (x0 + 21, y0 + 18), ic)
            d.text((x0 + 56, y0 + 30), label, font=font(21, 500), fill=MUTED, anchor="lm")
            d.text((x0 + 21, y1 - 12), value, font=font(38, 800), fill=WHITE, anchor="ls")

    column(104, 457, 280, "Статистика", [
        ("balance", "Баланс", str(coins)),
        ("messages", "Сообщений", str(messages)),
        ("voice", "Часов в войсах", str(voice_hours)),
    ])
    column(1116, 1497, 1306, "Топы", [
        ("trophy", "Топ по уровню", f"#{rank_level}"),
        ("trophy", "Топ по коинам", f"#{rank_coins}"),
        ("trophy", "Топ по войсу", f"#{rank_voice}"),
    ])

    size, cx, cy = 190, 786, 189
    try:
        av = Image.open(io.BytesIO(avatar_bytes)).convert("RGB").resize((size, size), Image.LANCZOS)
    except Exception:
        av = Image.new("RGB", (size, size), (70, 72, 78))
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
    img.paste(av, (cx - size // 2, cy - size // 2), mask.resize((size, size), Image.LANCZOS))
    d.text((cx, 335), str(username)[:20], font=font(26, 700), fill=WHITE, anchor="mm")

    d.rounded_rectangle((698, 423, 875, 520), radius=26, fill=(46, 46, 46), outline=(84, 84, 84), width=2)
    d.text((786, 455), str(level), font=font(48, 800), fill=WHITE, anchor="mm")
    d.text((786, 491), "Уровень", font=font(19, 500), fill=MUTED, anchor="mm")

    d.text((578, 557), str(level), font=font(19, 500), fill=WHITE, anchor="lm")
    d.text((994, 557), str(level + 1), font=font(19, 500), fill=DIM, anchor="rm")
    d.text((786, 557), f"{xp:,} / {xp_need:,} xp", font=font(19, 500), fill=MUTED, anchor="mm")

    bx0, bx1, by = 578, 994, 579
    d.rounded_rectangle((bx0, by - 2, bx1, by + 2), radius=2, fill=TRACK)
    ratio = max(0.0, min(1.0, xp / xp_need)) if xp_need else 0.0
    if ratio > 0:
        d.rounded_rectangle((bx0, by - 2, bx0 + max(4, int((bx1 - bx0) * ratio)), by + 2), radius=2, fill=WHITE)

    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf
