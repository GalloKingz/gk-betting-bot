import os
import asyncio
from aiohttp import web
import discord
from discord.ext import commands
import requests
import feedparser

# Mini server web integrato per Render
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

# Mappa delle 8 Leghe Principali
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

# Comando per le News
@bot.command(name="news")
async def get_news(ctx):
    feed_url = "https://www.gazzetta.it/rss/Calcio.xml"
    feed = feedparser.parse(feed_url)
    
    embed = discord.Embed(title="⚽ Ultime Notizie Calcio", color=discord.Color.blue())
    for entry in feed.entries[:5]:
        embed.add_field(name=entry.title, value=f"[Leggi la notizia]({entry.link})", inline=False)
    
    await ctx.send(embed=embed)

# Comando per i Pronostici del Giorno (Cassaforte + Colpaccio 5€)
@bot.command(name="bet")
async def get_bet(ctx):
    if not ODDS_API_KEY:
        await ctx.send("Chiave API Odds non configurata.")
        return

    url = f"https://api.the-odds-api.com/v4/sports/soccer_italy_serie_a/odds/?apiKey={ODDS_API_KEY}&regions=eu&markets=h2h&bookmakers=bet365"
    response = requests.get(url).json()

    if not response or isinstance(response, dict):
        await ctx.send("Nessuna partita disponibile al momento o limite API raggiunto.")
        return

    cassaforte = []
    colpaccio = []
    vincita_colpaccio = 5.0

    for match in response[:5]:
        home = match["home_team"]
        away = match["away_team"]
        bookmakers = match.get("bookmakers", [])
        
        if bookmakers:
            outcomes = bookmakers[0]["markets"][0]["outcomes"]
            odd_home = next((o["price"] for o in outcomes if o["name"] == home), 1.50)
            odd_away = next((o["price"] for o in outcomes if o["name"] == away), 2.50)

            # Cassaforte: Quota più bassa / 1X2 sicura
            if odd_home < 1.80:
                cassaforte.append(f"• **{home} vs {away}** ➔ **1** @{odd_home}")
            else:
                cassaforte.append(f"• **{home} vs {away}** ➔ **1X** @1.25")

            # Colpaccio: Quota più alta
            colpaccio.append(f"• **{home} vs {away}** ➔ **Over 2.5 + 1** @{odd_away}")
            vincita_colpaccio *= odd_away

    embed = discord.Embed(title="🔥 PRONOSTICI DEL GIORNO - GK BETTING", color=discord.Color.gold())
    
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
