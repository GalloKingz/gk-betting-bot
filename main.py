import os
import asyncio
from datetime import datetime, timezone
from aiohttp import web
import discord
from discord.ext import commands
import requests
import feedparser

# Mini server web integrato per Render (Keep-Alive)
async def handle(request):
    return web.Response(text="GK Betting Bot Online!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

# Inizializzazione Bot Discord
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

ODDS_API_KEY = os.environ.get("ODDS_API_KEY")

# Mappa delle Leghe e delle Coppe Europee
LEAGUES = {
    "Champions League": "soccer_uefa_champions_league",
    "Europa League": "soccer_uefa_europa_league",
    "Conference League": "soccer_uefa_europa_conference_league",
    "Serie A": "soccer_italy_serie_a",
    "Premier League": "soccer_epl",
    "LaLiga": "soccer_spain_la_liga",
    "Bundesliga": "soccer_germany_bundesliga",
    "Ligue 1": "soccer_france_ligue_one",
    "Eredivisie": "soccer_netherlands_eredivisie",
    "Süper Lig": "soccer_turkey_super_league",
    "Saudi Pro League": "soccer_saudi_pro_league"
}

@bot.event
async def on_ready():
    print(f"Bot connesso con successo come {bot.user}")

# Comando per le Ultime Notizie Calcio
@bot.command(name="news")
async def get_news(ctx):
    feed_url = "https://www.gazzetta.it/rss/Calcio.xml"
    feed = feedparser.parse(feed_url)
    
    embed = discord.Embed(title="⚽ Ultime Notizie Calcio", color=discord.Color.blue())
    for entry in feed.entries[:5]:
        embed.add_field(name=entry.title, value=f"[Leggi la notizia]({entry.link})", inline=False)
    
    await ctx.send(embed=embed)

# Comando per visualizzare le partite di OGGI (Coppe + Leghe)
@bot.command(name="partite")
async def get_matches(ctx):
    if not ODDS_API_KEY:
        await ctx.send("Chiave API Odds non configurata.")
        return

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    embed = discord.Embed(title=f"📅 Partite di Oggi ({today_str}) - Coppe & Leghe", color=discord.Color.green())
    found_any = False

    for league_name, league_key in LEAGUES.items():
        url = f"https://api.the-odds-api.com/v4/sports/{league_key}/odds/?apiKey={ODDS_API_KEY}&regions=eu&markets=h2h&bookmakers=bet365"
        try:
            response = requests.get(url, timeout=5).json()
            if isinstance(response, list) and len(response) > 0:
                todays_matches = []
                for m in response:
                    if m.get("commence_time", "").startswith(today_str):
                        todays_matches.append(f"• {m['home_team']} vs {m['away_team']}")
                
                if todays_matches:
                    embed.add_field(name=league_name, value="\n".join(todays_matches), inline=False)
                    found_any = True
        except Exception:
            continue

    if not found_any:
        embed.description = "Nessuna partita in programma esattamente per oggi tra coppe e campionati monitorati."

    await ctx.send(embed=embed)

# Comando per i Pronostici di OGGI (Cassaforte + Colpaccio 5€)
@bot.command(name="bet")
async def get_bet(ctx):
    if not ODDS_API_KEY:
        await ctx.send("Chiave API Odds non configurata.")
        return

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cassaforte = []
    colpaccio = []
    vincita_colpaccio = 5.0
    matches_collected = 0

    for league_name, league_key in LEAGUES.items():
        if matches_collected >= 5:
            break
        url = f"https://api.the-odds-api.com/v4/sports/{league_key}/odds/?apiKey={ODDS_API_KEY}&regions=eu&markets=h2h&bookmakers=bet365"
        try:
            response = requests.get(url, timeout=5).json()
            if isinstance(response, list) and len(response) > 0:
                for match in response:
                    if matches_collected >= 5:
                        break
                    if not match.get("commence_time", "").startswith(today_str):
                        continue

                    home = match["home_team"]
                    away = match["away_team"]
                    bookmakers = match.get("bookmakers", [])
                    
                    if bookmakers:
                        outcomes = bookmakers[0]["markets"][0]["outcomes"]
                        odd_home = next((o["price"] for o in outcomes if o["name"] == home), 1.50)
                        odd_away = next((o["price"] for o in outcomes if o["name"] == away), 2.50)

                        # Cassaforte
                        if odd_home < 1.85:
                            cassaforte.append(f"• **{home} vs {away}** ({league_name}) ➔ **1** @{odd_home}")
                        else:
                            cassaforte.append(f"• **{home} vs {away}** ({league_name}) ➔ **1X** @1.25")

                        # Colpaccio
                        colpaccio.append(f"• **{home} vs {away}** ({league_name}) ➔ **Over 2.5 + 1** @{odd_away}")
                        vincita_colpaccio *= odd_away
                        matches_collected += 1
        except Exception:
            continue

    embed = discord.Embed(title=f"🔥 PRONOSTICI DEL GIORNO ({today_str})", color=discord.Color.gold())
    
    embed.add_field(
        name="🛡️ LA CASSAFORTE (Alta Probabilità)", 
        value="\n".join(cassaforte) if cassaforte else "Nessun match ideale oggi.", 
        inline=False
    )
    
    embed.add_field(
        name="🚀 IL COLPACCIO (Schedina 5€)", 
        value="\n".join(colpaccio) + f"\n\n💰 **Vincita Potenziale con 5€:** `{round(vincita_colpaccio, 2)}€`" if colpaccio else "Nessun match disponibile per oggi.", 
        inline=False
    )

    await ctx.send(embed=embed)

async def main():
    await start_web_server()
    token = os.environ.get("DISCORD_TOKEN")
    await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())
