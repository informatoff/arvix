import logging
import urllib.request
from pathlib import Path

log = logging.getLogger("arvix.fonts")

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

# ---------- Montserrat (основной) ----------
VARIABLE_FONT = FONT_DIR / "Montserrat.ttf"
MONTSERRAT_URLS = (
    "https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat%5Bwght%5D.ttf",
    "https://raw.githubusercontent.com/google/fonts/main/ofl/montserrat/Montserrat%5Bwght%5D.ttf",
)

# ---------- DejaVu Sans (запасной: small caps и прочие символы) ----------
DEJAVU_BOLD = FONT_DIR / "DejaVuSans-Bold.ttf"
DEJAVU_REGULAR = FONT_DIR / "DejaVuSans.ttf"
DEJAVU_URLS = {
    DEJAVU_BOLD: (
        "https://github.com/dejavu-fonts/dejavu-fonts/raw/version_2_37/ttf/DejaVuSans-Bold.ttf",
        "https://raw.githubusercontent.com/dejavu-fonts/dejavu-fonts/version_2_37/ttf/DejaVuSans-Bold.ttf",
    ),
    DEJAVU_REGULAR: (
        "https://github.com/dejavu-fonts/dejavu-fonts/raw/version_2_37/ttf/DejaVuSans.ttf",
        "https://raw.githubusercontent.com/dejavu-fonts/dejavu-fonts/version_2_37/ttf/DejaVuSans.ttf",
    ),
}


def has_montserrat() -> bool:
    return VARIABLE_FONT.exists() or any(FONT_DIR.glob("Montserrat-*.ttf"))


def has_fallback() -> bool:
    return DEJAVU_BOLD.exists() or DEJAVU_REGULAR.exists() or any(FONT_DIR.glob("Noto*.ttf"))


def _download(urls, target: Path, name: str) -> bool:
    for url in urls:
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                data = resp.read()
            if len(data) > 100_000:
                target.write_bytes(data)
                log.info("%s скачан в %s", name, target)
                return True
        except Exception as exc:
            log.warning("Не удалось скачать %s (%s): %s", name, url, exc)
    return False


def ensure_fonts() -> None:
    FONT_DIR.mkdir(parents=True, exist_ok=True)

    if not has_montserrat():
        if not _download(MONTSERRAT_URLS, VARIABLE_FONT, "Montserrat"):
            log.warning("Montserrat не найден — положи Montserrat.ttf в assets/fonts вручную")

    if not has_fallback():
        ok = False
        for target, urls in DEJAVU_URLS.items():
            ok = _download(urls, target, target.name) or ok
        if not ok:
            log.warning("DejaVuSans не найден — положи DejaVuSans-Bold.ttf в assets/fonts вручную")
