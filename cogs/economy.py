from datetime import datetime, timezone, timedelta
import discord
from discord import app_commands
from discord.ext import commands

import config

MSK = timezone(timedelta(hours=3))


def _ts() -> str:
    return datetime.now(MSK).strftime("Сегодня, в %H:%M")


def _can_give_coins(interaction: discord.Interaction, settings) -> bool:
    if interaction.user.guild_permissions.administrator:
        return True
    role_id = settings["give_role_id"] if settings else None
    return bool(role_id and interaction.user.get_role(role_id))


class AddShopItemModal(discord.ui.Modal, title="Добавить товар в Магазин Arvix"):
    item_name = discord.ui.TextInput(
        label="Название предмета",
        placeholder="Например: VIP статус или Уникальный цвет",
        max_length=100,
    )
    item_price = discord.ui.TextInput(
        label="Цена в монетах",
        placeholder="Например: 500",
        max_length=10,
    )
    role_id = discord.ui.TextInput(
        label="ID роли для выдачи (необязательно)",
        placeholder="Вставьте ID роли из Discord (или оставьте пустым)",
        required=False,
        max_length=20,
    )
    item_desc = discord.ui.TextInput(
        label="Описание товара (необязательно)",
        style=discord.TextStyle.paragraph,
        placeholder="Подробности о товаре…",
        required=False,
        max_length=500,
    )

    async def on_submit(self, interaction: discord.Interaction):
        val = self.item_price.value.strip()
        if not val.isdigit() or int(val) <= 0:
            return await interaction.response.send_message("Цена должна быть числом больше 0.", ephemeral=True)

        price = int(val)
        role = None
        r_id = None
        if self.role_id.value and self.role_id.value.strip().isdigit():
            r_id = int(self.role_id.value.strip())
            role = interaction.guild.get_role(r_id)

        name = self.item_name.value.strip()
        desc = self.item_desc.value.strip() if self.item_desc.value else None

        item_id = await interaction.client.db.add_shop_item(
            interaction.guild_id, r_id, price, name, desc
        )

        role_info = f" (Выдает роль {role.mention})" if role else ""
        embed = discord.Embed(
            title="Товар добавлен в Магазин Arvix",
            description=f"Товар **{name}** за **{price:,} 🪙**{role_info} успешно добавлен `[ID: {item_id}]`.",
            color=config.SUCCESS_COLOR,
        )
        embed.set_footer(text=_ts())
        await interaction.response.send_message(embed=embed)


class ShopSelect(discord.ui.Select):
    def __init__(self, items):
        options = []
        for item in items:
            name = item["name"] or f"Товар #{item['id']}"
            options.append(
                discord.SelectOption(
                    label=f"{name} — {item['price']:,} 🪙",
                    value=str(item["id"]),
                    description=f"ID: {item['id']}",
                )
            )
        super().__init__(
            placeholder="Выберите товар для покупки…",
            options=options,
            custom_id="shop:select_item",
        )

    async def callback(self, interaction: discord.Interaction):
        item_id = int(self.values[0])
        db = interaction.client.db
        guild = interaction.guild
        member = interaction.user

        item = await db.get_shop_item(item_id, guild.id)
        if not item:
            return await interaction.response.send_message("Товар не найден.", ephemeral=True)

        role = guild.get_role(item["role_id"]) if item["role_id"] else None
        if role and member.get_role(role.id):
            return await interaction.response.send_message("У вас уже есть эта роль!", ephemeral=True)

        u = await db.get_user(guild.id, member.id)
        if u["coins"] < item["price"]:
            return await interaction.response.send_message(
                f"Недостаточно монет. Ваш баланс: **{u['coins']:,} 🪙**, цена: **{item['price']:,} 🪙**.",
                ephemeral=True,
            )

        await db.add_coins(guild.id, member.id, -item["price"])
        if role:
            try:
                await member.add_roles(role, reason=f"Покупка в Магазине Arvix за {item['price']} монет")
            except discord.HTTPException:
                await db.add_coins(guild.id, member.id, item["price"])
                return await interaction.response.send_message(
                    "Не удалось выдать роль. Проверьте права бота.", ephemeral=True
                )

        embed = discord.Embed(
            title="Покупка успешна!",
            description=f"Вы успешно приобрели **{item['name']}** за **{item['price']:,} 🪙**.",
            color=config.SUCCESS_COLOR,
        )
        embed.set_footer(text=_ts())
        await interaction.response.send_message(embed=embed, ephemeral=True)


class ShopView(discord.ui.View):
    def __init__(self, items):
        super().__init__(timeout=180)
        self.add_item(ShopSelect(items))


class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="give", description="Выдать монеты пользователю")
    @app_commands.describe(member="Кому выдать", amount="Количество монет")
    @app_commands.guild_only()
    async def give(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        s = await self.bot.db.get_settings(interaction.guild_id)
        if not _can_give_coins(interaction, s):
            return await interaction.response.send_message(
                "У вас нет прав для выдачи монет. Настройте роль через `/settings`.", ephemeral=True
            )
        if member.bot:
            return await interaction.response.send_message("Нельзя выдать монеты боту.", ephemeral=True)
        if amount <= 0:
            return await interaction.response.send_message("Сумма должна быть положительной.", ephemeral=True)

        await self.bot.db.add_coins(interaction.guild_id, member.id, amount)

        embed = discord.Embed(
            title="Выдача монет",
            description=f"Модератор {interaction.user.mention} выдал **{amount:,} 🪙** пользователю {member.mention}.",
            color=config.SUCCESS_COLOR,
        )
        embed.set_footer(text=_ts())
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="shop", description="Магазин Arvix")
    @app_commands.guild_only()
    async def shop(self, interaction: discord.Interaction):
        items = await self.bot.db.get_shop_items(interaction.guild_id)
        u = await self.bot.db.get_user(interaction.guild_id, interaction.user.id)

        if not items:
            return await interaction.response.send_message(
                "Магазин Arvix пока пуст. Администраторы могут добавить товары через `/shop_add`.",
                ephemeral=True,
            )

        lines = [f"Ваш баланс: **{u['coins']:,} 🪙**\n"]
        for idx, item in enumerate(items, start=1):
            role_part = f" (<@&{item['role_id']}>)" if item["role_id"] else ""
            desc_part = f"\n*{item['description']}*" if item["description"] else ""
            lines.append(f"**{idx}.** {item['name']}{role_part} — **{item['price']:,} 🪙** `[ID: {item['id']}]`{desc_part}")

        embed = discord.Embed(
            title="🛒 Магазин Arvix",
            description="\n".join(lines),
            color=config.BRAND_COLOR,
        )
        embed.set_footer(text=_ts())
        view = ShopView(items)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="shop_add", description="Добавить товар в Магазин Arvix")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def shop_add(self, interaction: discord.Interaction):
        await interaction.response.send_modal(AddShopItemModal())

    @app_commands.command(name="shop_remove", description="Удалить товар из магазина по ID")
    @app_commands.describe(item_id="ID товара из магазина")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def shop_remove(self, interaction: discord.Interaction, item_id: int):
        item = await self.bot.db.get_shop_item(item_id, interaction.guild_id)
        if not item:
            return await interaction.response.send_message(f"Товар с ID `{item_id}` не найден.", ephemeral=True)

        await self.bot.db.remove_shop_item(item_id, interaction.guild_id)
        embed = discord.Embed(
            title="Товар удален из Магазина Arvix",
            description=f"Товар `{item['name']}` `[ID: {item_id}]` успешно удален.",
            color=config.WARN_COLOR,
        )
        embed.set_footer(text=_ts())
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Economy(bot))
