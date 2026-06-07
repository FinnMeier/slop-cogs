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
