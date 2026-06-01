"""
Help Cog
Dropdown-based help command using LayoutView.
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
    "🤖 AI": (
        "`/ask <prompt>` – Chat with AI\n"
        "`/clearhistory` – Clear your AI conversation history"
    ),
    "🧱 Roblox": (
        "`/roblox group` – Display Roblox group info\n"
        "`/roblox profile <user>` – View a player's profile\n"
        "`/roblox avatar <user>` – View a player's full-body avatar\n"
        "`/roblox game <id>` – Get detailed game info\n"
        "`/roblox icon <id>` – Fetch a game's official icon\n"
        "`/roblox asset <id>` – Fetch full Roblox asset info\n"
        "`/roblox community <query>` – Search public Roblox groups\n"
        "`/roblox stocks` – Check Robux balances\n"
        "`/roblox gamepass <id>` – Generate a direct Gamepass link\n"
        "`/roblox devex <robux>` – Convert Robux ↔ USD (DevEx rate)\n"
        "`/roblox tax <robux>` – Calculate Roblox's 30% marketplace tax\n"
        "`/roblox checkpayout <user>` – Verify payout eligibility\n"
        "`/roblox rank <user>` – Promote a Roblox user to Rank 6\n"
        "`/roblox login` – View private account details (Owner)\n"
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
        "`/payment <method>` – Show payment instructions (Gcash / PayMaya / GoTyme)\n"
        "`/mexc` – Top 10 cryptos by 24h volume on MEXC\n"
        "`/status` – Bot health, uptime & system stats\n"
        "`/invite` – Get the bot invite link\n"
        "`/membercount` – Show member breakdown (total / humans / bots)\n"
        "`/boostcount` – Show server boost count & Nitro level\n"
        "`/roleinfo <role>` – Display detailed info about a role\n"
        "`/firstmessage [channel]` – Link to the first message in a channel"
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
        "`/stickypin` – Create and manage sticky-pinned messages in a channel\n"
        "`/nuke [channel]` – Clone a channel to delete all messages (Admin)\n"
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
        "`/steal` – Right-click a message → Apps → Steal Emoji/Sticker\n"
        "`/addemoji <emoji>` – Add any emoji to this server instantly\n"
        "`/ar add/remove/list` – Manage autoresponders\n"
        "`/react add/remove/list` – Manage autoreacts\n"
        "`/vm setup` – Set up VoiceMaster channels\n"
        "`/vm remove` – Remove VoiceMaster"
    ),
    "🔒 Antinuke": (
        "`/antinuke enable` – Enable antinuke protection (17 modules)\n"
        "`/antinuke disable` – Disable antinuke protection\n"
        "`/whitelist <user>` – Whitelist a user from antinuke actions\n"
        "`/unwhitelist <user>` – Remove a user from the whitelist\n"
        "`/whitelisted` – View all whitelisted users\n"
        "`/whitelistreset` – Clear all whitelisted users\n"
        "`/antinuke extraowner add <user>` – Grant extra-owner access\n"
        "`/antinuke extraowner remove <user>` – Revoke extra-owner access\n"
        "`/antinuke extraowner list` – List all extra owners"
    ),
    "🤖 Automod": (
        "`/automod enable` – Enable automod (select which events)\n"
        "`/automod disable` – Disable automod & clear all settings\n"
        "`/automod punishment` – Change punishment per event (Mute/Kick/Ban)\n"
        "`/automod config` – View all current automod settings\n"
        "`/automod logging <channel>` – Set the automod log channel\n"
        "`/automod ignore channel <channel>` – Exempt a channel\n"
        "`/automod ignore role <role>` – Exempt a role\n"
        "`/automod ignore show` – View all exemptions\n"
        "`/automod ignore reset` – Clear all exemptions\n"
        "`/automod unignore channel <channel>` – Remove channel exemption\n"
        "`/automod unignore role <role>` – Remove role exemption"
    ),
    "🎵 Music": (
        "`/play <song>` – Play a song or add it to the queue\n"
        "`/pause` – Pause the current track\n"
        "`/resume` – Resume a paused track\n"
        "`/skip` – Skip to the next track\n"
        "`/stop` – Stop playback and disconnect\n"
        "`/loop` – Toggle looping the current track\n"
        "`/autoplay` – Toggle autoplay (recommends tracks after queue ends)\n"
        "`/volume [0–100]` – Get or set the player volume\n"
        "`/nowplaying` – Show current track info and controls\n"
        "`/queue` – View the full track queue\n"
        "`/seek <seconds>` – Jump to a position in the current track\n"
        "`/music setup [channel]` – Set a dedicated music channel (Admin)\n"
        "`/music reset` – Remove the dedicated music channel (Admin)\n"
        "`/music settings` – View music configuration (Admin)"
    ),
    "🎉 Fun": (
        "-# Fun commands use the `n` prefix — just type them without a space (e.g. `nslap @user`)\n\n"
        "`nslap [@user]` – Slap someone with a GIF\n"
        "`nhug [@user]` – Hug someone with a GIF\n"
        "`nkiss [@user]` – Kiss someone with a GIF\n"
        "`npat [@user]` – Pat someone with a GIF\n"
        "`nangry [@user]` – Express anger at someone\n"
        "`ncuddle [@user]` – Cuddle with someone\n"
        "`nwave [@user]` – Wave at someone\n"
        "`nhighfive [@user]` – High five someone\n"
        "`npoke [@user]` – Poke someone\n"
        "`nwink [@user]` – Wink at someone\n"
        "`ncry` – Cry with a GIF\n"
        "`ndance` – Dance with a GIF\n"
        "`nlaugh` – Laugh with a GIF\n"
        "`nsmile` – Smile with a GIF\n"
        "`nconfused` – Show confusion\n"
        "`nblush` – Blush with a GIF\n"
        "`nsleep` – Sleep with a GIF\n"
        "`nshrug` – Shrug with a GIF\n"
        "`nnod` – Nod with a GIF\n"
        "`ntriggered` – Get triggered with a GIF"
    ),
    "🎤 Voice Control": (
        "`/vcmute <member>` – Server-mute a member in VC\n"
        "`/vcunmute <member>` – Remove server-mute from a member\n"
        "`/vcdeafen <member>` – Server-deafen a member in VC\n"
        "`/vcundeafen <member>` – Remove server-deafen from a member\n"
        "`/vcmove <member> <channel>` – Move a member to another VC\n"
        "`/vcmoveall <from> <to>` – Move all members between VCs\n"
        "`/vckick <member>` – Kick a member from their VC"
    ),
    "🎫 Tickets": (
        "`/ticket setup <category> [support_role] [log_channel]` – Set up the ticket system\n"
        "`/ticket panel` – Post the ticket creation panel in the current channel\n"
        "`/ticket close` – Close the current ticket\n"
        "`/ticket delete` – Delete the current ticket channel\n"
        "`/ticket add <member>` – Add a member to the current ticket\n"
        "`/ticket remove <member>` – Remove a member from the current ticket\n"
        "`/ticket info` – View info about the current ticket"
    ),
    "👋 Welcomer": (
        "`/welcomer setup <channel>` – Set the welcome message channel\n"
        "`/welcomer message <text>` – Customize the welcome message\n"
        "   Placeholders: `{user.mention}` `{user.name}` `{user.id}` `{server.name}` `{member.count}`\n"
        "`/welcomer embed <true/false>` – Toggle embed vs plain text\n"
        "`/welcomer disable` – Disable welcome messages\n"
        "`/welcomer test` – Send a test welcome message\n"
        "`/welcomer view` – View current welcomer settings"
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

        total = len(CATEGORY_COMMANDS)
        section = Section(
            TextDisplay(
                "### <a:butterflys:1408105261226266738> __Neroniel__ is **ready!**\n"
                f"> Pick from **{total} categories** below to see all available commands.\n"
                "> Slash commands use `/` · Fun commands use the `n` prefix (e.g. `nslap`)"
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
