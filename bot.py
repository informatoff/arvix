import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
from db import Database
from utils.fonts import ensure_fonts

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("arvix")

EXTENSIONS = (
    "cogs.admin",
    "cogs.moderation",
    "cogs.profile",
    "cogs.news",
    "cogs.tickets",
    "cogs.info",
    "cogs.top",
    "cogs.economy",
    "cogs.logging",
)


async def on_tree_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "У тебя недостаточно прав для этой команды."
    elif isinstance(error, app_commands.BotMissingPermissions):
        msg = "Мне не хватает прав: " + ", ".join(error.missing_permissions)
    elif isinstance(error, app_commands.NoPrivateMessage):
        msg = "Эта команда работает только на сервере."
    else:
        log.exception("Ошибка команды", exc_info=error)
        msg = "Что-то пошло не так. Попробуй ещё раз."
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


class Arvix(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            max_messages=5000,
            help_command=None,
        )
        self.db = Database(config.DB_PATH)
        self.tree.on_error = on_tree_error

    async def setup_hook(self):
        await self.db.connect()
        await asyncio.to_thread(ensure_fonts)
        for ext in EXTENSIONS:
            try:
                await self.load_extension(ext)
            except Exception:
                log.exception("Не удалось загрузить %s", ext)
        await self.tree.sync()
        if config.DEV_GUILD_ID:
            guild = discord.Object(id=config.DEV_GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)

    async def on_ready(self):
        log.info("Arvix запущен как %s", self.user)

    async def close(self):
        await self.db.close()
        await super().close()


if __name__ == "__main__":
    if not config.TOKEN:
        raise SystemExit("Укажи DISCORD_TOKEN в файле .env")
    Arvix().run(config.TOKEN)
