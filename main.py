import os
import asyncio
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

# Mappa delle 8 Leghe Principali richieste
LEAGUES = {
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

# Comando per visualizzare le partite delle 8 leghe
@bot.command(name="partite")
async def get_matches(ctx):
    if not ODDS_API_KEY:
        await ctx.send("Chiave API Odds non configurata.")
        return

    embed = discord.Embed(title="📅 Partite del Giorno - Le 8 Leghe", color=discord.Color.green())
    found_any = False

    for league_name, league_key in LEAGUES.items():
        url = f"https://api.the-odds-api.com/v4/sports/{league_key}/odds/?apiKey={ODDS_API_KEY}&regions=eu&markets=h2h&bookmakers=bet365"
        try:
            response = requests.get(url, timeout=5).json()
            if isinstance(response, list) and len(response) > 0:
                matches_text = []
                for m in response[:3]: # Prende fino a 3 match per lega per non intasare la chat
                    matches_text.append(f"• {m['home_team']} vs {m['away_team']}")
                embed.add_field(name=league_name, value="\n".join(matches_text), inline=False)
                found_any = True
        except Exception:
            continue

    if not found_any:
        embed.description = "Nessuna partita in programma trovata al momento per le 8 leghe."

    await ctx.send(embed=embed)

# Comando per i Pronostici (Cassaforte + Colpaccio 5€) su tutte le 8 leghe
@bot.command(name="bet")
async def get_bet(ctx):
    if not ODDS_API_KEY:
        await ctx.send("Chiave API Odds non configurata.")
        return

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
                for match in response[:2]:
                    if matches_collected >= 5:
                        break
                    home = match["home_team"]
                    away = match["away_team"]
                    bookmakers = match.get("bookmakers", [])
                    
                    if bookmakers:
                        outcomes = bookmakers[0]["markets"][0]["outcomes"]
                        odd_home = next((o["price"] for o in outcomes if o["name"] == home), 1.50)
                        odd_away = next((o["price"] for o in outcomes if o["name"] == away), 2.50)

                        # Aggiunge alla Cassaforte
                        if odd_home < 1.85:
                            cassaforte.append(f"• **{home} vs {away}** ({league_name}) ➔ **1** @{odd_home}")
                        else:
                            cassaforte.append(f"• **{home} vs {away}** ({league_name}) ➔ **1X** @1.25")

                        # Aggiunge al Colpaccio
                        colpaccio.append(f"• **{home} vs {away}** ({league_name}) ➔ **Over 2.5 + 1** @{odd_away}")
                        vincita_colpaccio *= odd_away
                        matches_collected += 1
        except Exception:
            continue

    embed = discord.Embed(title="🔥 PRONOSTICI DEL GIORNO - 8 LEGHE TOP", color=discord.Color.gold())
    
    embed.add_field(
        name="🛡️ LA CASSAFORTE (Alta Probabilità)", 
        value="\n".join(cassaforte) if cassaforte else "Nessun match ideale oggi.", 
        inline=False
    )
    
    embed.add_field(
        name="🚀 IL COLPACCIO (Schedina 5€)", 
        value="\n".join(colpaccio) + f"\n\n💰 **Vincita Potenziale con 5€:** `{round(vincita_colpaccio, 2)}€`" if colpaccio else "Nessun match disponibile.", 
        inline=False
    )

    await ctx.send(embed=embed)

async def main():
    await start_web_server()
    token = os.environ.get("DISCORD_TOKEN")
    await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())
