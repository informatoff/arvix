from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands

import config

MSK = timezone(timedelta(hours=3))

PROMO_LOG_CHANNEL_ID = 1553841964292775956

TYPE_COINS = 1
TYPE_CUSTOM = 2

PROMO_TYPE_CHOICES = [
    app_commands.Choice(name="ArvixCoins", value=TYPE_COINS),
    app_commands.Choice(name="Другое (приз вручную)", value=TYPE_CUSTOM),
]


def _ts() -> str:
    return datetime.now(MSK).strftime("%d.%m.%Y %H:%M:%S")


def _can_manage_promo(interaction: discord.Interaction, settings) -> bool:
    if interaction.user.guild_permissions.administrator:
        return True
    role_id = settings["promo_role_id"] if settings else None
    return bool(role_id and interaction.user.get_role(role_id))


class Promocode(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="promoadd", description="Добавить промокод")
    @app_commands.describe(
        code="Код промокода",
        type="Тип промокода: монеты или произвольный приз",
        prize="Название приза (для типа «Другое») или количество монет (для «ArvixCoins»)",
        uses="Сколько раз можно активировать (лимит использований)",
    )
    @app_commands.choices(type=PROMO_TYPE_CHOICES)
    @app_commands.guild_only()
    async def promoadd(
        self,
        interaction: discord.Interaction,
        code: str,
        type: app_commands.Choice[int],
        prize: str,
        uses: app_commands.Range[int, 1, 100000],
    ):
        db = self.bot.db
        s = await db.get_settings(interaction.guild_id)
        if not _can_manage_promo(interaction, s):
            return await interaction.response.send_message(
                "У вас нет прав для добавления промокодов. Настройте роль через `/settings`.",
                ephemeral=True,
            )

        code_clean = code.strip()
        if not code_clean:
            return await interaction.response.send_message("Код не может быть пустым.", ephemeral=True)

        existing = await db.get_promocode(interaction.guild_id, code_clean)
        if existing:
            return await interaction.response.send_message(
                f"Промокод `{code_clean}` уже существует.", ephemeral=True
            )

        ptype = type.value
        amount = None
        prize_name = None

        if ptype == TYPE_COINS:
            val = prize.strip()
            if not val.isdigit() or int(val) <= 0:
                return await interaction.response.send_message(
                    "Для типа **ArvixCoins** параметр `prize` должен быть числом больше 0 (количество монет).",
                    ephemeral=True,
                )
            amount = int(val)
        else:
            prize_name = prize.strip()
            if not prize_name:
                return await interaction.response.send_message(
                    "Укажите название приза для промокода.", ephemeral=True
                )

        await db.create_promocode(
            interaction.guild_id, code_clean, ptype, prize_name, amount, uses, interaction.user.id
        )

        prize_display = f"{amount:,} ArvixCoins" if ptype == TYPE_COINS else prize_name
        embed = discord.Embed(
            title="🎟️ Промокод создан",
            color=config.SUCCESS_COLOR,
        )
        embed.add_field(name="Код", value=f"`{code_clean}`", inline=True)
        embed.add_field(name="Тип", value="ArvixCoins" if ptype == TYPE_COINS else "Другое", inline=True)
        embed.add_field(name="Приз", value=prize_display, inline=True)
        embed.add_field(name="Лимит использований", value=str(uses), inline=True)
        embed.set_footer(text=_ts())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="promocode", description="Активировать промокод")
    @app_commands.describe(code="Введите промокод")
    @app_commands.guild_only()
    async def promocode(self, interaction: discord.Interaction, code: str):
        db = self.bot.db
        code_clean = code.strip()

        promo = await db.get_promocode(interaction.guild_id, code_clean)
        if not promo:
            return await interaction.response.send_message(
                "Такой промокод не найден или уже неактивен.", ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        ok = await db.redeem_promocode(promo["id"], interaction.guild_id, interaction.user.id)
        if not ok:
            return await interaction.followup.send(
                "Вы уже активировали этот промокод, либо лимит активаций исчерпан.",
                ephemeral=True,
            )

        user = interaction.user
        ptype = promo["type"]

        if ptype == TYPE_COINS:
            amount = promo["amount"] or 0
            await db.add_coins(interaction.guild_id, user.id, amount)
            prize_display = f"{amount:,}ArvixCoins"
        else:
            prize_display = promo["prize_name"] or "—"

        activation_embed = discord.Embed(color=0x2B2D31)
        activation_embed.description = (
            f"🎟️ **Активирован промокод**\n\n"
            f"👤 {user.mention} `[id{user.id}]`\n"
            f"🔑 Код: `{promo['code']}`\n"
            f"🎁 Приз: {prize_display}\n"
            f"🕐 Время: {_ts()}"
        )
        await interaction.followup.send(embed=activation_embed, ephemeral=True)

        if ptype == TYPE_CUSTOM:
            log_ch = interaction.guild.get_channel(PROMO_LOG_CHANNEL_ID)
            if not log_ch:
                try:
                    log_ch = await interaction.client.fetch_channel(PROMO_LOG_CHANNEL_ID)
                except discord.HTTPException:
                    log_ch = None
            if log_ch:
                log_embed = discord.Embed(
                    title="🎟️ Активирован промокод",
                    color=config.BRAND_COLOR,
                )
                log_embed.add_field(
                    name="👤 Пользователь",
                    value=f"{user.mention} ({user.name} | ID: `{user.id}`)",
                    inline=False,
                )
                log_embed.add_field(name="🔑 Код", value=f"`{promo['code']}`", inline=False)
                log_embed.add_field(name="🎁 Приз", value=prize_display, inline=False)
                log_embed.set_footer(text=_ts())
                try:
                    await log_ch.send(embed=log_embed)
                except discord.HTTPException:
                    pass


async def setup(bot):
    await bot.add_cog(Promocode(bot))
