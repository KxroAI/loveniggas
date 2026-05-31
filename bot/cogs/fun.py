"""
Fun Commands Cog
Social/reaction GIF commands.
Uses otakugifs.xyz (free, no API key required).
"""

import aiohttp
import discord
from discord.ext import commands

GIF_API = "https://api.otakugifs.xyz/gif"


async def _fetch_gif(reaction: str) -> str:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{GIF_API}?reaction={reaction}",
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("url", "")
    except Exception:
        pass
    return ""


class FunCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _react(self, ctx: commands.Context, gif_url: str, title: str):
        embed = discord.Embed(title=title, color=discord.Color.random())
        if gif_url:
            embed.set_image(url=gif_url)
        embed.set_footer(
            text=f"Requested by {ctx.author.display_name}",
            icon_url=ctx.author.display_avatar.url,
        )
        await ctx.send(embed=embed)

    # ── Target commands ────────────────────────────────────────────────────

    @commands.command(name="slap", help="Slap someone! Usage: nslap @user")
    @commands.cooldown(rate=3, per=30, type=commands.BucketType.user)
    async def slap(self, ctx: commands.Context, user: discord.Member = None):
        user = user or ctx.author
        gif = await _fetch_gif("slap")
        target = user.display_name if user.id != ctx.author.id else "themselves"
        await self._react(ctx, gif, f"{ctx.author.display_name} slapped {target}! 👋")

    @commands.command(name="hug", help="Hug someone! Usage: nhug @user")
    @commands.cooldown(rate=3, per=30, type=commands.BucketType.user)
    async def hug(self, ctx: commands.Context, user: discord.Member = None):
        user = user or ctx.author
        gif = await _fetch_gif("hug")
        target = user.display_name if user.id != ctx.author.id else "themselves"
        await self._react(ctx, gif, f"{ctx.author.display_name} hugged {target}! 🤗")

    @commands.command(name="kiss", help="Kiss someone! Usage: nkiss @user")
    @commands.cooldown(rate=3, per=30, type=commands.BucketType.user)
    async def kiss(self, ctx: commands.Context, user: discord.Member = None):
        user = user or ctx.author
        gif = await _fetch_gif("kiss")
        target = user.display_name if user.id != ctx.author.id else "themselves"
        await self._react(ctx, gif, f"{ctx.author.display_name} kissed {target}! 💋")

    @commands.command(name="pat", help="Pat someone! Usage: npat @user")
    @commands.cooldown(rate=3, per=30, type=commands.BucketType.user)
    async def pat(self, ctx: commands.Context, user: discord.Member = None):
        user = user or ctx.author
        gif = await _fetch_gif("pat")
        target = user.display_name if user.id != ctx.author.id else "themselves"
        await self._react(ctx, gif, f"{ctx.author.display_name} patted {target}! 🤚")

    @commands.command(name="angry", help="Express anger at someone! Usage: nangry @user")
    @commands.cooldown(rate=3, per=30, type=commands.BucketType.user)
    async def angry(self, ctx: commands.Context, user: discord.Member = None):
        user = user or ctx.author
        gif = await _fetch_gif("angryface")
        target = user.display_name if user.id != ctx.author.id else "themselves"
        await self._react(ctx, gif, f"{ctx.author.display_name} is angry at {target}! 😡")

    @commands.command(name="cuddle", help="Cuddle with someone! Usage: ncuddle @user")
    @commands.cooldown(rate=3, per=30, type=commands.BucketType.user)
    async def cuddle(self, ctx: commands.Context, user: discord.Member = None):
        user = user or ctx.author
        gif = await _fetch_gif("cuddle")
        target = user.display_name if user.id != ctx.author.id else "themselves"
        await self._react(ctx, gif, f"{ctx.author.display_name} cuddled with {target}! 🥰")

    @commands.command(name="wave", help="Wave at someone! Usage: nwave @user")
    @commands.cooldown(rate=3, per=30, type=commands.BucketType.user)
    async def wave(self, ctx: commands.Context, user: discord.Member = None):
        user = user or ctx.author
        gif = await _fetch_gif("wave")
        target = user.display_name if user.id != ctx.author.id else "themselves"
        await self._react(ctx, gif, f"{ctx.author.display_name} waved at {target}! 👋")

    @commands.command(name="highfive", help="High five someone! Usage: nhighfive @user")
    @commands.cooldown(rate=3, per=30, type=commands.BucketType.user)
    async def highfive(self, ctx: commands.Context, user: discord.Member = None):
        user = user or ctx.author
        gif = await _fetch_gif("highfive")
        target = user.display_name if user.id != ctx.author.id else "themselves"
        await self._react(ctx, gif, f"{ctx.author.display_name} high fived {target}! 🙌")

    @commands.command(name="poke", help="Poke someone! Usage: npoke @user")
    @commands.cooldown(rate=3, per=30, type=commands.BucketType.user)
    async def poke(self, ctx: commands.Context, user: discord.Member = None):
        user = user or ctx.author
        gif = await _fetch_gif("poke")
        target = user.display_name if user.id != ctx.author.id else "themselves"
        await self._react(ctx, gif, f"{ctx.author.display_name} poked {target}! 👉")

    @commands.command(name="wink", help="Wink at someone! Usage: nwink @user")
    @commands.cooldown(rate=3, per=30, type=commands.BucketType.user)
    async def wink(self, ctx: commands.Context, user: discord.Member = None):
        user = user or ctx.author
        gif = await _fetch_gif("wink")
        target = user.display_name if user.id != ctx.author.id else "themselves"
        await self._react(ctx, gif, f"{ctx.author.display_name} winked at {target}! 😉")

    # ── Solo commands ──────────────────────────────────────────────────────

    @commands.command(name="cry", help="Cry! Usage: ncry")
    @commands.cooldown(rate=3, per=30, type=commands.BucketType.user)
    async def cry(self, ctx: commands.Context):
        gif = await _fetch_gif("cry")
        await self._react(ctx, gif, f"{ctx.author.display_name} is crying! 😢")

    @commands.command(name="dance", help="Dance! Usage: ndance")
    @commands.cooldown(rate=3, per=30, type=commands.BucketType.user)
    async def dance(self, ctx: commands.Context):
        gif = await _fetch_gif("dance")
        await self._react(ctx, gif, f"{ctx.author.display_name} is dancing! 💃")

    @commands.command(name="laugh", help="Laugh! Usage: nlaugh")
    @commands.cooldown(rate=3, per=30, type=commands.BucketType.user)
    async def laugh(self, ctx: commands.Context):
        gif = await _fetch_gif("laugh")
        await self._react(ctx, gif, f"{ctx.author.display_name} is laughing! 😂")

    @commands.command(name="smile", help="Smile! Usage: nsmile")
    @commands.cooldown(rate=3, per=30, type=commands.BucketType.user)
    async def smile(self, ctx: commands.Context):
        gif = await _fetch_gif("smile")
        await self._react(ctx, gif, f"{ctx.author.display_name} is smiling! 😊")

    @commands.command(name="confused", help="Show confusion! Usage: nconfused")
    @commands.cooldown(rate=3, per=30, type=commands.BucketType.user)
    async def confused(self, ctx: commands.Context):
        gif = await _fetch_gif("think")
        await self._react(ctx, gif, f"{ctx.author.display_name} is confused! 🤔")

    @commands.command(name="blush", help="Blush! Usage: nblush")
    @commands.cooldown(rate=3, per=30, type=commands.BucketType.user)
    async def blush(self, ctx: commands.Context):
        gif = await _fetch_gif("blush")
        await self._react(ctx, gif, f"{ctx.author.display_name} is blushing! 😳")

    @commands.command(name="sleep", help="Sleep! Usage: nsleep")
    @commands.cooldown(rate=3, per=30, type=commands.BucketType.user)
    async def sleep(self, ctx: commands.Context):
        gif = await _fetch_gif("sleep")
        await self._react(ctx, gif, f"{ctx.author.display_name} is sleeping! 😴")

    @commands.command(name="shrug", help="Shrug! Usage: nshrug")
    @commands.cooldown(rate=3, per=30, type=commands.BucketType.user)
    async def shrug(self, ctx: commands.Context):
        gif = await _fetch_gif("shrug")
        await self._react(ctx, gif, f"{ctx.author.display_name} shrugged! 🤷")

    @commands.command(name="nod", help="Nod! Usage: nnod")
    @commands.cooldown(rate=3, per=30, type=commands.BucketType.user)
    async def nod(self, ctx: commands.Context):
        gif = await _fetch_gif("nod")
        await self._react(ctx, gif, f"{ctx.author.display_name} nodded! 😌")

    @commands.command(name="triggered", help="Get triggered! Usage: ntriggered")
    @commands.cooldown(rate=3, per=30, type=commands.BucketType.user)
    async def triggered(self, ctx: commands.Context):
        gif = await _fetch_gif("triggered")
        await self._react(ctx, gif, f"{ctx.author.display_name} is triggered! 😤")


async def setup(bot: commands.Bot):
    await bot.add_cog(FunCog(bot))
