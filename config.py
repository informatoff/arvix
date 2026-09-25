import os

from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
DEV_GUILD_ID = int(os.getenv("DEV_GUILD_ID") or 0) or None
DB_PATH = os.getenv("DB_PATH", "arvix.db")

BRAND_COLOR = 0x7C5CFF
SUCCESS_COLOR = 0x43B581
WARN_COLOR = 0xFAA61A
DANGER_COLOR = 0xF04747
WHITE_COLOR = 0xFFFFFF
LOG_COLOR = 0x2B2D31

XP_COOLDOWN = 60
XP_RANGE = (15, 25)
MESSAGE_COINS = 1
VOICE_XP = 10
VOICE_COINS = 1
VOICE_MIN_MEMBERS = 1

BOT_NAME = "Arvix"
SYSTEM_DESC = (
    "Лидерская система — единое место для работы лидеров: вся основная "
    "информация и управление находятся на сайте, а новости и обновления "
    "публикуются в нашей группе ВКонтакте."
)
LINKS = [
    ("Сайт", "https://leaderswag.sampproject.ru/"),
    ("Группа VK", "https://vk.ru/club236581375"),
    ("Разработчик · syndicq", "https://vk.ru/syndicq"),
    ("Разработчик · gonzalezez", "https://vk.ru/gonzalezez"),
]
