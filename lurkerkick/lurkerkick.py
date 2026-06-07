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
            "dm_on_kick": False,   # Whether to DM users when they are kicked
            "test_mode": False,    # Whether test mode is active
            "test_inactivity_minutes": 5 # Default test mode inactivity minutes
        }

        default_member = {
            "last_active": None # Timestamp of last sent message
        }

        self.config.register_guild(**default_guild)
        self.config.register_member(**default_member)

        # Start background tasks
        self.init_task = self.bot.loop.create_task(self._initialize_tracking())
        self.lurker_check.start()

    async def _initialize_tracking(self):
        """Initialize tracking_started for all guilds globally upon load."""
        await self.bot.wait_until_red_ready()
        now = datetime.now(timezone.utc).timestamp()
        for guild in self.bot.guilds:
            started = await self.config.guild(guild).tracking_started()
            if started is None:
                await self.config.guild(guild).tracking_started.set(now)

    def cog_unload(self):
        if hasattr(self, 'init_task'):
            self.init_task.cancel()
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
        Returns a list of tuples (member, duration, unit) for users who are inactive
        based on the guild's current settings.
        """
        settings = await self.config.guild(guild).all()

        inactivity_days = settings["inactivity_days"]
        test_mode = settings.get("test_mode", False)
        test_inactivity_minutes = settings.get("test_inactivity_minutes", 5)
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

            join_time = member.joined_at
            if join_time and join_time.tzinfo is None:
                join_time = join_time.replace(tzinfo=timezone.utc)

            if last_active_ts is None:
                effective_last_active = tracking_started_time
                if join_time and join_time > effective_last_active:
                    effective_last_active = join_time
            else:
                effective_last_active = datetime.fromtimestamp(last_active_ts, tz=timezone.utc)
                # Decision: If the user rejoined AFTER their last recorded message, their effective activity
                # time should reset to their join time. This prevents instantly kicking rejoining users.
                if join_time and join_time > effective_last_active:
                    effective_last_active = join_time

            delta = now - effective_last_active

            if test_mode:
                minutes_inactive = int(delta.total_seconds() / 60)
                if minutes_inactive >= test_inactivity_minutes:
                    inactive_users.append((member, minutes_inactive, "minutes"))
            else:
                days_inactive = delta.days
                if days_inactive >= inactivity_days:
                    inactive_users.append((member, days_inactive, "days"))

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
        failed_users = []

        inactive_users = users_to_kick if users_to_kick is not None else await self._get_inactive_users(guild)

        for member, duration, unit in inactive_users:
            try:
                # Decision: Try to DM the user reasoning before kick as requested
                if dm_on_kick:
                    try:
                        await member.send(f"You have been kicked from {guild.name} due to inactivity ({duration} {unit} without a message).")
                    except discord.Forbidden:
                        # Cannot DM user
                        pass

                await guild.kick(member, reason=f"LurkerKick: Inactive for {duration} {unit}")
                kicked_users.append(f"{member.name}#{member.discriminator} ({member.id}) - {duration} {unit} inactive")
            except discord.Forbidden:
                # Bot lacks permissions to kick this user
                log.error(f"Failed to kick {member.id} from {guild.id} - Missing permissions")
                failed_users.append(f"{member.name}#{member.discriminator} ({member.id}) - Missing permissions")
            except discord.HTTPException as e:
                log.error(f"Failed to kick {member.id} from {guild.id} - HTTP Exception: {e}")
                failed_users.append(f"{member.name}#{member.discriminator} ({member.id}) - HTTP Exception: {e}")

        # Log results
        if log_channel and (kicked_users or failed_users):
            message = "**LurkerKick Purge**\n"
            if kicked_users:
                message += f"Kicked {len(kicked_users)} inactive users:\n"
                for user_str in kicked_users:
                    message += f"- {user_str}\n"

            if failed_users:
                message += f"\nFailed to kick {len(failed_users)} users:\n"
                for user_str in failed_users:
                    message += f"- {user_str}\n"

            for page in pagify(message):
                try:
                    await log_channel.send(page)
                except discord.Forbidden:
                    break

        return kicked_users, failed_users

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        """Start tracking for new guilds when the bot joins them."""
        started = await self.config.guild(guild).tracking_started()
        if started is None:
            now = datetime.now(timezone.utc).timestamp()
            await self.config.guild(guild).tracking_started.set(now)

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
    async def testmode(self, ctx, minutes: int = None):
        """
        Toggle test mode. If minutes are provided, test mode is enabled with that threshold.
        If test mode is enabled, it checks inactivity in minutes instead of days.
        """
        if minutes is not None:
            if minutes < 1:
                return await ctx.send("Minutes must be at least 1.")
            await self.config.guild(ctx.guild).test_mode.set(True)
            await self.config.guild(ctx.guild).test_inactivity_minutes.set(minutes)
            await ctx.send(f"Test mode **enabled** with inactivity threshold set to **{minutes} minutes**.")
        else:
            is_test_mode = await self.config.guild(ctx.guild).test_mode()
            if is_test_mode:
                await self.config.guild(ctx.guild).test_mode.set(False)
                await ctx.send("Test mode **disabled**. Reverting to standard days-based checks.")
            else:
                await self.config.guild(ctx.guild).test_mode.set(True)
                minutes = await self.config.guild(ctx.guild).test_inactivity_minutes()
                await ctx.send(f"Test mode **enabled** with inactivity threshold set to **{minutes} minutes**.")

    @lurkerkick.command()
    async def toggle(self, ctx):
        """Toggle automatic lurker kicking on or off for this server."""
        is_active = await self.config.guild(ctx.guild).is_active()

        if is_active:
            await self.config.guild(ctx.guild).is_active.set(False)
            await ctx.send("Automatic lurker kicking has been **disabled**.")
        else:
            await self.config.guild(ctx.guild).is_active.set(True)
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
        test_mode_status = "Enabled" if settings.get("test_mode", False) else "Disabled"
        test_mins = settings.get("test_inactivity_minutes", 5)
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
            f"Test Mode: **{test_mode_status}** ({test_mins} minutes)\n"
            f"Log Channel: **{channel_str}**\n"
            f"DM Users on Kick: **{dm_on_kick_status}**\n"
            f"Ignored Roles: {roles_str}\n"
            f"Tracking Started: {started_time}\n"
        )
        await ctx.send(msg)

    @lurkerkick.command()
    async def runnow(self, ctx):
        """Manually trigger the lurker kick process for this server right now."""
        started = await self.config.guild(ctx.guild).tracking_started()
        if started is None:
            return await ctx.send("Message tracking is still initializing. Please try again in a moment.")

        inactive_users = await self._get_inactive_users(ctx.guild)

        if not inactive_users:
            return await ctx.send("There are currently no inactive users to kick.")

        message = f"**Users to be kicked ({len(inactive_users)}):**\n"
        for member, duration, unit in inactive_users:
            message += f"- {member.name}#{member.discriminator} ({member.id}) - {duration} {unit} inactive\n"

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
        kicked_users, failed_users = await self._process_guild(ctx.guild, manual=True, users_to_kick=inactive_users)

        summary = "Manual process complete. Check the log channel (if configured) for details.\n"
        if failed_users:
            summary += f"\n**Warning:** Failed to kick {len(failed_users)} users (likely due to missing permissions or hierarchy). Check logs for details."

            # Show the first few failures directly to the user in the channel
            fail_list = "\n".join(f"- {f}" for f in failed_users[:5])
            if len(failed_users) > 5:
                fail_list += f"\n... and {len(failed_users) - 5} more."

            for page in pagify(f"{summary}\n\n**Failed Kicks:**\n{fail_list}"):
                await ctx.send(page)
        else:
            await ctx.send(summary)
