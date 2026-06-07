# LurkerKick

LurkerKick is a cog for [Red-DiscordBot V3](https://github.com/Cog-Creators/Red-DiscordBot) that automatically or manually kicks inactive users (lurkers) from your server.

By default, Discord does not tell bots when a user last sent a message. This cog tracks messages from the moment it is loaded to determine user activity, kicking those who do not speak for a configurable number of days.

## Features
- **Configurable Timeframe**: Set how many days a user can be inactive before being kicked (default is 30 days).
- **Role Exclusions**: Specify roles that should be immune to lurker kicks.
- **Auto-Exclusions**: Server Administrators and Bots are always immune.
- **Safety Checks**: The bot waits until the full inactivity timeframe has elapsed after enabling before kicking anyone, to avoid accidental server purges.
- **DM Reasoning**: Users receive a direct message explaining why they were kicked from the server.
- **Logging**: Configurable logging channel to keep track of kicked users.
- **Manual Trigger**: Manually run the kick process outside of the 24-hour automatic loop.

## Installation

Ensure the `lurkerkick` directory is in one of your bot's cog paths. Then load it:
```
[p]load lurkerkick
```
*(Replace `[p]` with your bot's prefix.)*

## Commands

All commands require Administrator permissions.

* `[p]lurkerkick toggle`
  Toggles automatic lurker kicking on or off for the server.

* `[p]lurkerkick setdays <days>`
  Sets the number of days of inactivity required before a user is kicked.

* `[p]lurkerkick logchannel [channel]`
  Sets the channel where kicks will be logged. Leave the channel blank to disable logging.

* `[p]lurkerkick ignorerole <role>`
  Adds or removes a role from the ignored list. Users with this role will not be kicked.

* `[p]lurkerkick settings`
  Displays the current settings for the server.

* `[p]lurkerkick runnow`
  Manually triggers the lurker kick process for the server right now.

## Important Note

- **Tracking Behavior:** Because Discord does not provide historical message data without scanning every channel (which is extremely resource-intensive), this cog relies on tracking messages. Tracking begins globally for all servers as soon as the cog is loaded on your bot. This means if you set the inactivity threshold to 30 days, the bot will not kick anyone until 30 days have passed since the cog was first loaded or joined your server. You can safely keep `[p]lurkerkick toggle` disabled and manually use `[p]lurkerkick runnow` once the inactivity period has passed.
- **On-Load Execution:** The automated background check is scheduled to run every 24 hours. However, the first check happens **immediately** upon the cog being loaded or reloaded (`[p]load lurkerkick`). If you have the cog enabled for your server and previously enabled test mode, loading the cog may result in immediate kicks based on your saved settings. Always ensure your settings are correct before reloading if the cog is active.
