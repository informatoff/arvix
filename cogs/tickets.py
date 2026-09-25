import asyncio
import re
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands

import config
from utils.transcript import build_html_transcript

MSK = timezone(timedelta(hours=3))


def _ts() -> str:
    return datetime.now(MSK).strftime("Сегодня, в %H:%M")


def _find_links(text: str) -> str:
    urls = re.findall(r'https?://\S+', text or "")
    return "\n".join(urls) if urls else "❌"


def _is_support(interaction: discord.Interaction, settings) -> bool:
    perms = interaction.user.guild_permissions
    if perms.administrator or perms.manage_channels:
        return True
    role_id = settings["ticket_role_id"] if settings else None
    return bool(role_id and interaction.user.get_role(role_id))


class TicketModal(discord.ui.Modal, title="Создание тикета"):
    topic = discord.ui.TextInput(
        label="Тема обращения", max_length=100, placeholder="Кратко: что случилось?"
    )
    details = discord.ui.TextInput(
        label="Подробности", style=discord.TextStyle.paragraph,
        max_length=1500, required=False,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        db, guild, user = interaction.client.db, interaction.guild, interaction.user

        s = await db.get_settings(guild.id)
        cat_id = s["ticket_category_id"] if s and s["ticket_category_id"] else None
        role_id = s["ticket_role_id"] if s and s["ticket_role_id"] else None

        category = guild.get_channel(cat_id) if cat_id else None
        if cat_id and not category:
            try:
                category = await guild.fetch_channel(cat_id)
            except discord.HTTPException:
                category = None

        role = guild.get_role(role_id) if role_id else None
        if role_id and not role:
            try:
                roles = await guild.fetch_roles()
                role = discord.utils.get(roles, id=role_id)
            except discord.HTTPException:
                role = None

        missing = []
        if not category:
            missing.append("Категория тикетов")
        if not role:
            missing.append("Роль поддержки")

        if missing:
            return await interaction.followup.send(
                f"Тикеты не настроены. Не настроено в `/settings`: **{', '.join(missing)}**.",
                ephemeral=True,
            )

        existing = await db.get_open_ticket(guild.id, user.id)
        if existing:
            ch = guild.get_channel(existing["channel_id"])
            if ch:
                return await interaction.followup.send(
                    f"У тебя уже есть открытый тикет: {ch.mention}", ephemeral=True
                )
            await db.update_ticket(existing["id"], status="closed")

        tid = await db.create_ticket(guild.id, user.id, self.topic.value, self.details.value)

        member_perms = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True,
            attach_files=True, embed_links=True,
        )
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: member_perms,
            role: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True,
                attach_files=True, embed_links=True, manage_messages=True,
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_channels=True,
                manage_messages=True, embed_links=True, attach_files=True,
                read_message_history=True,
            ),
        }
        channel = await guild.create_text_channel(
            f"ticket-{tid}", category=category, overwrites=overwrites,
            topic=f"Тикет #{tid} • {user} ({user.id})",
            reason=f"Тикет от {user}",
        )
        await db.update_ticket(tid, channel_id=channel.id)

        detail_text = self.details.value or "Без подробностей"
        embed = discord.Embed(color=0x5865F2)
        embed.set_author(
            name=f"Вопрос от {user.display_name}",
            icon_url=user.display_avatar.url,
        )
        embed.title = f"Тема вопроса: {self.topic.value}"
        embed.description = f"```{detail_text}```"
        embed.add_field(
            name="🖇️ Найденные ссылки",
            value=_find_links(detail_text),
            inline=False,
        )
        embed.set_footer(text=_ts())

        content = (
            f"`[ ⏳ | Ожидание ]` {user.mention}, "
            f"ваш тикет был передан на рассмотрение {role.mention}"
        )
        await channel.send(
            content=content,
            embed=embed,
            view=TicketControlView(),
            allowed_mentions=discord.AllowedMentions(users=True, roles=True),
        )
        await interaction.followup.send(f"Тикет создан: {channel.mention}", ephemeral=True)


class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Создать тикет", style=discord.ButtonStyle.primary,
        emoji="📩", custom_id="arvix:ticket:create",
    )
    async def create(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TicketModal())


class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Взять тикет", style=discord.ButtonStyle.secondary,
        emoji="📩", custom_id="arvix:ticket:claim",
    )
    async def claim_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        db = interaction.client.db
        t = await db.get_ticket_by_channel(interaction.channel_id)
        if not t:
            return await interaction.response.send_message("Тикет не найден.", ephemeral=True)
        s = await db.get_settings(interaction.guild_id)
        if not _is_support(interaction, s):
            return await interaction.response.send_message(
                "Только поддержка может взять тикет.", ephemeral=True
            )
        if t["claimed_by"]:
            return await interaction.response.send_message(
                f"Тикет уже ведёт <@{t['claimed_by']}>.", ephemeral=True
            )

        await db.update_ticket(t["id"], claimed_by=interaction.user.id)
        button.disabled = True
        await interaction.response.edit_message(view=self)

        await interaction.channel.send(
            f"`[ 🔮 | В обработке ]` <@{t['user_id']}>, "
            f"ваш тикет принят в обработку модератором {interaction.user.mention}"
        )

        if s and s["ticket_log_channel_id"]:
            log_ch = interaction.guild.get_channel(s["ticket_log_channel_id"])
            if log_ch:
                embed = discord.Embed(
                    title=f"🏷️ Тикет #{t['id']} принят в обработку",
                    color=config.BRAND_COLOR,
                )
                embed.add_field(
                    name="🛡️ Модератор",
                    value=f"{interaction.user.mention} ({interaction.user.name} | ID: `{interaction.user.id}`)",
                    inline=False,
                )
                embed.add_field(name="👤 Автор", value=f"<@{t['user_id']}>", inline=False)
                embed.add_field(
                    name="📍 Канал", value=f"# {interaction.channel.name}", inline=False
                )
                embed.set_footer(text=_ts())
                try:
                    await log_ch.send(embed=embed)
                except discord.HTTPException:
                    pass

    @discord.ui.button(
        label="Закрыть", style=discord.ButtonStyle.secondary,
        emoji="🔒", custom_id="arvix:ticket:close",
    )
    async def close_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        db = interaction.client.db
        t = await db.get_ticket_by_channel(interaction.channel_id)
        if not t:
            return await interaction.response.send_message("Тикет не найден.", ephemeral=True)
        s = await db.get_settings(interaction.guild_id)
        if interaction.user.id != t["user_id"] and not _is_support(interaction, s):
            return await interaction.response.send_message(
                "Закрыть тикет может автор или поддержка.", ephemeral=True
            )

        rate_embed = discord.Embed(
            title="Оцените работу модератора",
            description=f"<@{t['user_id']}>, пожалуйста, оцените качество обработки Вашего тикета.",
            color=config.BRAND_COLOR,
        )
        rate_embed.set_footer(text=_ts())
        await interaction.channel.send(embed=rate_embed, view=RatingView(t["id"], moderator_user=interaction.user))
        await interaction.response.defer()

    @discord.ui.button(
        label="Принудительно закрыть", style=discord.ButtonStyle.secondary,
        emoji="🗑", custom_id="arvix:ticket:force_close",
    )
    async def force_close_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        db = interaction.client.db
        t = await db.get_ticket_by_channel(interaction.channel_id)
        if not t:
            return await interaction.response.send_message("Тикет не найден.", ephemeral=True)
        s = await db.get_settings(interaction.guild_id)
        if not _is_support(interaction, s):
            return await interaction.response.send_message(
                "Только поддержка может принудительно закрыть.", ephemeral=True
            )

        await interaction.response.defer()
        await _finalize_close(interaction.client, interaction.channel, interaction.guild, interaction.user, t, s, force=True)


async def _finalize_close(bot, channel: discord.TextChannel, guild: discord.Guild, moderator: discord.User | discord.Member, t, s, *, force: bool = False):
    db = bot.db

    await db.update_ticket(
        t["id"],
        status="closed",
        closed_by=moderator.id,
        closed_at=datetime.now(MSK).isoformat(),
    )

    if force:
        await channel.send(embed=discord.Embed(
            title="🔒 Тикет закрыт принудительно",
            description="Канал будет удалён через 5 секунд.",
            color=config.DANGER_COLOR,
        ))
        await asyncio.sleep(5)
        try:
            await channel.delete(reason=f"Тикет принудительно закрыт: {moderator}")
        except discord.HTTPException:
            pass
        return

    await channel.send(
        f"`[ 🔒 | Закрытие ]` <@{t['user_id']}>, "
        f"тикет закрыт модератором {moderator.mention}"
    )

    transcript = await build_html_transcript(
        channel, guild, t["id"], config.BOT_NAME
    )
    transcript_file = discord.File(transcript, filename=f"ticket-{t['id']}.html")

    if s and s["ticket_log_channel_id"]:
        log_ch = guild.get_channel(s["ticket_log_channel_id"])
        if log_ch:
            log_embed = discord.Embed(
                title=f"🔒 Тикет #{t['id']} закрыт", color=config.WARN_COLOR,
            )
            author_member = guild.get_member(t["user_id"])
            author_name = author_member.name if author_member else str(t["user_id"])
            log_embed.add_field(
                name="👤 Автор",
                value=f"<@{t['user_id']}> ({author_name} | ID: `{t['user_id']}`)",
                inline=False,
            )
            log_embed.add_field(
                name="🛡️ Модератор",
                value=f"{moderator.mention} ({moderator.name} | ID: `{moderator.id}`)",
                inline=False,
            )
            topic_val = f"`{t['topic']}`" if t["topic"] else "`—`"
            log_embed.add_field(
                name="📝 Тема", value=topic_val, inline=False,
            )
            log_embed.set_footer(text=_ts())
            transcript_copy = await build_html_transcript(
                channel, guild, t["id"], config.BOT_NAME
            )
            try:
                await log_ch.send(
                    embed=log_embed,
                    file=discord.File(transcript_copy, filename=f"ticket-{t['id']}.html"),
                )
            except discord.HTTPException:
                pass

    close_embed = discord.Embed(
        title="🔒 Тикет закрыт",
        description="Тикет перемещён в архив. Лог переписки прикреплён ниже.",
        color=config.WARN_COLOR,
    )
    close_embed.set_footer(text=_ts())
    await channel.send(embed=close_embed, file=transcript_file, view=DeleteTicketView())

    user_obj = guild.get_member(t["user_id"])
    if user_obj:
        try:
            await channel.set_permissions(
                user_obj, view_channel=True, send_messages=False,
                read_message_history=True, add_reactions=True,
            )
        except discord.HTTPException:
            pass

    archive_id = s["ticket_archive_category_id"] if s else None
    if archive_id:
        archive_cat = guild.get_channel(archive_id)
        if archive_cat:
            try:
                await channel.edit(category=archive_cat, name=f"closed-{t['id']}", reason="Тикет закрыт → архив")
            except discord.HTTPException:
                pass


class RatingView(discord.ui.View):
    def __init__(self, ticket_id: int, moderator_user: discord.User | discord.Member):
        super().__init__(timeout=None)
        self.ticket_id = ticket_id
        self.moderator_user = moderator_user
        self.add_item(RatingButton(ticket_id, good=True, moderator_user=moderator_user))
        self.add_item(RatingButton(ticket_id, good=False, moderator_user=moderator_user))


class RatingButton(discord.ui.Button):
    def __init__(self, ticket_id: int, *, good: bool, moderator_user: discord.User | discord.Member):
        self.ticket_id = ticket_id
        self.moderator_user = moderator_user
        self.rating_value = 1 if good else -1
        super().__init__(
            emoji="👍" if good else "👎",
            style=discord.ButtonStyle.success if good else discord.ButtonStyle.danger,
            custom_id=f"arvix:ticket:rate:{'good' if good else 'bad'}:{ticket_id}",
        )

    async def callback(self, interaction: discord.Interaction):
        db = interaction.client.db
        t = await db.fetchone("SELECT * FROM tickets WHERE id=?", self.ticket_id)
        if not t or t["status"] == "closed":
            return await interaction.response.send_message("Тикет уже закрыт.", ephemeral=True)

        await db.update_ticket(self.ticket_id, rating=self.rating_value)
        for item in self.view.children:
            item.disabled = True

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="Спасибо за оценку!",
                description="Ваш отзыв учтён.",
                color=config.SUCCESS_COLOR,
            ),
            view=self.view,
        )

        s = await db.get_settings(interaction.guild_id)
        await _finalize_close(interaction.client, interaction.channel, interaction.guild, self.moderator_user, t, s, force=False)


class DeleteTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Удалить тикет", style=discord.ButtonStyle.danger,
        emoji="🗑", custom_id="arvix:ticket:delete",
    )
    async def delete_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        s = await interaction.client.db.get_settings(interaction.guild_id)
        if not _is_support(interaction, s):
            return await interaction.response.send_message(
                "Только поддержка может удалить тикет.", ephemeral=True
            )
        await interaction.response.send_message("Удаляю тикет…")
        await asyncio.sleep(2)
        try:
            await interaction.channel.delete(reason=f"Тикет удалён: {interaction.user}")
        except discord.HTTPException:
            pass


class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(TicketPanelView())
        self.bot.add_view(TicketControlView())
        self.bot.add_view(DeleteTicketView())

    @app_commands.command(
        name="ticketpanel", description="Отправить панель создания тикетов"
    )
    @app_commands.guild_only()
    async def ticketpanel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🏷️ Тикет-система поддержки",
            description=(
                "Если у Вас возникли вопросы, жалобы или проблемы — "
                "нажмите на кнопку ниже, чтобы создать тикет.\n\n"
                "Наши модераторы ответят Вам в кратчайшие сроки."
            ),
            color=config.BRAND_COLOR,
        )
        embed.set_footer(text=_ts())
        await interaction.channel.send(embed=embed, view=TicketPanelView())
        await interaction.response.send_message("Панель отправлена.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Tickets(bot))
