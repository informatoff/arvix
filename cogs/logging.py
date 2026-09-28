from datetime import datetime, timezone, timedelta
from typing import Optional

import discord
from discord.ext import commands

import config

MSK = timezone(timedelta(hours=3))


def _now() -> str:
    """Время для футера: 12.09.2026 14:05 (МСК)."""
    return datetime.now(MSK).strftime("%d.%m.%Y %H:%M")


def _fmt_dt(dt: Optional[datetime]) -> str:
    """Дата в виде 20.03.2026 21:08:24 (МСК)."""
    if not dt:
        return "неизвестно"
    return dt.astimezone(MSK).strftime("%d.%m.%Y %H:%M:%S")


def _user_field(u: discord.abc.User) -> str:
    """<@id> (ник | ID: `id`)"""
    return f"{u.mention} ({u.name} | ID: `{u.id}`)"


def _footer(user_id: int) -> str:
    return f"ID пользователя: {user_id} • {_now()}"


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

    # ---------- вспомогательное ----------

    async def _member_log_channel(self, guild: discord.Guild):
        s = await self.bot.db.get_settings(guild.id)
        if not s:
            return None
        try:
            ch_id = s["memberlog_channel_id"]
        except (KeyError, IndexError):
            return None
        return guild.get_channel(ch_id) if ch_id else None

    async def _audit_actor(
        self,
        guild: discord.Guild,
        action: discord.AuditLogAction,
        target_id: int,
        max_age: int = 15,
    ):
        """Ищет в аудит-логе, кто совершил действие. Возвращает (user, reason)."""
        me = guild.me
        if not me or not me.guild_permissions.view_audit_log:
            return None, None
        try:
            async for entry in guild.audit_logs(limit=10, action=action):
                if getattr(entry.target, "id", None) != target_id:
                    continue
                age = (datetime.now(timezone.utc) - entry.created_at).total_seconds()
                if age > max_age:
                    continue
                return entry.user, entry.reason
        except discord.HTTPException:
            pass
        return None, None

    async def _send(self, ch, embed: discord.Embed):
        try:
            await ch.send(embed=embed)
        except discord.HTTPException:
            pass

    async def _db_event(self, guild_id, user_id, event, actor=None, reason=None, details=None):
        """Запись события в БД (не мешает логу, если что-то пошло не так)."""
        try:
            await self.bot.db.log_member_event(
                guild_id, user_id, event,
                actor_id=actor.id if actor else None,
                reason=reason,
                details=details,
            )
        except Exception:
            pass

    # ---------- вход: лог участников + приветствие ----------

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if not member.guild:
            return

        # запись в БД
        try:
            await self.bot.db.set_joined_at(member.guild.id, member.id, member.joined_at)
        except Exception:
            pass
        await self._db_event(member.guild.id, member.id, "join")

        # лог участников (включая ботов)
        mch = await self._member_log_channel(member.guild)
        if mch:
            embed = discord.Embed(
                title=f"👋 Новый участник — {member.name}",
                color=0x57F287,
            )
            embed.add_field(name="👤 Пользователь", value=_user_field(member), inline=False)
            embed.add_field(name="📅 Аккаунт создан", value=_fmt_dt(member.created_at), inline=False)
            embed.set_footer(text=_footer(member.id))
            await self._send(mch, embed)

        # приветствие
        if member.bot:
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

    # ---------- выход / кик ----------

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if not member.guild:
            return

        kicker, kick_reason = await self._audit_actor(
            member.guild, discord.AuditLogAction.kick, member.id
        )

        # запись в БД
        await self._db_event(
            member.guild.id, member.id,
            "kick" if kicker else "leave",
            actor=kicker, reason=kick_reason,
        )

        ch = await self._member_log_channel(member.guild)
        if not ch:
            return

        if kicker:
            embed = discord.Embed(
                title=f"👢 Участник исключён — {member.name}",
                color=0xFEE75C,
            )
            embed.add_field(name="👤 Пользователь", value=_user_field(member), inline=False)
            embed.add_field(
                name="📌 Причина",
                value=f"`{kick_reason}`" if kick_reason else "*Не указана*",
                inline=False,
            )
            embed.add_field(name="🛡️ Кто исключил", value=_user_field(kicker), inline=False)
        else:
            embed = discord.Embed(
                title=f"🚪 Сервер покинул — {member.name}",
                color=0xED4245,
            )
            embed.add_field(name="👤 Пользователь", value=_user_field(member), inline=False)
            embed.add_field(name="📌 Причина", value="👋 Сам покинул сервер", inline=False)

        embed.set_footer(text=_footer(member.id))
        await self._send(ch, embed)

    # ---------- роли и ник ----------

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if not after.guild:
            return

        roles_changed = before.roles != after.roles
        nick_changed = before.nick != after.nick
        if not (roles_changed or nick_changed):
            return

        ch = await self._member_log_channel(after.guild)

        if roles_changed:
            before_ids = {r.id for r in before.roles}
            after_ids = {r.id for r in after.roles}
            added = [r for r in after.roles if r.id not in before_ids]
            removed = [r for r in before.roles if r.id not in after_ids]

            if added or removed:
                actor, _ = await self._audit_actor(
                    after.guild, discord.AuditLogAction.member_role_update, after.id
                )

                # запись в БД
                for r in added:
                    await self._db_event(after.guild.id, after.id, "role_add", actor=actor, details=str(r.id))
                for r in removed:
                    await self._db_event(after.guild.id, after.id, "role_remove", actor=actor, details=str(r.id))

                if ch:
                    embed = discord.Embed(
                        title=f"🎭 Роли участника изменены — {after.name}",
                        color=0x5865F2,
                    )
                    embed.add_field(name="👤 Пользователь", value=_user_field(after), inline=False)
                    if added:
                        embed.add_field(
                            name="➕ Выданы роли",
                            value=" ".join(r.mention for r in added)[:1000],
                            inline=False,
                        )
                    if removed:
                        embed.add_field(
                            name="➖ Сняты роли",
                            value=" ".join(r.mention for r in removed)[:1000],
                            inline=False,
                        )
                    embed.add_field(
                        name="🛡️ Кто изменил",
                        value=_user_field(actor) if actor else "неизвестно",
                        inline=False,
                    )
                    embed.set_footer(text=_footer(after.id))
                    await self._send(ch, embed)

        if nick_changed:
            actor, _ = await self._audit_actor(
                after.guild, discord.AuditLogAction.member_update, after.id
            )

            await self._db_event(
                after.guild.id, after.id, "nick_change",
                actor=actor,
                details=f"{before.nick or ''} -> {after.nick or ''}",
            )

            if ch:
                embed = discord.Embed(
                    title=f"✏️ Ник участника изменён — {after.name}",
                    color=0xFEE75C,
                )
                embed.add_field(name="👤 Пользователь", value=_user_field(after), inline=False)
                embed.add_field(name="📝 Было", value=before.nick or "*без ника*", inline=True)
                embed.add_field(name="📝 Стало", value=after.nick or "*без ника*", inline=True)
                embed.add_field(
                    name="🛡️ Кто изменил",
                    value=_user_field(actor) if actor else "неизвестно",
                    inline=False,
                )
                embed.set_footer(text=_footer(after.id))
                await self._send(ch, embed)

    # ---------- аватар и имя пользователя ----------

    @commands.Cog.listener()
    async def on_user_update(self, before: discord.User, after: discord.User):
        avatar_changed = before.avatar != after.avatar
        name_changed = before.name != after.name
        gname_changed = before.global_name != after.global_name
        if not (avatar_changed or name_changed or gname_changed):
            return

        for guild in self.bot.guilds:
            member = guild.get_member(after.id)
            if not member:
                continue

            # запись в БД
            if avatar_changed:
                await self._db_event(guild.id, after.id, "avatar_change")
            if name_changed or gname_changed:
                await self._db_event(
                    guild.id, after.id, "name_change",
                    details=f"{before.name}/{before.global_name} -> {after.name}/{after.global_name}",
                )

            ch = await self._member_log_channel(guild)
            if not ch:
                continue

            if avatar_changed:
                embed = discord.Embed(
                    title=f"🖼️ Аватар изменён — {after.name}",
                    color=0x5865F2,
                )
                embed.add_field(name="👤 Пользователь", value=_user_field(member), inline=False)
                if before.avatar:
                    embed.add_field(
                        name="Было",
                        value=f"[ссылка]({before.avatar.replace(size=1024).url})",
                        inline=True,
                    )
                embed.add_field(
                    name="Стало",
                    value=f"[ссылка]({after.display_avatar.replace(size=1024).url})",
                    inline=True,
                )
                embed.set_thumbnail(url=after.display_avatar.url)
                embed.set_footer(text=_footer(after.id))
                await self._send(ch, embed)

            if name_changed or gname_changed:
                embed = discord.Embed(
                    title=f"🏷️ Имя изменено — {after.name}",
                    color=0xFEE75C,
                )
                embed.add_field(name="👤 Пользователь", value=_user_field(member), inline=False)
                if name_changed:
                    embed.add_field(name="Username было", value=f"`{before.name}`", inline=True)
                    embed.add_field(name="Username стало", value=f"`{after.name}`", inline=True)
                if gname_changed:
                    embed.add_field(
                        name="Отображаемое имя было",
                        value=before.global_name or "*нет*",
                        inline=False,
                    )
                    embed.add_field(
                        name="Отображаемое имя стало",
                        value=after.global_name or "*нет*",
                        inline=False,
                    )
                embed.set_footer(text=_footer(after.id))
                await self._send(ch, embed)

    # ---------- сообщения ----------

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
        embed.add_field(name="👤 Пользователь", value=_user_field(after.author), inline=False)
        embed.add_field(name="📍 Канал", value=after.channel.mention, inline=False)
        b_content = before.content[:1000] if before.content else "*Нет текста*"
        a_content = after.content[:1000] if after.content else "*Нет текста*"
        embed.add_field(name="📝 Было", value=b_content, inline=False)
        embed.add_field(name="📝 Стало", value=a_content, inline=False)
        embed.set_footer(text=f"ID сообщения: {after.id} • {_now()}")
        await self._send(ch, embed)

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
        embed.add_field(name="👤 Пользователь", value=_user_field(message.author), inline=False)
        embed.add_field(name="📍 Канал", value=message.channel.mention, inline=False)
        content = message.content[:1000] if message.content else "*[Вложение или пусто]*"
        embed.add_field(name="📝 Текст", value=content, inline=False)
        embed.set_footer(text=f"ID сообщения: {message.id} • {_now()}")
        await self._send(ch, embed)

    # ---------- войс ----------

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ):
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
            embed = discord.Embed(title=f"🔊 Подключение к войсу — {member.name}", color=0x57F287)
            embed.add_field(name="👤 Пользователь", value=_user_field(member), inline=False)
            embed.add_field(name="📍 Канал", value=after.channel.mention, inline=False)
        elif before.channel is not None and after.channel is None:
            embed = discord.Embed(title=f"🔇 Отключение от войса — {member.name}", color=0xED4245)
            embed.add_field(name="👤 Пользователь", value=_user_field(member), inline=False)
            embed.add_field(name="📍 Канал", value=before.channel.mention, inline=False)
        elif before.channel != after.channel and before.channel is not None and after.channel is not None:
            embed = discord.Embed(title=f"🔄 Перемещение по войсам — {member.name}", color=0x5865F2)
            embed.add_field(name="👤 Пользователь", value=_user_field(member), inline=False)
            embed.add_field(name="📍 Было", value=before.channel.mention, inline=True)
            embed.add_field(name="📍 Стало", value=after.channel.mention, inline=True)

        if embed:
            embed.set_footer(text=_footer(member.id))
            await self._send(ch, embed)


async def setup(bot):
    await bot.add_cog(Logging(bot))
