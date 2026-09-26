from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands

import config

MSK = timezone(timedelta(hours=3))

NEWCOMER_ROLE_ID = 1553347071971565658


def _ts() -> str:
    return datetime.now(MSK).strftime("Сегодня, в %H:%M")


def _is_support(interaction: discord.Interaction, settings) -> bool:
    perms = interaction.user.guild_permissions
    if perms.administrator or perms.manage_guild:
        return True
    role_id = settings["ticket_role_id"] if settings else None
    return bool(role_id and interaction.user.get_role(role_id))


class VerificationModal(discord.ui.Modal, title="Получение доступа"):
    nickname = discord.ui.TextInput(
        label="Ваш ник",
        placeholder="Укажите свой игровой / основной ник",
        max_length=100,
    )
    position = discord.ui.TextInput(
        label="Должность",
        placeholder="Например: Админ, Лидер",
        max_length=100,
    )
    proof_link = discord.ui.TextInput(
        label="Ссылка на скриншот-пруф",
        placeholder="Вставьте ссылку на скриншот, подтверждающий должность",
        max_length=500,
    )

    async def on_submit(self, interaction: discord.Interaction):
        db, guild, user = interaction.client.db, interaction.guild, interaction.user

        s = await db.get_settings(guild.id)
        log_id = s["verification_log_channel_id"] if s and s["verification_log_channel_id"] else None
        log_ch = guild.get_channel(log_id) if log_id else None

        if not log_ch:
            return await interaction.response.send_message(
                "Верификация не настроена. Обратитесь к администрации сервера.",
                ephemeral=True,
            )

        link = self.proof_link.value.strip()
        link_display = link if link.startswith(("http://", "https://")) else f"`{link}`"

        embed = discord.Embed(
            title="📋 Новая заявка на верификацию",
            color=config.BRAND_COLOR,
        )
        embed.set_author(name=str(user), icon_url=user.display_avatar.url)
        embed.add_field(
            name="👤 Участник",
            value=f"{user.mention} (`{user.id}`)",
            inline=False,
        )
        embed.add_field(name="📝 Ник", value=self.nickname.value, inline=True)
        embed.add_field(name="🏷️ Должность", value=self.position.value, inline=True)
        embed.add_field(name="🖇️ Пруф", value=link_display, inline=False)
        embed.set_footer(text=_ts())

        if link.startswith(("http://", "https://")):
            lowered = link.lower()
            if lowered.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")) or "cdn.discordapp.com" in lowered or "media.discordapp.net" in lowered:
                embed.set_image(url=link)

        await log_ch.send(embed=embed, view=VerificationReviewView())

        success_embed = discord.Embed(
            description="**Вы успешно отправили заявку!**\nОжидайте рассмотрения администрацией.",
            color=config.SUCCESS_COLOR,
        )
        await interaction.response.send_message(embed=success_embed, ephemeral=True)


class VerificationPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Получить доступ", style=discord.ButtonStyle.success,
        emoji="✅", custom_id="arvix:verification:apply",
    )
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        db = interaction.client.db
        s = await db.get_settings(interaction.guild_id)
        role_id = s["verification_role_id"] if s and s["verification_role_id"] else None
        if role_id and interaction.user.get_role(role_id):
            already_embed = discord.Embed(
                description="**Вы уже прошли верификацию!**",
                color=config.SUCCESS_COLOR,
            )
            return await interaction.response.send_message(embed=already_embed, ephemeral=True)
        await interaction.response.send_modal(VerificationModal())


class VerificationReviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Одобрить", style=discord.ButtonStyle.success,
        emoji="✅", custom_id="arvix:verification:approve",
    )
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        db, guild = interaction.client.db, interaction.guild
        s = await db.get_settings(guild.id)
        if not _is_support(interaction, s):
            return await interaction.response.send_message(
                "Только поддержка может рассматривать заявки.", ephemeral=True
            )

        applicant_id = self._extract_applicant_id(interaction)
        member = guild.get_member(applicant_id)
        if not member:
            try:
                member = await guild.fetch_member(applicant_id)
            except discord.HTTPException:
                member = None

        role_id = s["verification_role_id"] if s and s["verification_role_id"] else None
        role = guild.get_role(role_id) if role_id else None

        if not member or not role:
            return await interaction.response.send_message(
                "Не удалось выдать роль: участник вышел с сервера или роль верификации не настроена.",
                ephemeral=True,
            )

        try:
            await member.add_roles(role, reason=f"Верификация одобрена {interaction.user}")
        except discord.HTTPException:
            return await interaction.response.send_message(
                "Не удалось выдать роль. Проверьте права бота.", ephemeral=True
            )

        newcomer_role = guild.get_role(NEWCOMER_ROLE_ID)
        if newcomer_role and newcomer_role in member.roles:
            try:
                await member.remove_roles(newcomer_role, reason=f"Верификация одобрена {interaction.user}")
            except discord.HTTPException:
                pass

        for item in self.children:
            item.disabled = True

        old_embed = interaction.message.embeds[0]
        old_embed.color = config.SUCCESS_COLOR
        old_embed.add_field(
            name="✅ Решение",
            value=f"Одобрено {interaction.user.mention}",
            inline=False,
        )
        await interaction.response.edit_message(embed=old_embed, view=self)

        success_embed = discord.Embed(
            description="**Вы успешно прошли проверку!**",
            color=config.SUCCESS_COLOR,
        )
        try:
            await member.send(embed=success_embed)
        except discord.HTTPException:
            pass

    @discord.ui.button(
        label="Отклонить", style=discord.ButtonStyle.danger,
        emoji="❌", custom_id="arvix:verification:deny",
    )
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        db, guild = interaction.client.db, interaction.guild
        s = await db.get_settings(guild.id)
        if not _is_support(interaction, s):
            return await interaction.response.send_message(
                "Только поддержка может рассматривать заявки.", ephemeral=True
            )

        applicant_id = self._extract_applicant_id(interaction)
        member = guild.get_member(applicant_id)

        for item in self.children:
            item.disabled = True

        old_embed = interaction.message.embeds[0]
        old_embed.color = config.DANGER_COLOR
        old_embed.add_field(
            name="❌ Решение",
            value=f"Отклонено {interaction.user.mention}",
            inline=False,
        )
        await interaction.response.edit_message(embed=old_embed, view=self)

        if member:
            deny_embed = discord.Embed(
                description="**Ваша заявка на верификацию отклонена.**\nПроверьте корректность данных и попробуйте снова.",
                color=config.DANGER_COLOR,
            )
            try:
                await member.send(embed=deny_embed)
            except discord.HTTPException:
                pass

    def _extract_applicant_id(self, interaction: discord.Interaction) -> int | None:
        embeds = interaction.message.embeds
        if not embeds:
            return None
        for field in embeds[0].fields:
            if field.name and "Участник" in field.name:
                match = field.value.split("`")
                if len(match) >= 2 and match[1].isdigit():
                    return int(match[1])
        return None


class Verification(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(VerificationPanelView())
        self.bot.add_view(VerificationReviewView())

    @app_commands.command(
        name="verifypanel", description="Отправить панель верификации доступа"
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def verifypanel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Получение доступа",
            description=(
                "Вам необходимо **пройти процесс верификации**, чтобы "
                "воспользоваться Discord сервером в полном объёме и "
                "**получить доступ** ко всем существующим функциям.\n\n"
                "Если получить доступ не удаётся — воспользуйтесь "
                "**официальным приложением Discord**, либо **обновите его** до "
                "последней версии и попробуйте снова."
            ),
            color=0xFFFFFF,
        )
        await interaction.channel.send(embed=embed, view=VerificationPanelView())
        await interaction.response.send_message("Панель отправлена.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Verification(bot))
