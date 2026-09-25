import discord
from discord import app_commands
from discord.ext import commands

import config

SETTING_MAP = {
    "news_channel_id":            ("Канал новостей", "channel", [discord.ChannelType.text]),
    "welcome_channel_id":         ("Канал приветствий", "channel", [discord.ChannelType.text]),
    "modlog_channel_id":          ("Канал модлога", "channel", [discord.ChannelType.text]),
    "msglog_channel_id":          ("Канал логов сообщений", "channel", [discord.ChannelType.text]),
    "voicelog_channel_id":        ("Канал логов войса", "channel", [discord.ChannelType.text]),
    "levelup_channel_id":         ("Канал уровней", "channel", [discord.ChannelType.text]),
    "ticket_category_id":         ("Категория тикетов", "channel", [discord.ChannelType.category]),
    "ticket_role_id":             ("Роль поддержки", "role", None),
    "ticket_log_channel_id":      ("Канал логов тикетов", "channel", [discord.ChannelType.text]),
    "ticket_archive_category_id": ("Категория архива тикетов", "channel", [discord.ChannelType.category]),
    "give_role_id":               ("Роль для /give", "role", None),
}


def _build_settings_embed(settings) -> discord.Embed:
    embed = discord.Embed(
        title="⚙️ Настройки бота",
        description="Выберите параметр для настройки в меню ниже.",
        color=config.BRAND_COLOR,
    )
    for key, (label, typ, _) in SETTING_MAP.items():
        val = settings[key] if settings and settings[key] else None
        if typ == "role":
            display = f"<@&{val}>" if val else "не задана"
        elif "category" in key:
            display = f"<#{val}>" if val else "не задана"
        else:
            display = f"<#{val}>" if val else "не задан"
        embed.add_field(name=label, value=display, inline=True)
    return embed


class SettingPickerSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=label, value=key)
            for key, (label, _, _) in SETTING_MAP.items()
        ]
        super().__init__(
            placeholder="Выберите настройку…",
            options=options,
            custom_id="settings:picker",
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        key = self.values[0]
        label, typ, ch_types = SETTING_MAP[key]
        view = SettingValueView(key, label)
        if typ == "channel":
            view.add_item(ChannelValueSelect(key, ch_types))
        else:
            view.add_item(RoleValueSelect(key))
        embed = discord.Embed(
            title=f"Настройка: {label}",
            description="Выберите значение ниже или нажмите **Назад**.",
            color=config.BRAND_COLOR,
        )
        await interaction.response.edit_message(embed=embed, view=view)


class ChannelValueSelect(discord.ui.ChannelSelect):
    def __init__(self, setting_key: str, ch_types: list):
        super().__init__(
            placeholder="Выберите канал или категорию…",
            channel_types=ch_types,
            row=1,
        )
        self.setting_key = setting_key

    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0]
        await interaction.client.db.set_settings(
            interaction.guild_id, **{self.setting_key: channel.id}
        )
        s = await interaction.client.db.get_settings(interaction.guild_id)
        embed = _build_settings_embed(s)
        await interaction.response.edit_message(embed=embed, view=MainSettingsView())


class RoleValueSelect(discord.ui.RoleSelect):
    def __init__(self, setting_key: str):
        super().__init__(placeholder="Выберите роль…", row=1)
        self.setting_key = setting_key

    async def callback(self, interaction: discord.Interaction):
        role = self.values[0]
        await interaction.client.db.set_settings(
            interaction.guild_id, **{self.setting_key: role.id}
        )
        s = await interaction.client.db.get_settings(interaction.guild_id)
        embed = _build_settings_embed(s)
        await interaction.response.edit_message(embed=embed, view=MainSettingsView())


class BackButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Назад", style=discord.ButtonStyle.secondary, row=2)

    async def callback(self, interaction: discord.Interaction):
        s = await interaction.client.db.get_settings(interaction.guild_id)
        embed = _build_settings_embed(s)
        await interaction.response.edit_message(embed=embed, view=MainSettingsView())


class SettingValueView(discord.ui.View):
    def __init__(self, key: str, label: str):
        super().__init__(timeout=300)
        self.add_item(BackButton())


class MainSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(SettingPickerSelect())


class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="settings", description="Настройки бота")
    @app_commands.guild_only()
    async def settings_cmd(self, interaction: discord.Interaction):
        s = await self.bot.db.get_settings(interaction.guild_id)
        embed = _build_settings_embed(s)
        await interaction.response.send_message(
            embed=embed, view=MainSettingsView(), ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(Admin(bot))
