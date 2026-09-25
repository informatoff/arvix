from datetime import datetime, timezone, timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import config

MSK = timezone(timedelta(hours=3))

PING_CHOICES = [
    app_commands.Choice(name="Без упоминания", value="none"),
    app_commands.Choice(name="@everyone", value="everyone"),
    app_commands.Choice(name="@here", value="here"),
]


def build_embed(title: str, body: str, image: str | None):
    embed = discord.Embed(
        title=title,
        description=body,
        color=0x5865F2,
    )
    if image and image.startswith(("http://", "https://")):
        embed.set_image(url=image)
    embed.set_footer(text=datetime.now(MSK).strftime("%d.%m.%Y %H:%M"))
    return embed


class ConfirmView(discord.ui.View):
    def __init__(self, author_id: int, channel: discord.TextChannel, embed: discord.Embed, ping: str):
        super().__init__(timeout=600)
        self.author_id, self.channel, self.embed, self.ping = author_id, channel, embed, ping

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author_id

    @discord.ui.button(label="Опубликовать", style=discord.ButtonStyle.success)
    async def publish(self, interaction: discord.Interaction, button: discord.ui.Button):
        content, mentions = None, discord.AllowedMentions.none()
        if self.ping in ("everyone", "here"):
            content, mentions = f"@{self.ping}", discord.AllowedMentions(everyone=True)
        try:
            msg = await self.channel.send(content=content, embed=self.embed, allowed_mentions=mentions)
        except discord.HTTPException:
            return await interaction.response.edit_message(
                content=f"Не удалось отправить в {self.channel.mention} — проверь мои права.",
                embed=None, view=None,
            )
        if self.channel.is_news():
            try:
                await msg.publish()
            except discord.HTTPException:
                pass
        await interaction.response.edit_message(content=f"Опубликовано: {msg.jump_url}", embed=None, view=None)
        self.stop()

    @discord.ui.button(label="Отмена", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Отменено.", embed=None, view=None)
        self.stop()


class NewsModal(discord.ui.Modal, title="Новая новость"):
    heading = discord.ui.TextInput(label="Заголовок", max_length=200)
    body = discord.ui.TextInput(
        label="Текст новости",
        style=discord.TextStyle.paragraph,
        max_length=4000,
        placeholder="**жирный**  *курсив*  __подчёркнутый__  > цитата  ||спойлер||  - список",
    )
    image = discord.ui.TextInput(label="Ссылка на картинку (необязательно)", required=False, max_length=500)

    def __init__(self, channel: discord.TextChannel, ping: str):
        super().__init__()
        self.channel, self.ping = channel, ping

    async def on_submit(self, interaction: discord.Interaction):
        embed = build_embed(
            self.heading.value, self.body.value, self.image.value.strip() or None
        )
        view = ConfirmView(interaction.user.id, self.channel, embed, self.ping)
        await interaction.response.send_message(
            f"Предпросмотр. Публикую в {self.channel.mention}:", embed=embed, view=view, ephemeral=True
        )


class News(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="news", description="Опубликовать новость в новостной канал")
    @app_commands.describe(ping="Кого упомянуть в новости")
    @app_commands.choices(ping=PING_CHOICES)
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def news(self, interaction: discord.Interaction, ping: Optional[app_commands.Choice[str]] = None):
        s = await self.bot.db.get_settings(interaction.guild_id)
        channel = interaction.guild.get_channel(s["news_channel_id"]) if s and s["news_channel_id"] else None
        if not channel:
            return await interaction.response.send_message(
                "Новостной канал не задан. Настройте его через `/settings`.", ephemeral=True
            )
        await interaction.response.send_modal(NewsModal(channel, ping.value if ping else "none"))


async def setup(bot):
    await bot.add_cog(News(bot))
