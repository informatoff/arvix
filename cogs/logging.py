from datetime import datetime, timezone, timedelta
import discord
from discord.ext import commands

import config

MSK = timezone(timedelta(hours=3))


def _ts() -> str:
    return datetime.now(MSK).strftime("Сегодня, в %H:%M")


class MemberCountView(discord.ui.View):
    def __init__(self, count: int):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label=f"Вы стали {count}-м участником!",
                style=discord.ButtonStyle.secondary,
                disabled=True,
            )
        )


class Logging(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot or not member.guild:
            return

        s = await self.bot.db.get_settings(member.guild.id)
        if not s or not s["welcome_channel_id"]:
            return

        ch = member.guild.get_channel(s["welcome_channel_id"])
        if not ch:
            return

        guild_name = member.guild.name
        embed = discord.Embed(
            title=f"Добро пожаловать на Discord сервер {guild_name}!",
            description=(
                f"**Друг, приветствуем тебя на Discord сервере проекта {guild_name}!**\n\n"
                "Тут ты сможешь погрузиться в удивительный мир Лидерской системы Arvix!\n"
                "Наше сообщество состоит из людей, увлеченных игрой, которые ценят дружелюбие, творчество и взаимопомощь.\n"
                "Здесь ты найдешь множество возможностей для общения, игры и взаимодействия с другими участниками. "
                "Не стесняйся задавать вопросы и присоединяться к нашим событиям.\n\n"
                "Вся основная информация и управление находятся на нашем сайте, а новости публикуются в группе ВКонтакте."
            ),
            color=0xFFFFFF,
        )
        view = MemberCountView(member.guild.member_count)
        try:
            await ch.send(content=member.mention, embed=embed, view=view)
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if after.author.bot or not after.guild:
            return
        if before.content == after.content:
            return

        s = await self.bot.db.get_settings(after.guild.id)
        if not s or not s["msglog_channel_id"]:
            return

        ch = after.guild.get_channel(s["msglog_channel_id"])
        if not ch:
            return

        embed = discord.Embed(
            title=f"✏️ Сообщение изменено — {after.author.name}",
            color=0xFEE75C,
        )
        embed.add_field(
            name="👤 Пользователь",
            value=f"{after.author.mention} ({after.author.display_name} | ID: `{after.author.id}`)",
            inline=False,
        )
        embed.add_field(name="📍 Канал", value=after.channel.mention, inline=False)
        b_content = before.content[:1000] if before.content else "*Нет текста*"
        a_content = after.content[:1000] if after.content else "*Нет текста*"
        embed.add_field(name="📝 Было", value=b_content, inline=False)
        embed.add_field(name="📝 Стало", value=a_content, inline=False)
        embed.set_footer(text=f"ID сообщения: {after.id} • {_ts()}")

        try:
            await ch.send(embed=embed)
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        s = await self.bot.db.get_settings(message.guild.id)
        if not s or not s["msglog_channel_id"]:
            return

        ch = message.guild.get_channel(s["msglog_channel_id"])
        if not ch:
            return

        embed = discord.Embed(
            title=f"🗑️ Сообщение удалено — {message.author.name}",
            color=0xED4245,
        )
        embed.add_field(
            name="👤 Пользователь",
            value=f"{message.author.mention} ({message.author.display_name} | ID: `{message.author.id}`)",
            inline=False,
        )
        embed.add_field(name="📍 Канал", value=message.channel.mention, inline=False)
        content = message.content[:1000] if message.content else "*[Вложение или пусто]*"
        embed.add_field(name="📝 Текст", value=content, inline=False)
        embed.set_footer(text=f"ID сообщения: {message.id} • {_ts()}")

        try:
            await ch.send(embed=embed)
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot or not member.guild:
            return

        s = await self.bot.db.get_settings(member.guild.id)
        if not s or not s["voicelog_channel_id"]:
            return

        ch = member.guild.get_channel(s["voicelog_channel_id"])
        if not ch:
            return

        embed = None
        if before.channel is None and after.channel is not None:
            embed = discord.Embed(
                title=f"🔊 Подключение к войсу — {member.name}",
                color=0x57F287,
            )
            embed.add_field(
                name="👤 Пользователь",
                value=f"{member.mention} ({member.display_name} | ID: `{member.id}`)",
                inline=False,
            )
            embed.add_field(name="📍 Канал", value=after.channel.mention, inline=False)
            embed.set_footer(text=_ts())
        elif before.channel is not None and after.channel is None:
            embed = discord.Embed(
                title=f"🔇 Отключение от войса — {member.name}",
                color=0xED4245,
            )
            embed.add_field(
                name="👤 Пользователь",
                value=f"{member.mention} ({member.display_name} | ID: `{member.id}`)",
                inline=False,
            )
            embed.add_field(name="📍 Канал", value=before.channel.mention, inline=False)
            embed.set_footer(text=_ts())
        elif before.channel != after.channel and before.channel is not None and after.channel is not None:
            embed = discord.Embed(
                title=f"🔄 Перемещение по войсам — {member.name}",
                color=0x5865F2,
            )
            embed.add_field(
                name="👤 Пользователь",
                value=f"{member.mention} ({member.display_name} | ID: `{member.id}`)",
                inline=False,
            )
            embed.add_field(name="📍 Было", value=before.channel.mention, inline=True)
            embed.add_field(name="📍 Стало", value=after.channel.mention, inline=True)
            embed.set_footer(text=_ts())

        if embed:
            try:
                await ch.send(embed=embed)
            except discord.HTTPException:
                pass


async def setup(bot):
    await bot.add_cog(Logging(bot))
