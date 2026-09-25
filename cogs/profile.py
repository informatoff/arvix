import asyncio
import logging
import random
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from utils.card import render_profile
from utils.levels import xp_needed

log = logging.getLogger("arvix.profile")


class Profile(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._last_xp: dict[tuple[int, int], float] = {}

    async def cog_load(self):
        self.voice_loop.start()

    async def cog_unload(self):
        self.voice_loop.cancel()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        key = (message.guild.id, message.author.id)
        now = time.monotonic()
        xp = coins = 0
        if now - self._last_xp.get(key, 0) >= config.XP_COOLDOWN:
            self._last_xp[key] = now
            xp, coins = random.randint(*config.XP_RANGE), config.MESSAGE_COINS
        level, leveled = await self.bot.db.add_progress(
            message.guild.id, message.author.id, xp=xp, coins=coins, messages=1
        )
        if leveled:
            s = await self.bot.db.get_settings(message.guild.id)
            ch = None
            if s and s["levelup_channel_id"]:
                ch = message.guild.get_channel(s["levelup_channel_id"])
            ch = ch or message.channel
            embed = discord.Embed(
                description=f"Поздравляем {message.author.mention}! Ты достиг **{level}** уровня!",
                color=0x5865F2,
            )
            try:
                await ch.send(embed=embed)
            except discord.HTTPException:
                pass

    @tasks.loop(seconds=60)
    async def voice_loop(self):
        try:
            for guild in self.bot.guilds:
                channels = list(guild.voice_channels) + list(getattr(guild, "stage_channels", []))
                for vc in channels:
                    if vc == guild.afk_channel:
                        continue
                    members = [
                        m for m in vc.members
                        if not m.bot and not (m.voice and (m.voice.self_deaf or m.voice.deaf))
                    ]
                    if len(members) < config.VOICE_MIN_MEMBERS:
                        continue
                    s = await self.bot.db.get_settings(guild.id)
                    lvl_ch = guild.get_channel(s["levelup_channel_id"]) if s and s["levelup_channel_id"] else None
                    for m in members:
                        lvl, leveled = await self.bot.db.add_progress(
                            guild.id, m.id, xp=config.VOICE_XP, coins=config.VOICE_COINS, voice_seconds=60
                        )
                        if leveled and lvl_ch:
                            embed = discord.Embed(
                                description=f"Поздравляем {m.mention}! Ты достиг **{lvl}** уровня!",
                                color=0x5865F2,
                            )
                            try:
                                await lvl_ch.send(embed=embed)
                            except discord.HTTPException:
                                pass
        except Exception:
            log.exception("Ошибка в voice_loop")

    @voice_loop.before_loop
    async def _before_voice(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="profile", description="Показать профиль")
    @app_commands.describe(member="Чей профиль показать (по умолчанию — твой)")
    @app_commands.guild_only()
    async def profile(self, interaction: discord.Interaction, member: discord.Member | None = None):
        member = member or interaction.user
        if member.bot:
            return await interaction.response.send_message("У ботов нет профиля", ephemeral=True)
        await interaction.response.defer()

        db = self.bot.db
        u = await db.get_user(interaction.guild_id, member.id)
        r_level, r_coins, r_voice = await db.get_ranks(interaction.guild_id, u)
        try:
            avatar = await member.display_avatar.replace(size=256, format="png").read()
        except discord.HTTPException:
            avatar = None

        buf = await asyncio.to_thread(
            render_profile,
            avatar, u["coins"], u["messages"], u["voice_seconds"] // 3600,
            u["level"], u["xp"], xp_needed(u["level"]), r_level, r_coins, r_voice,
            member.display_name,
        )
        await interaction.followup.send(file=discord.File(buf, filename="profile.png"))


async def setup(bot):
    await bot.add_cog(Profile(bot))
