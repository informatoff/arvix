import math
import time
import discord
from discord import app_commands
from discord.ext import commands

import config
from utils.levels import xp_needed

PAGE_SIZE = 10

SORT_OPTIONS = [
    ("Сорт. по уровню", "level", "📈"),
    ("Сорт. по балансу", "coins", "💰"),
    ("Сорт. по голосовой активности", "voice", "🎶"),
]


async def build_top_embed(
    guild: discord.Guild,
    user: discord.User | discord.Member,
    db,
    sort_by: str,
    page: int,
) -> tuple[discord.Embed, int]:
    total_users = await db.count_users(guild.id)
    total_pages = max(1, math.ceil(total_users / PAGE_SIZE)) if total_users else 1
    page = max(1, min(page, total_pages))
    offset = (page - 1) * PAGE_SIZE

    rows = await db.get_top(guild.id, sort_by=sort_by, limit=PAGE_SIZE, offset=offset)
    user_rank = await db.get_user_rank(guild.id, user.id, sort_by=sort_by)

    lines = []

    if not rows:
        lines.append("*Пока никто не попал в этот рейтинг.*")
    else:
        now_ts = int(time.time())
        for i, row in enumerate(rows, start=offset + 1):
            if i == 1:
                badge = "🥇"
            elif i == 2:
                badge = "🥈"
            elif i == 3:
                badge = "🥉"
            else:
                badge = f"**{i}.**"

            r = dict(row)
            uid = r["user_id"]
            member = guild.get_member(uid)
            if not member:
                try:
                    member = await guild.fetch_member(uid)
                except Exception:
                    member = None

            if member:
                user_label = f"{member.mention} ({member.name})"
            else:
                user_label = f"<@{uid}>"

            if sort_by == "coins":
                coins = (r.get("coins", 0) or 0) + (r.get("bank", 0) or 0)
                sub = f"Баланс: {coins:,} 🪙"
            elif sort_by == "level":
                lvl = r.get("level", 0) or 0
                xp = r.get("xp", 0) or 0
                need = xp_needed(lvl)
                sub = f"Уровень: {lvl} ( {xp}/{need} )"
            elif sort_by == "voice":
                v_sec = r.get("voice_seconds", 0) or 0
                hours = v_sec // 3600
                mins = (v_sec % 3600) // 60
                secs = v_sec % 60
                sub = f"Голосовая активность: {hours}:{mins:02d}:{secs:02d}"
            else:
                sub = ""

            lines.append(f"{badge} {user_label}\n{sub}\n")

    lines.append(f"{user.mention}, Ваша позиция в топе: **{user_rank}**")
    lines.append(f"Страница {page} из {total_pages}")

    embed = discord.Embed(
        title="Список лидеров",
        description="\n".join(lines),
        color=0x5865F2,
    )
    return embed, total_pages


class TopSelect(discord.ui.Select):
    def __init__(self, current_sort: str):
        options = [
            discord.SelectOption(
                label=label,
                value=val,
                emoji=emoji,
                default=(val == current_sort),
            )
            for label, val, emoji in SORT_OPTIONS
        ]
        super().__init__(
            placeholder="Выберите сортировку…",
            options=options,
            row=0,
            custom_id="top:select_sort",
        )

    async def callback(self, interaction: discord.Interaction):
        view: TopView = self.view
        view.sort_by = self.values[0]
        view.page = 1
        await view.update(interaction)


class PageJumpModal(discord.ui.Modal, title="Перейти к странице"):
    page_input = discord.ui.TextInput(
        label="Номер страницы",
        placeholder="Введите число…",
        min_length=1,
        max_length=5,
    )

    def __init__(self, parent_view: "TopView"):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        val = self.page_input.value.strip()
        if not val.isdigit() or int(val) < 1:
            return await interaction.response.send_message("Введите корректное число.", ephemeral=True)
        self.parent_view.page = int(val)
        await self.parent_view.update(interaction)


class TopView(discord.ui.View):
    def __init__(self, author_id: int, guild: discord.Guild, db, sort_by: str = "coins", page: int = 1):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.guild = guild
        self.db = db
        self.sort_by = sort_by
        self.page = page
        self.total_pages = 1
        self._refresh_components()

    def _refresh_components(self):
        self.clear_items()
        self.add_item(TopSelect(self.sort_by))

        prev_btn = discord.ui.Button(
            label="◀", style=discord.ButtonStyle.secondary, row=1, disabled=(self.page <= 1)
        )
        prev_btn.callback = self.prev_page
        self.add_item(prev_btn)

        jump_btn = discord.ui.Button(
            label="Перейти к странице", style=discord.ButtonStyle.secondary, row=1
        )
        jump_btn.callback = self.jump_page
        self.add_item(jump_btn)

        next_btn = discord.ui.Button(
            label="▶", style=discord.ButtonStyle.secondary, row=1, disabled=(self.page >= self.total_pages)
        )
        next_btn.callback = self.next_page
        self.add_item(next_btn)

        close_btn = discord.ui.Button(
            label="❌", style=discord.ButtonStyle.secondary, row=1
        )
        close_btn.callback = self.close_view
        self.add_item(close_btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Это меню открыто для другого пользователя.", ephemeral=True)
            return False
        return True

    async def update(self, interaction: discord.Interaction):
        embed, self.total_pages = await build_top_embed(
            self.guild, interaction.user, self.db, self.sort_by, self.page
        )
        self._refresh_components()
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)

    async def prev_page(self, interaction: discord.Interaction):
        if self.page > 1:
            self.page -= 1
        await self.update(interaction)

    async def next_page(self, interaction: discord.Interaction):
        if self.page < self.total_pages:
            self.page += 1
        await self.update(interaction)

    async def jump_page(self, interaction: discord.Interaction):
        await interaction.response.send_modal(PageJumpModal(self))

    async def close_view(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await interaction.delete_original_response()


class Top(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="top", description="Список лидеров сервера")
    @app_commands.describe(sort_by="Критерий сортировки топа")
    @app_commands.choices(
        sort_by=[
            app_commands.Choice(name="📈 Сорт. по уровню", value="level"),
            app_commands.Choice(name="💰 Сорт. по балансу", value="coins"),
            app_commands.Choice(name="🎶 Сорт. по голосовой активности", value="voice"),
        ]
    )
    @app_commands.guild_only()
    async def top_cmd(self, interaction: discord.Interaction, sort_by: app_commands.Choice[str] | None = None):
        chosen_sort = sort_by.value if sort_by else "coins"
        await interaction.response.defer()
        view = TopView(
            author_id=interaction.user.id,
            guild=interaction.guild,
            db=self.bot.db,
            sort_by=chosen_sort,
            page=1,
        )
        embed, view.total_pages = await build_top_embed(
            interaction.guild, interaction.user, self.bot.db, chosen_sort, 1
        )
        view._refresh_components()
        await interaction.followup.send(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(Top(bot))
