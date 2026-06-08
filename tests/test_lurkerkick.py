import pytest
import discord
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta

from lurkerkick.lurkerkick import LurkerKick

@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.loop.create_task = MagicMock()
    return bot

@pytest.fixture
def cog(mock_bot):
    with patch("redbot.core.Config.get_conf") as mock_get_conf, patch("discord.ext.tasks.Loop.start") as mock_start:
        # Mock the config entirely
        mock_config = MagicMock()
        mock_get_conf.return_value = mock_config

        return LurkerKick(mock_bot)

@pytest.fixture
def mock_guild():
    guild = MagicMock(spec=discord.Guild)
    guild.id = 123
    guild.name = "Test Guild"
    return guild

@pytest.fixture
def mock_member():
    member = MagicMock(spec=discord.Member)
    member.id = 456
    member.name = "TestUser"
    member.discriminator = "0001"
    member.bot = False
    member.guild_permissions.administrator = False
    member.roles = []

    # Needs to be aware datetime for join
    now = datetime.now(timezone.utc)
    member.joined_at = now - timedelta(days=40)
    return member

@pytest.mark.asyncio
async def test_get_inactive_users_finds_inactive(cog, mock_guild, mock_member):
    # Setup mock config values
    now = datetime.now(timezone.utc)

    # User was last active 35 days ago
    last_active = (now - timedelta(days=35)).timestamp()

    # Tracking started 40 days ago
    tracking_started = (now - timedelta(days=40)).timestamp()

    mock_guild.members = [mock_member]

    # Mock the return values from Config
    # await self.config.guild(guild).all()
    cog.config.guild.return_value.all = AsyncMock(return_value={
        "inactivity_days": 30,
        "excluded_roles": [],
        "tracking_started": tracking_started
    })

    # await self.config.member(member).last_active()
    cog.config.member.return_value.last_active = AsyncMock(return_value=last_active)

    inactive_users = await cog._get_inactive_users(mock_guild)

    assert len(inactive_users) == 1
    assert inactive_users[0][0] == mock_member
    assert inactive_users[0][1] == 35

@pytest.mark.asyncio
async def test_get_inactive_users_ignores_active(cog, mock_guild, mock_member):
    now = datetime.now(timezone.utc)

    # User was last active 10 days ago (threshold is 30)
    last_active = (now - timedelta(days=10)).timestamp()
    tracking_started = (now - timedelta(days=40)).timestamp()

    mock_guild.members = [mock_member]

    cog.config.guild.return_value.all = AsyncMock(return_value={
        "inactivity_days": 30,
        "excluded_roles": [],
        "tracking_started": tracking_started
    })

    cog.config.member.return_value.last_active = AsyncMock(return_value=last_active)

    inactive_users = await cog._get_inactive_users(mock_guild)

    assert len(inactive_users) == 0

@pytest.mark.asyncio
async def test_get_inactive_users_ignores_excluded_role(cog, mock_guild, mock_member):
    now = datetime.now(timezone.utc)
    last_active = (now - timedelta(days=35)).timestamp()
    tracking_started = (now - timedelta(days=40)).timestamp()

    # Add an excluded role to the member
    mock_role = MagicMock(spec=discord.Role)
    mock_role.id = 999
    mock_member.roles = [mock_role]

    mock_guild.members = [mock_member]

    cog.config.guild.return_value.all = AsyncMock(return_value={
        "inactivity_days": 30,
        "excluded_roles": [999], # Role ID 999 is excluded
        "tracking_started": tracking_started
    })

    cog.config.member.return_value.last_active = AsyncMock(return_value=last_active)

    inactive_users = await cog._get_inactive_users(mock_guild)

    # User should be ignored due to the role, even though they are inactive
    assert len(inactive_users) == 0

@pytest.mark.asyncio
async def test_get_inactive_users_handles_none_last_active(cog, mock_guild, mock_member):
    now = datetime.now(timezone.utc)
    tracking_started = (now - timedelta(days=40)).timestamp()

    # Member joined 40 days ago, has never sent a message (last_active is None)
    mock_guild.members = [mock_member]

    cog.config.guild.return_value.all = AsyncMock(return_value={
        "inactivity_days": 30,
        "excluded_roles": [],
        "tracking_started": tracking_started
    })

    cog.config.member.return_value.last_active = AsyncMock(return_value=None)

    inactive_users = await cog._get_inactive_users(mock_guild)

    # Should calculate from tracking_started (40 days inactive)
    assert len(inactive_users) == 1
    assert inactive_users[0][0] == mock_member
    assert inactive_users[0][1] == 40

@pytest.mark.asyncio
async def test_process_guild_kicks_users_without_dm(cog, mock_guild, mock_member):
    # Setup member kick method to be async and successful
    mock_member.kick = AsyncMock()

    # Create users_to_kick list
    users_to_kick = [(mock_member, 35, "days")]

    # Mock config settings
    cog.config.guild.return_value.all = AsyncMock(return_value={
        "is_active": True,
        "log_channel": None,
        "dm_on_kick": False,
        "dm_message": "",
        "tracking_started": datetime.now(timezone.utc).timestamp() - 86400 * 40
    })

    # Call _process_guild
    kicked, failed = await cog._process_guild(mock_guild, manual=True, users_to_kick=users_to_kick)

    # Asserts
    mock_guild.kick.assert_called_once_with(mock_member, reason="LurkerKick: Inactive for 35 days")
    assert len(kicked) == 1
    assert kicked[0] == f"{mock_member.name}#{mock_member.discriminator} ({mock_member.id}) - 35 days inactive"
    assert len(failed) == 0


@pytest.mark.asyncio
async def test_process_guild_kicks_users_with_dm(cog, mock_guild, mock_member):
    # Setup member kick method and send method
    mock_member.kick = AsyncMock()
    mock_member.send = AsyncMock()

    # Create users_to_kick list
    users_to_kick = [(mock_member, 35, "days")]

    # Mock config settings
    cog.config.guild.return_value.all = AsyncMock(return_value={
        "is_active": True,
        "log_channel": None,
        "dm_on_kick": True,
        "dm_message": "Hello {user_name}, you are kicked from {guild_name} for {duration} {unit} inactivity.",
        "tracking_started": datetime.now(timezone.utc).timestamp() - 86400 * 40
    })

    # Call _process_guild
    kicked, failed = await cog._process_guild(mock_guild, manual=True, users_to_kick=users_to_kick)

    # Asserts
    mock_member.send.assert_called_once_with("Hello TestUser, you are kicked from Test Guild for 35 days inactivity.")
    mock_guild.kick.assert_called_once_with(mock_member, reason="LurkerKick: Inactive for 35 days")
    assert len(kicked) == 1
    assert kicked[0] == f"{mock_member.name}#{mock_member.discriminator} ({mock_member.id}) - 35 days inactive"
    assert len(failed) == 0


@pytest.mark.asyncio
async def test_process_guild_handles_kick_failures(cog, mock_guild, mock_member):
    # Setup member kick method to fail (e.g. Forbidden)
    mock_response = MagicMock()
    mock_response.status = 403
    mock_guild.kick = AsyncMock(side_effect=discord.Forbidden(mock_response, "Missing Permissions"))

    # Create users_to_kick list
    users_to_kick = [(mock_member, 35, "days")]

    # Mock config settings
    cog.config.guild.return_value.all = AsyncMock(return_value={
        "is_active": True,
        "log_channel": None,
        "dm_on_kick": False,
        "dm_message": "",
        "tracking_started": datetime.now(timezone.utc).timestamp() - 86400 * 40
    })

    # Call _process_guild
    kicked, failed = await cog._process_guild(mock_guild, manual=True, users_to_kick=users_to_kick)

    # Asserts
    mock_guild.kick.assert_called_once_with(mock_member, reason="LurkerKick: Inactive for 35 days")
    assert len(kicked) == 0
    assert len(failed) == 1
    assert failed[0] == f"{mock_member.name}#{mock_member.discriminator} ({mock_member.id}) - Missing permissions"

@pytest.fixture
def mock_ctx(mock_guild):
    ctx = MagicMock()
    ctx.guild = mock_guild
    ctx.send = AsyncMock()
    return ctx

@pytest.mark.asyncio
async def test_setdays_updates_inactivity_days(cog, mock_ctx):
    # Setup mock to simulate config set
    cog.config.guild.return_value.inactivity_days.set = AsyncMock()

    # Call the command (note: the framework usually unwraps the command, but we can call callback)
    await cog.setdays.callback(cog, mock_ctx, 14)

    # Asserts
    cog.config.guild.return_value.inactivity_days.set.assert_called_once_with(14)
    mock_ctx.send.assert_called_once_with("Inactivity threshold set to **14 days**.")

@pytest.mark.asyncio
async def test_setdays_rejects_low_values(cog, mock_ctx):
    # Call the command with 0
    await cog.setdays.callback(cog, mock_ctx, 0)

    # Asserts
    mock_ctx.send.assert_called_once_with("Days must be at least 1.")

@pytest.mark.asyncio
async def test_toggle_enables_and_disables(cog, mock_ctx):
    # Mock current state as False
    cog.config.guild.return_value.is_active = AsyncMock(return_value=False)
    cog.config.guild.return_value.is_active.set = AsyncMock()

    # Call toggle
    await cog.toggle.callback(cog, mock_ctx)

    # Asserts
    cog.config.guild.return_value.is_active.set.assert_called_once_with(True)
    mock_ctx.send.assert_called_once_with("Automatic lurker kicking has been **enabled**.")

    # Reset mocks
    mock_ctx.send.reset_mock()
    cog.config.guild.return_value.is_active.set.reset_mock()

    # Mock current state as True
    cog.config.guild.return_value.is_active = AsyncMock(return_value=True)

    # Call toggle again
    await cog.toggle.callback(cog, mock_ctx)

    # Asserts
    cog.config.guild.return_value.is_active.set.assert_called_once_with(False)
    mock_ctx.send.assert_called_once_with("Automatic lurker kicking has been **disabled**.")


@pytest.mark.asyncio
async def test_ignorerole_adds_and_removes(cog, mock_ctx):
    mock_role = MagicMock(spec=discord.Role)
    mock_role.id = 999
    mock_role.name = "Test Role"

    # We need to mock the async context manager returned by excluded_roles()
    class AsyncContextManagerMock:
        def __init__(self, data):
            self.data = data
        async def __aenter__(self):
            return self.data
        async def __aexit__(self, exc_type, exc, tb):
            pass

    # First test: Add role
    roles_list = []
    cog.config.guild.return_value.excluded_roles = MagicMock(return_value=AsyncContextManagerMock(roles_list))

    await cog.ignorerole.callback(cog, mock_ctx, mock_role)

    assert 999 in roles_list
    mock_ctx.send.assert_called_once_with("Added **Test Role** to the ignored roles list. Users with this role will no longer be kicked.")

    # Second test: Remove role
    mock_ctx.send.reset_mock()
    roles_list = [999]
    cog.config.guild.return_value.excluded_roles = MagicMock(return_value=AsyncContextManagerMock(roles_list))

    await cog.ignorerole.callback(cog, mock_ctx, mock_role)

    assert 999 not in roles_list
    mock_ctx.send.assert_called_once_with("Removed **Test Role** from the ignored roles list.")
