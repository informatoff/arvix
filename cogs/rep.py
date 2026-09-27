from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands

REP_CHANNEL_ID = 1553843988090589295
MSK = timezone(timedelta(hours=3))

STAR_OPTIONS = [
    ("★★★★★", 5),
    ("★★★★☆", 4),
    ("★★★☆☆", 3),
    ("★★☆☆☆", 2),
    ("★☆☆☆☆", 1),
]


def _stars_display(rating: int) -> str:
    return "★" * rating + "☆" * (5 - rating)


def _ts() -> str:
    return datetime.now(MSK)


class RepModal(discord.ui.Modal, title="Оставить отзыв"):
    nickname = discord.ui.TextInput(
        label="Ваш ник",
        placeholder="Например: Noim Nurzhanov",
        max_length=100,
    )
    review_text = discord.ui.TextInput(
        label="Ваш отзыв",
        style=discord.TextStyle.paragraph,
        placeholder="Расскажите, что вам понравилось или не понравилось…",
        max_length=1000,
        required=False,
    )

    def __init__(self, rating: int):
        super().__init__()
        self.rating = rating

    async def on_submit(self, interaction: discord.Interaction):
        text = self.review_text.value.strip() if self.review_text.value else ""
        if not text:
            text = "Решил промолчать"

        embed = discord.Embed(
            color=discord.Color.from_rgb(255, 255, 255),
        )
        embed.description = f"{_stars_display(self.rating)}\n\n{text}"
        embed.set_footer(text=self.nickname.value.strip())
        embed.timestamp = _ts()

        channel = interaction.guild.get_channel(REP_CHANNEL_ID) if interaction.guild else None
        if not channel:
            try:
                channel = await interaction.client.fetch_channel(REP_CHANNEL_ID)
            except discord.HTTPException:
                channel = None

        if not channel:
            return await interaction.response.send_message(
                "Не удалось найти канал для отзывов. Обратитесь к администрации.", ephemeral=True
            )

        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            return await interaction.response.send_message(
                "Не удалось отправить отзыв — проверьте права бота в канале отзывов.", ephemeral=True
            )

        await interaction.response.send_message("Спасибо за ваш отзыв! ✅", ephemeral=True)


class StarSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=label, value=str(value))
            for label, value in STAR_OPTIONS
        ]
        super().__init__(
            placeholder="Выберите оценку…",
            options=options,
            custom_id="rep:select_stars",
        )

    async def callback(self, interaction: discord.Interaction):
        rating = int(self.values[0])
        await interaction.response.send_modal(RepModal(rating))


class StarSelectView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=120)
        self.author_id = author_id
        self.add_item(StarSelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Это меню открыто для другого пользователя.", ephemeral=True
            )
            return False
        return True


class Rep(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="rep", description="Оставить отзыв о нас")
    async def rep(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "Выберите оценку от 1 до 5 звёзд:",
            view=StarSelectView(interaction.user.id),
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(Rep(bot))
