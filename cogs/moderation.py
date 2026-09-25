import re
from datetime import datetime, timezone, timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import config

MSK = timezone(timedelta(hours=3))

ACTION_COLORS = {
    "BAN":        0xED4245,
    "UNBAN":      0x57F287,
    "KICK":       0xFEE75C,
    "MUTE":       0xFEE75C,
    "UNMUTE":     0x57F287,
    "WARN":       0xFF7518,
    "TICKET-BAN": 0xED4245,
}

ACTION_LABELS = {
    "Кик": "KICK", "Мут": "MUTE", "Размут": "UNMUTE",
    "Бан": "BAN", "Разбан": "UNBAN",
    "Предупреждение": "WARN", "Тикет-бан": "TICKET-BAN",
}


def _ts() -> str:
    return datetime.now(MSK).strftime("Сегодня, в %H:%M")


DURATION_RE = re.compile(r"(\d+)\s*([smhdсмчд])")
UNIT_SECONDS = {"s": 1, "с": 1, "m": 60, "м": 60, "h": 3600, "ч": 3600, "d": 86400, "д": 86400}
MAX_TIMEOUT = timedelta(days=28)


def format_duration(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)

    def _ru_days(n):
        if n % 10 == 1 and n % 100 != 11: return f"{n} день"
        if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14): return f"{n} дня"
        return f"{n} дней"

    def _ru_hours(n):
        if n % 10 == 1 and n % 100 != 11: return f"{n} час"
        if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14): return f"{n} часа"
        return f"{n} часов"

    def _ru_mins(n):
        if n % 10 == 1 and n % 100 != 11: return f"{n} минута"
        if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14): return f"{n} минуты"
        return f"{n} минут"

    parts = []
    if days: parts.append(_ru_days(days))
    if hours: parts.append(_ru_hours(hours))
    if minutes and not days: parts.append(_ru_mins(minutes))
    return " ".join(parts) or "меньше минуты"


def parse_duration(text: str) -> timedelta | None:
    parts = DURATION_RE.findall(text.lower())
    if not parts:
        return None
    return timedelta(seconds=sum(int(n) * UNIT_SECONDS[u] for n, u in parts))


def hierarchy_error(interaction: discord.Interaction, target: discord.Member) -> str | None:
    guild, me = interaction.guild, interaction.guild.me
    if target.id == interaction.user.id:
        return "Нельзя применить это к самому себе."
    if target.id == guild.owner_id:
        return "Нельзя наказывать владельца сервера."
    if target.id == me.id:
        return "Себя я наказывать не буду."
    if interaction.user.id != guild.owner_id and target.top_role >= interaction.user.top_role:
        return "Роль участника выше или равна твоей."
    if target.top_role >= me.top_role:
        return "Моя роль ниже роли участника — поднимите роль бота выше."
    return None


def punishment_log_embed(
    action: str,
    moderator: discord.abc.User,
    target: discord.abc.User,
    reason: str,
    duration_str: Optional[str] = None,
) -> discord.Embed:
    label = ACTION_LABELS.get(action, action.upper())
    color = ACTION_COLORS.get(label, 0x839496)
    embed = discord.Embed(color=color)
    embed.set_author(name=label)
    embed.add_field(name="Модератор", value=f"{moderator.mention} `[{moderator.id}]`", inline=False)
    embed.add_field(name="Пользователь", value=f"{target.mention} `[{target.id}]`", inline=False)
    embed.add_field(name="Причина", value=f"`{reason or 'Не указана'}`", inline=False)
    if duration_str:
        embed.add_field(name="Срок", value=duration_str, inline=False)
    embed.set_footer(text=_ts())
    return embed


def dm_embed(
    guild_name: str,
    action: str,
    reason: str,
    duration_str: Optional[str] = None,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"Ты получил наказание на сервере {guild_name}",
        color=0xFFFFFF,
    )
    value = f"**Причина: {reason or 'Не указана'}**"
    if duration_str:
        value += f"\n**Срок: {duration_str}**"
    embed.add_field(name=f"Тип наказания: {action}", value=value, inline=False)
    embed.set_footer(text=_ts())
    return embed


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _send_modlog(self, guild: discord.Guild, embed: discord.Embed):
        s = await self.bot.db.get_settings(guild.id)
        if s and s["modlog_channel_id"]:
            channel = guild.get_channel(s["modlog_channel_id"])
            if channel:
                try:
                    await channel.send(embed=embed)
                except discord.HTTPException:
                    pass

    async def _dm(self, member: discord.User | discord.Member, guild_name: str,
                  action: str, reason: str, duration_str: Optional[str] = None):
        try:
            await member.send(embed=dm_embed(guild_name, action, reason, duration_str))
        except discord.HTTPException:
            pass

    @app_commands.command(name="mute", description="Выдать мут участнику (тайм-аут)")
    @app_commands.describe(
        member="Кого замутить",
        duration="Срок: 30m, 2h, 1d, 1h30m (максимум 28д)",
        reason="Причина наказания",
    )
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.checks.bot_has_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def mute(
        self, interaction: discord.Interaction, member: discord.Member,
        duration: str, reason: str = "Не указана",
    ):
        if err := hierarchy_error(interaction, member):
            return await interaction.response.send_message(err, ephemeral=True)
        delta = parse_duration(duration)
        if not delta or delta > MAX_TIMEOUT:
            return await interaction.response.send_message(
                "Неверный срок. Примеры: `30m`, `2h`, `1d`, `1h30m` (максимум 28 дней).",
                ephemeral=True,
            )
        await interaction.response.defer(ephemeral=True)
        dur_str = format_duration(delta)

        await member.timeout(delta, reason=f"{interaction.user}: {reason}")
        await self._dm(member, interaction.guild.name, "Мут", reason, duration_str=dur_str)

        await interaction.followup.send(
            f"✅ Вы успешно выдали наказание (мут) для {member.mention}.",
            ephemeral=True,
        )

        embed = punishment_log_embed("Мут", interaction.user, member, reason, dur_str)
        await self._send_modlog(interaction.guild, embed)

    @app_commands.command(name="unmute", description="Снять мут с участника")
    @app_commands.describe(member="С кого снять мут", reason="Причина снятия")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.checks.bot_has_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def unmute(
        self, interaction: discord.Interaction, member: discord.Member,
        reason: str = "Не указана",
    ):
        if not member.is_timed_out():
            return await interaction.response.send_message(
                "У этого участника нет мута.", ephemeral=True
            )
        await interaction.response.defer(ephemeral=True)
        await member.timeout(None, reason=f"{interaction.user}: {reason}")

        await self._dm(member, interaction.guild.name, "Размут", reason)
        await interaction.followup.send(
            f"✅ Вы успешно сняли мут с {member.mention}.",
            ephemeral=True,
        )

        embed = punishment_log_embed("Размут", interaction.user, member, reason)
        await self._send_modlog(interaction.guild, embed)

    @app_commands.command(name="kick", description="Исключить участника с сервера")
    @app_commands.describe(member="Кого исключить", reason="Причина исключения")
    @app_commands.default_permissions(kick_members=True)
    @app_commands.checks.has_permissions(kick_members=True)
    @app_commands.checks.bot_has_permissions(kick_members=True)
    @app_commands.guild_only()
    async def kick(
        self, interaction: discord.Interaction, member: discord.Member,
        reason: str = "Не указана",
    ):
        if err := hierarchy_error(interaction, member):
            return await interaction.response.send_message(err, ephemeral=True)
        await interaction.response.defer(ephemeral=True)

        await self._dm(member, interaction.guild.name, "Кик", reason)
        await member.kick(reason=f"{interaction.user}: {reason}")

        await interaction.followup.send(
            f"✅ Вы успешно исключили {member.mention}.",
            ephemeral=True,
        )

        embed = punishment_log_embed("Кик", interaction.user, member, reason)
        await self._send_modlog(interaction.guild, embed)

    @app_commands.command(name="ban", description="Заблокировать участника на сервере")
    @app_commands.describe(
        member="Кого забанить",
        reason="Причина бана",
        delete_days="Удалить сообщения за N дней (0–7)",
    )
    @app_commands.default_permissions(ban_members=True)
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.checks.bot_has_permissions(ban_members=True)
    @app_commands.guild_only()
    async def ban(
        self, interaction: discord.Interaction, member: discord.Member,
        reason: str = "Не указана",
        delete_days: app_commands.Range[int, 0, 7] = 0,
    ):
        if err := hierarchy_error(interaction, member):
            return await interaction.response.send_message(err, ephemeral=True)
        await interaction.response.defer(ephemeral=True)

        await self._dm(member, interaction.guild.name, "Бан", reason)
        await member.ban(
            reason=f"{interaction.user}: {reason}",
            delete_message_seconds=delete_days * 86400,
        )

        await interaction.followup.send(
            f"✅ Вы успешно заблокировали {member.mention}.",
            ephemeral=True,
        )

        embed = punishment_log_embed("Бан", interaction.user, member, reason)
        await self._send_modlog(interaction.guild, embed)

    @app_commands.command(name="unban", description="Разблокировать пользователя по ID")
    @app_commands.describe(user_id="ID пользователя", reason="Причина разбана")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.checks.bot_has_permissions(ban_members=True)
    @app_commands.guild_only()
    async def unban(
        self, interaction: discord.Interaction, user_id: str,
        reason: str = "Не указана",
    ):
        if not user_id.isdigit():
            return await interaction.response.send_message(
                "Укажите числовой ID пользователя.", ephemeral=True
            )
        await interaction.response.defer(ephemeral=True)
        user = discord.Object(id=int(user_id))
        try:
            entry = await interaction.guild.fetch_ban(user)
        except discord.NotFound:
            return await interaction.followup.send(
                "Этого пользователя нет в списке банов.", ephemeral=True
            )
        await interaction.guild.unban(user, reason=f"{interaction.user}: {reason}")

        await interaction.followup.send(
            f"✅ Вы успешно разбанили {entry.user}.",
            ephemeral=True,
        )

        embed = punishment_log_embed("Разбан", interaction.user, entry.user, reason)
        await self._send_modlog(interaction.guild, embed)

    @app_commands.command(name="warn", description="Выдать предупреждение участнику")
    @app_commands.describe(member="Кому выдать", reason="Причина предупреждения")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def warn(
        self, interaction: discord.Interaction, member: discord.Member,
        reason: str = "Не указана",
    ):
        if err := hierarchy_error(interaction, member):
            return await interaction.response.send_message(err, ephemeral=True)
        await interaction.response.defer(ephemeral=True)

        await self._dm(member, interaction.guild.name, "Предупреждение", reason)

        await interaction.followup.send(
            f"✅ Предупреждение выдано {member.mention}.",
            ephemeral=True,
        )

        embed = punishment_log_embed("Предупреждение", interaction.user, member, reason)
        await self._send_modlog(interaction.guild, embed)


async def setup(bot):
    await bot.add_cog(Moderation(bot))
