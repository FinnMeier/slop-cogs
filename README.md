# Custom Cogs for Red-DiscordBot

This repository contains custom cogs designed for use with [Red-DiscordBot V3](https://github.com/Cog-Creators/Red-DiscordBot).

## Available Cogs

### [LurkerKick](./lurkerkick)
A cog to automatically or manually kick inactive users (lurkers) from your server. Features include:
- Configurable inactivity timeframes.
- Role-based exclusions to protect specific users from being kicked.
- Customizable log channels to track kicks.
- DM notifications explaining the kick reason to users before they are removed.

Please refer to the [LurkerKick README](./lurkerkick/README.md) for full installation and configuration instructions.

## Installation

To install these cogs on your Red-DiscordBot instance, you can use the built-in downloader cog to add this repository as a source. Assuming you have the `Downloader` cog loaded:

1. Add the repo:
   ```
   [p]repo add custom-cogs https://github.com/FinnMeier/cogs
   ```
2. Install a specific cog:
   ```
   [p]cog install custom-cogs lurkerkick
   ```
3. Load the cog:
   ```
   [p]load lurkerkick
   ```
*(Replace `[p]` with your bot's prefix.)*
