import discord
from discord import app_commands
from discord.ext import commands

import config

HELP_CATEGORIES = {
    "general": {
        "title": "Справка по командам — Основное",
        "description": "Команды общей активности и информации:",
        "commands": [
            ("`/profile [участник]`", "Просмотр карточки профиля и статистики активности"),
            ("`/top [сортировка]`", "Таблица лидеров сервера (уровень, баланс, войс)"),
            ("`/info`", "Информация о боте и ссылки на ресурсы"),
            ("`/ping`", "Проверить текущую задержку бота"),
            ("`/help`", "Справка по всем командам бота"),
        ],
    },
    "economy": {
        "title": "Справка по командам — Экономика",
        "description": "Команды баланса и магазина:",
        "commands": [
            ("`/shop`", "Магазин Arvix за монеты"),
            ("`/give <участник> <сумма>`", "Выдать монеты пользователю"),
        ],
    },
    "moderation": {
        "title": "Справка по командам — Модерация",
        "description": "Команды контроля и выдачи наказаний:",
        "commands": [
            ("`/ban <участник> [причина] [срок] [доказательства]`", "Заблокировать пользователя"),
            ("`/unban <id_пользователя> [причина]`", "Разблокировать пользователя"),
            ("`/kick <участник> [причина] [доказательства]`", "Исключить пользователя с сервера"),
            ("`/mute <участник> [причина] [срок] [доказательства]`", "Выдать мут пользователю"),
            ("`/unmute <участник> [причина]`", "Снять мут с пользователя"),
            ("`/warn <участник> [причина] [доказательства]`", "Выдать предупреждение пользователю"),
        ],
    },
    "tickets_news": {
        "title": "Справка по командам — Новости",
        "description": "Публикации и объявления:",
        "commands": [
            ("`/news [упоминание]`", "Опубликовать новость в новостной канал"),
        ],
    },
    "admin": {
        "title": "Справка по командам — Администрирование",
        "description": "Команды настройки бота:",
        "commands": [
            ("`/settings`", "Панель настройки каналов и ролей бота"),
        ],
    },
}


class HelpSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Основное", value="general", description="Профиль, топ, информация, задержка"),
            discord.SelectOption(label="Экономика", value="economy", description="Магазин Arvix и выдача монет"),
            discord.SelectOption(label="Модерация", value="moderation", description="Бан, кик, мут, размут, варн"),
            discord.SelectOption(label="Новости", value="tickets_news", description="Публикация новостей"),
            discord.SelectOption(label="Администрирование", value="admin", description="Настройки бота на сервере"),
        ]
        super().__init__(
            placeholder="Выберите раздел команд…",
            options=options,
            custom_id="help:select_category",
        )

    async def callback(self, interaction: discord.Interaction):
        cat_key = self.values[0]
        cat_info = HELP_CATEGORIES.get(cat_key)
        if not cat_info:
            return await interaction.response.send_message("Раздел не найден.", ephemeral=True)

        embed = discord.Embed(
            title=cat_info["title"],
            description=cat_info["description"],
            color=config.BRAND_COLOR,
        )
        for cmd_name, cmd_desc in cat_info["commands"]:
            embed.add_field(name=cmd_name, value=cmd_desc, inline=False)

        await interaction.response.edit_message(embed=embed, view=self.view)


class HelpView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(HelpSelect())


class InfoButtonsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="Сайт", url="https://leaderswag.sampproject.ru/"))
        self.add_item(discord.ui.Button(label="Группа VK", url="https://vk.ru/club236581375"))


class Info(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="ping", description="Проверить задержку бота")
    async def ping(self, interaction: discord.Interaction):
        latency_ms = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"Понг! Задержка: `{latency_ms} мс`")

    @app_commands.command(name="info", description="О системе и наши ресурсы")
    async def info(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title=f"{config.BOT_NAME} — помощник лидерской системы",
            description=config.SYSTEM_DESC,
            color=config.BRAND_COLOR,
        )
        embed.add_field(
            name="Что умеет бот",
            value=(
                "• `/profile` — карточка активности\n"
                "• `/top` — рейтинг лидеров сервера\n"
                "• `/shop` — магазин ролей за монеты\n"
                "• Тикеты — обращения в поддержку\n"
                "• `/news` — новости сервера\n"
                "• Модерация — `/ban` `/kick` `/mute` `/unmute` `/unban`\n"
                "• Экономика — `/give`"
            ),
            inline=False,
        )
        embed.add_field(
            name="Наши ресурсы",
            value="\n".join(f"• [{label}]({url})" for label, url in config.LINKS),
            inline=False,
        )
        if self.bot.user:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        await interaction.response.send_message(embed=embed, view=InfoButtonsView())

    @app_commands.command(name="help", description="Справка по командам бота по разделам")
    async def help_cmd(self, interaction: discord.Interaction):
        default_cat = HELP_CATEGORIES["general"]
        embed = discord.Embed(
            title=default_cat["title"],
            description=default_cat["description"],
            color=config.BRAND_COLOR,
        )
        for cmd_name, cmd_desc in default_cat["commands"]:
            embed.add_field(name=cmd_name, value=cmd_desc, inline=False)

        await interaction.response.send_message(embed=embed, view=HelpView())


async def setup(bot):
    await bot.add_cog(Info(bot))
