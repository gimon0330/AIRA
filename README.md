# AIRA

AIRA is a Discord bot for checking League of Legends records with Riot API.

## Features

- Modern `discord.py` slash command bot
- Extension/Cog based feature loading
- `/전적` command for Riot ID based League of Legends record lookup
- Riot Account-V1, Summoner-V4, League-V4, and Match-V5 integration
- Secret values loaded from environment variables

## Command

```text
/전적 riot_id: Hide on bush#KR1
```

The command shows:

- Summoner level
- Solo queue rank
- Flex queue rank
- Recent 5 match summary
- Win/loss, champion, KDA, CS, and vision score

## Setup

### 1. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

On Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e .
```

### 2. Configure environment variables

Copy the example file:

```bash
cp .env.example .env
```

Then edit `.env`:

```text
DISCORD_TOKEN=YOUR_DISCORD_BOT_TOKEN
RIOT_API_KEY=YOUR_RIOT_API_KEY
```

For faster slash command updates during development, optionally add:

```text
DISCORD_GUILD_ID=YOUR_TEST_SERVER_ID
```

### 3. Run

```bash
python -m aira
```

## Notes

- Riot ID must include a tag, like `Hide on bush#KR1`.
- Riot API keys must not be committed to the repository.
- Global slash command sync can take time. Use `DISCORD_GUILD_ID` while developing.

## Structure

```text
.
├── aira/
│   ├── __main__.py
│   ├── bot.py
│   ├── config.py
│   ├── riot.py
│   └── exts/
│       └── league.py
├── .env.example
├── .gitignore
├── pyproject.toml
└── README.md
```
