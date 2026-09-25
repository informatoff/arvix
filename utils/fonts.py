import logging
import urllib.request
from pathlib import Path

log = logging.getLogger("arvix.fonts")

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
VARIABLE_FONT = FONT_DIR / "Montserrat.ttf"
URLS = (
    "https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat%5Bwght%5D.ttf",
    "https://raw.githubusercontent.com/google/fonts/main/ofl/montserrat/Montserrat%5Bwght%5D.ttf",
)


def has_montserrat() -> bool:
    return VARIABLE_FONT.exists() or any(FONT_DIR.glob("Montserrat-*.ttf"))


def ensure_fonts() -> None:
    if has_montserrat():
        return
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    for url in URLS:
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                data = resp.read()
            if len(data) > 100_000:
                VARIABLE_FONT.write_bytes(data)
                log.info("Montserrat скачан в %s", VARIABLE_FONT)
                return
        except Exception as exc:
            log.warning("Не удалось скачать шрифт (%s): %s", url, exc)
    log.warning("Montserrat не найден — положи Montserrat.ttf в assets/fonts вручную")
