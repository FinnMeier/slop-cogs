import asyncio
import discord
from redbot.core import Config, commands, checks
from redbot.core.utils.chat_formatting import pagify
from discord.ext import tasks
from datetime import datetime, timezone, timedelta
import logging

log = logging.getLogger("red.lurkerkick")

class LurkerKick(commands.Cog):
    """
    Kicks inactive users (lurkers) periodically or manually.
    Configurable timeframe, excluded roles, and logging.
    """

    def __init__(self, bot):
        self.bot = bot

        # Decision: Use Red's Config to store per-guild settings and per-member last_active timestamps.
        # This allows each server to have its own settings and tracks members independently.
        self.config = Config.get_conf(self, identifier=1234567890123456, force_registration=True)

        default_guild = {
            "inactivity_days": 30, # Default: no messages in 30 days
            "excluded_roles": [],  # List of role IDs to ignore
            "log_channel": None,   # Channel ID for logging kicks
            "is_active": False,    # Whether the background task is running for this guild
            "tracking_started": None, # Timestamp when tracking started for the guild to ensure we don't kick early
            "dm_on_kick": False    # Whether to DM users when they are kicked
        }

        default_member = {
            "last_active": None # Timestamp of last sent message
        }

        self.config.register_guild(**default_guild)
        self.config.register_member(**default_member)

        # Decision: Use a background task running every 24 hours (a common global default period)
        # to check for inactive users and kick them if they exceed the threshold.
        self.lurker_check.start()

    def cog_unload(self):
        self.lurker_check.cancel()

    @tasks.loop(hours=24)
    async def lurker_check(self):
        """Background task that runs every 24 hours to kick inactive users."""
        for guild in self.bot.guilds:
            await self._process_guild(guild)

    @lurker_check.before_loop
    async def before_lurker_check(self):
        await self.bot.wait_until_red_ready()

    async def _get_inactive_users(self, guild: discord.Guild):
        """
        Returns a list of tuples (member, days_inactive) for users who are inactive
        based on the guild's current settings.
        """
        settings = await self.config.guild(guild).all()

        inactivity_days = settings["inactivity_days"]
        excluded_roles = settings["excluded_roles"]
        tracking_started = settings["tracking_started"]

        if tracking_started is None:
            return []

        tracking_started_time = datetime.fromtimestamp(tracking_started, tz=timezone.utc)

        inactive_users = []
        now = datetime.now(timezone.utc)

        for member in guild.members:
            if member.bot or member.guild_permissions.administrator:
                continue

            has_excluded_role = any(role.id in excluded_roles for role in member.roles)
            if has_excluded_role:
                continue

            last_active_ts = await self.config.member(member).last_active()

            if last_active_ts is None:
                join_time = member.joined_at
                if join_time and join_time.tzinfo is None:
                    join_time = join_time.replace(tzinfo=timezone.utc)

                effective_last_active = tracking_started_time
                if join_time and join_time > effective_last_active:
                    effective_last_active = join_time
            else:
                effective_last_active = datetime.fromtimestamp(last_active_ts, tz=timezone.utc)

            days_inactive = (now - effective_last_active).days

            if days_inactive >= inactivity_days:
                inactive_users.append((member, days_inactive))

        return inactive_users

    async def _process_guild(self, guild: discord.Guild, manual: bool = False, users_to_kick: list = None):
        """
        Process a single guild to check for inactive users.
        """
        settings = await self.config.guild(guild).all()

        # If not active and not triggered manually, skip
        if not settings["is_active"] and not manual:
            return

        log_channel_id = settings["log_channel"]
        tracking_started = settings["tracking_started"]
        dm_on_kick = settings["dm_on_kick"]

        # Decision: Ensure we don't kick anyone before we have tracked them for at least the inactivity period.
        # Otherwise, we'd immediately kick everyone who hasn't sent a message since the cog was loaded!
        if tracking_started is None:
            # This shouldn't happen if they turned it on, but just in case.
            return

        log_channel = guild.get_channel(log_channel_id) if log_channel_id else None

        kicked_users = []

        inactive_users = users_to_kick if users_to_kick is not None else await self._get_inactive_users(guild)

        for member, days_inactive in inactive_users:
            try:
                # Decision: Try to DM the user reasoning before kick as requested
                if dm_on_kick:
                    try:
                        await member.send(f"You have been kicked from {guild.name} due to inactivity ({days_inactive} days without a message).")
                    except discord.Forbidden:
                        # Cannot DM user
                        pass

                await guild.kick(member, reason=f"LurkerKick: Inactive for {days_inactive} days")
                kicked_users.append(f"{member.name}#{member.discriminator} ({member.id}) - {days_inactive} days inactive")
            except discord.Forbidden:
                # Bot lacks permissions to kick this user
                log.error(f"Failed to kick {member.id} from {guild.id} - Missing permissions")
            except discord.HTTPException as e:
                log.error(f"Failed to kick {member.id} from {guild.id} - HTTP Exception: {e}")

        # Log results
        if log_channel and kicked_users:
            message = f"**LurkerKick Purge**\nKicked {len(kicked_users)} inactive users:\n"
            for user_str in kicked_users:
                message += f"- {user_str}\n"

            for page in pagify(message):
                try:
                    await log_channel.send(page)
                except discord.Forbidden:
                    break

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Listener to track when users send messages."""
        if message.author.bot or message.guild is None:
            return

        # Decision: Only track if active, to save resources?
        # Actually, it's better to always track so that if they turn it on later, we have historical data.
        # So we update unconditionally.

        await self.config.member(message.author).last_active.set(message.created_at.replace(tzinfo=timezone.utc).timestamp())

    @commands.group(aliases=["lk"])
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def lurkerkick(self, ctx):
        """Configure the LurkerKick cog."""
        pass

    @lurkerkick.command()
    async def toggle(self, ctx):
        """Toggle automatic lurker kicking on or off for this server."""
        is_active = await self.config.guild(ctx.guild).is_active()

        if is_active:
            await self.config.guild(ctx.guild).is_active.set(False)
            await ctx.send("Automatic lurker kicking has been **disabled**.")
        else:
            await self.config.guild(ctx.guild).is_active.set(True)
            # If tracking never started, start it now
            started = await self.config.guild(ctx.guild).tracking_started()
            if started is None:
                await self.config.guild(ctx.guild).tracking_started.set(datetime.now(timezone.utc).timestamp())
                await ctx.send(f"Automatic lurker kicking has been **enabled**.\n\n"
                               f"**IMPORTANT:** Because the bot just started tracking messages on this server, "
                               f"it will wait until the full inactivity period has passed before kicking anyone "
                               f"who hasn't sent a message.")
            else:
                await ctx.send("Automatic lurker kicking has been **enabled**.")

    @lurkerkick.command()
    async def dmtoggle(self, ctx):
        """Toggle whether users are DMed before being kicked for inactivity."""
        dm_on_kick = await self.config.guild(ctx.guild).dm_on_kick()

        if dm_on_kick:
            await self.config.guild(ctx.guild).dm_on_kick.set(False)
            await ctx.send("DMing users before kick has been **disabled**.")
        else:
            await self.config.guild(ctx.guild).dm_on_kick.set(True)
            await ctx.send("DMing users before kick has been **enabled**.")

    @lurkerkick.command()
    async def setdays(self, ctx, days: int):
        """Set the number of days of inactivity before a user is kicked."""
        if days < 1:
            return await ctx.send("Days must be at least 1.")

        await self.config.guild(ctx.guild).inactivity_days.set(days)
        await ctx.send(f"Inactivity threshold set to **{days} days**.")

    @lurkerkick.command()
    async def logchannel(self, ctx, channel: discord.TextChannel = None):
        """Set the channel where lurker kicks will be logged. Leave blank to disable logging."""
        if channel is None:
            await self.config.guild(ctx.guild).log_channel.set(None)
            await ctx.send("Kick logging has been **disabled**.")
        else:
            await self.config.guild(ctx.guild).log_channel.set(channel.id)
            await ctx.send(f"Kick logging will now go to {channel.mention}.")

    @lurkerkick.command()
    async def ignorerole(self, ctx, role: discord.Role):
        """Add or remove a role from the ignored list. Users with this role will not be kicked."""
        async with self.config.guild(ctx.guild).excluded_roles() as excluded_roles:
            if role.id in excluded_roles:
                excluded_roles.remove(role.id)
                await ctx.send(f"Removed **{role.name}** from the ignored roles list.")
            else:
                excluded_roles.append(role.id)
                await ctx.send(f"Added **{role.name}** to the ignored roles list. Users with this role will no longer be kicked.")

    @lurkerkick.command()
    async def settings(self, ctx):
        """View the current LurkerKick settings for this server."""
        settings = await self.config.guild(ctx.guild).all()

        active_status = "Enabled" if settings["is_active"] else "Disabled"
        days = settings["inactivity_days"]
        channel_id = settings["log_channel"]
        channel_str = f"<#{channel_id}>" if channel_id else "None"

        excluded_roles = settings["excluded_roles"]
        roles_str = ", ".join(f"<@&{r}>" for r in excluded_roles) if excluded_roles else "None"

        started = settings["tracking_started"]
        if started:
            started_time = datetime.fromtimestamp(started, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        else:
            started_time = "Never"

        dm_on_kick_status = "Enabled" if settings["dm_on_kick"] else "Disabled"

        msg = (
            f"**LurkerKick Settings for {ctx.guild.name}**\n"
            f"Status: **{active_status}**\n"
            f"Inactivity Threshold: **{days} days**\n"
            f"Log Channel: **{channel_str}**\n"
            f"DM Users on Kick: **{dm_on_kick_status}**\n"
            f"Ignored Roles: {roles_str}\n"
            f"Tracking Started: {started_time}\n"
        )
        await ctx.send(msg)

    @lurkerkick.command()
    async def runnow(self, ctx):
        """Manually trigger the lurker kick process for this server right now."""
        # Decision: Ensure tracking started so we don't accidentally kick everyone.
        started = await self.config.guild(ctx.guild).tracking_started()
        if started is None:
            # We haven't started tracking, we cannot safely run now.
            # But what if they never toggled it on, but still want to run manually?
            # We MUST track time so we know who is inactive. Since discord doesn't give us
            # "last message sent", we cannot reliably kick without first observing.
            return await ctx.send("Cannot run manually because message tracking has not started. Please enable the cog using `[p]lurkerkick toggle` to begin tracking messages.")

        inactive_users = await self._get_inactive_users(ctx.guild)

        if not inactive_users:
            return await ctx.send("There are currently no inactive users to kick.")

        message = f"**Users to be kicked ({len(inactive_users)}):**\n"
        for member, days_inactive in inactive_users:
            message += f"- {member.name}#{member.discriminator} ({member.id}) - {days_inactive} days inactive\n"

        for page in pagify(message):
            await ctx.send(page)

        await ctx.send("\n**Are you sure you want to kick these users? Reply with `yes` or `no`.**")

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() in ('yes', 'no')

        try:
            msg = await self.bot.wait_for('message', check=check, timeout=30.0)
        except asyncio.TimeoutError:
            return await ctx.send("Confirmation timed out.")
        except Exception:
            return await ctx.send("Confirmation timed out.")

        if msg.content.lower() == 'no':
            return await ctx.send("Manual lurker kick process cancelled.")

        await ctx.send("Running lurker kick process manually...")
        await self._process_guild(ctx.guild, manual=True, users_to_kick=inactive_users)
        await ctx.send("Manual process complete. Check the log channel (if configured) for details.")
