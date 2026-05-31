"""
Help Cog
Dropdown-based help command using LayoutView (from Meeklys-Src design).
Available as both /help (slash) and !help (prefix) and on bot mention.
"""

import discord
from discord import app_commands
from discord.ext import commands
from discord import SelectOption
from discord.ui import (
    LayoutView,
    Container,
    Section,
    TextDisplay,
    Separator,
    Select,
    ActionRow,
    Thumbnail,
)

CATEGORY_COMMANDS = {
    "🤖 AI": "`/ask <prompt>` – Chat with AI\n`/clearhistory` – Clear your AI conversation history",
    "🧱 Roblox": (
        "`/roblox group` – Display Roblox group info\n"
        "`/roblox profile <user>` – View a player's profile\n"
        "`/roblox game <id>` – Get game info\n"
        "`/roblox stocks` – Check Robux balances\n"
        "`/roblox rate` – Set global minimum conversion rates (Owner)"
    ),
    "💱 Currency": (
        "`/payout <type> <amount>` – Convert Robux ↔ PHP (Payout rate)\n"
        "`/gift <type> <amount>` – Convert Robux ↔ PHP (Gift rate)\n"
        "`/nct <type> <amount>` – Convert Robux ↔ PHP (NCT rate)\n"
        "`/ct <type> <amount>` – Convert Robux ↔ PHP (CT rate)\n"
        "`/allrates <type> <amount>` – Compare all 4 rates at once\n"
        "`/setrate` – Update this server's active rates (Admin)\n"
        "`/resetrate` – Clear active rates for this server (Admin)\n"
        "`/convertcurrency <amount> <from> <to>` – Convert real-world currencies\n"
        "`/viewrates` – View all server rates (Owner)\n"
        "`/forceresetallrates` – Reset all servers' rates (Owner)"
    ),
    "🛠️ Utility": (
        "`/userinfo [user]` – View Discord account details\n"
        "`/serverinfo` – Display server stats\n"
        "`/avatar [user]` – View profile picture\n"
        "`/banner [user]` – View profile banner\n"
        "`/weather <city>` – Get live weather data\n"
        "`/calculator <num1> <op> <num2>` – Basic math\n"
        "`/payment <method>` – Show payment instructions\n"
        "`/mexc` – Top 10 cryptos by 24h volume on MEXC\n"
        "`/status` – Bot health & uptime\n"
        "`/invite` – Get the bot invite link"
    ),
    "📢 Giveaways": (
        "`/giveaway <prize> <duration> <winners>` – Start a giveaway\n"
        "`/giveawayend <id>` – End a giveaway early\n"
        "`/giveawayreroll <id>` – Pick new winners"
    ),
    "📨 Invites": (
        "`/invites [user]` – Check how many members someone has invited\n"
        "`/invitehistory [user]` – Timestamped log of invited members\n"
        "`/invitestats` – Server-wide joins, leaves & net invites\n"
        "`/inviteleaderboard` – Top 10 inviters in this server\n"
        "`/adjustinvites <user> <amount>` – Add or remove invites (Admin)\n"
        "`/resetinvites <user>` – Reset a user's invite count (Admin)"
    ),
    "📱 Social": (
        "`/tiktok <link>` – Download and send a TikTok video\n"
        "`/instagram <link>` – Convert Instagram post/reel to preview\n"
        "`/poll <question> <duration>` – Create a timed poll\n"
        "`/remindme <duration> <note>` – Set a personal reminder\n"
        "`/snipe` – Show the last deleted message\n"
        "`/editsnipe` – Show the last edited message\n"
        "`/donate <user> <amount>` – Playfully donate Robux (cosmetic)"
    ),
    "🔧 Admin": (
        "`/purge <amount>` – Bulk-delete messages\n"
        "`/announcement` – Create a server announcement\n"
        "`/say <message>` – Make the bot send a message\n"
        "`/dm <user> <message>` – DM a user (Owner)\n"
        "`/dmall <message>` – DM all members (Owner)\n"
        "`/createinvite` – Generate invites for all servers (Owner)"
    ),
    "🛡️ Moderation": (
        "`/warn <user> [reason]` – Warn a member\n"
        "`/ban <user> [reason]` – Ban a member\n"
        "`/unban <user_id> [reason]` – Unban a user by ID\n"
        "`/kick <user> [reason]` – Kick a member\n"
        "`/mute <user> [reason]` – Timeout a member (28 days)\n"
        "`/unmute <user> [reason]` – Remove a member's timeout\n"
        "`/lock` – Lock the current channel\n"
        "`/unlock` – Unlock the current channel\n"
        "`/hide` – Hide the current channel from @everyone\n"
        "`/unhide` – Unhide the current channel"
    ),
    "⚙️ Extras": (
        "`/ping` – Check bot latency\n"
        "`/uptime` – Show how long the bot has been online\n"
        "`/steal` – Right-click a message → Apps → Steal Emoji/Sticker\n"
        "`/timer <seconds>` – Set a countdown timer\n"
        "`/ar add/remove/list` – Manage autoresponders\n"
        "`/react add/remove/list` – Manage autoreacts\n"
        "`/boys` / `/girls` / `/pic` – Random pfp/gif\n"
        "`/vm setup` – Set up VoiceMaster channels\n"
        "`/vm remove` – Remove VoiceMaster"
    ),
}


class HelpView(LayoutView):
    def __init__(self, bot: commands.Bot, author_id: int):
        super().__init__(timeout=120)
        self.bot = bot
        self.author_id = author_id

        options = [
            SelectOption(label=category, description=f"View {category} commands")
            for category in CATEGORY_COMMANDS
        ]

        self.dropdown = Select(
            placeholder="Choose a category...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="help_category_select",
        )
        self.dropdown.callback = self.on_select

        section = Section(
            TextDisplay(
                "### <a:butterflys:1408105261226266738> __Neroniel__ is **ready!**\n"
                "> Pick a category below to see all available commands.\n"
                "> All commands use `/` slash syntax."
            ),
            accessory=Thumbnail(
                media=discord.UnfurledMediaItem(url=bot.user.display_avatar.url),
                description="Neroniel Help",
            ),
            id=1,
        )

        container = Container(
            section,
            Separator(),
            TextDisplay("-# Use the dropdown to explore commands."),
            ActionRow(self.dropdown),
        )

        self.add_item(container)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "<:cross:1408031235057385564> This help menu isn't for you. Run `/help` yourself.",
                ephemeral=True,
            )
            return False
        return True

    async def on_select(self, interaction: discord.Interaction):
        category = self.dropdown.values[0]
        commands_text = CATEGORY_COMMANDS.get(category, "No commands found.")

        section = Section(
            TextDisplay(f"# {category}\n{commands_text}"),
            accessory=Thumbnail(
                media=discord.UnfurledMediaItem(url=self.bot.user.display_avatar.url),
                description=f"{category}",
            ),
            id=2,
        )

        container = Container(
            section,
            Separator(),
            TextDisplay("-# Use the dropdown to view another category."),
            ActionRow(self.dropdown),
        )

        self.clear_items()
        self.add_item(container)
        await interaction.response.edit_message(view=self)


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Show all available commands")
    async def help_slash(self, interaction: discord.Interaction):
        view = HelpView(self.bot, interaction.user.id)
        await interaction.response.send_message(view=view)

    @commands.command(name="help", aliases=["h"])
    async def help_prefix(self, ctx: commands.Context):
        view = HelpView(self.bot, ctx.author.id)
        await ctx.send(view=view)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        stripped = message.content.strip()
        if stripped in (self.bot.user.mention, f"<@!{self.bot.user.id}>"):
            view = HelpView(self.bot, message.author.id)
            await message.channel.send(view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(HelpCog(bot))
