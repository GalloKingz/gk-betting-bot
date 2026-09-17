import os
import asyncio
from datetime import datetime, timezone
from aiohttp import web
import discord
from discord.ext import commands, tasks
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
TARGET_CHANNEL_NAME = "partite-e-pronostici" 

# Mappa delle Leghe
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

# Dizionario in memoria per tracciare le casse delle stanze temporali {channel_id: {"cassa": float, "giocata_attiva": float}}
active_pyramids = {}

@bot.event
async def on_ready():
    print(f"Bot connesso con successo come {bot.user}")
    if not daily_bet_task.is_running():
        daily_bet_task.start()

# Task automatico giornaliero per #partite-e-pronostici
@tasks.loop(hours=24)
async def daily_bet_task():
    await bot.wait_until_ready()
    channel = discord.utils.get(bot.get_all_channels(), name=TARGET_CHANNEL_NAME)
    if not channel:
        return

    try:
        await channel.purge(limit=100)
    except Exception:
        pass

    if not ODDS_API_KEY:
        return

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cassaforte = []
    colpaccio = []
    vincita_cassaforte = 5.0
    vincita_colpaccio = 5.0
    matches_collected = 0
    found_any_matches = False

    embed_matches = discord.Embed(title=f"📅 Partite di Oggi ({today_str}) - Coppe & Leghe", color=discord.Color.green())

    for league_name, league_key in LEAGUES.items():
        url = f"https://api.the-odds-api.com/v4/sports/{league_key}/odds/?apiKey={ODDS_API_KEY}&regions=eu&markets=h2h&bookmakers=bet365"
        try:
            response = requests.get(url, timeout=5).json()
            if isinstance(response, list) and len(response) > 0:
                todays_matches = []
                for match in response:
                    if not match.get("commence_time", "").startswith(today_str):
                        continue
                    
                    home = match["home_team"]
                    away = match["away_team"]
                    todays_matches.append(f"• {home} vs {away}")
                    found_any_matches = True

                    if matches_collected < 4:
                        odd_home = 1.28
                        odd_away = 2.10
                        bookmakers = match.get("bookmakers", [])
                        if bookmakers:
                            try:
                                outcomes = bookmakers[0]["markets"][0]["outcomes"]
                                for o in outcomes:
                                    if o["name"] == home:
                                        odd_home = o["price"]
                                    elif o["name"] == away:
                                        odd_away = o["price"]
                            except Exception:
                                pass

                        cassaforte.append(f"• **{home} vs {away}** ({league_name}) ➔ **1X** @1.28")
                        vincita_cassaforte *= 1.28

                        colpaccio.append(f"• **{home} vs {away}** ({league_name}) ➔ **1 + Over 1.5** @{odd_away}")
                        vincita_colpaccio *= odd_away
                        matches_collected += 1

                if todays_matches:
                    embed_matches.add_field(name=league_name, value="\n".join(todays_matches), inline=False)
        except Exception:
            continue

    if not found_any_matches:
        embed_matches.description = "Nessuna partita in programma oggi."

    await channel.send(embed=embed_matches)

    embed_bet = discord.Embed(title=f"🔥 PRONOSTICI DEL GIORNO ({today_str})", color=discord.Color.gold())
    valore_cassa = "\n".join(cassaforte) + f"\n\n💰 **Vincita Potenziale con 5€:** `{round(vincita_cassaforte, 2)}€`" if cassaforte else "Nessun match."
    embed_bet.add_field(name="🛡️ LA CASSAFORTE (Alta Probabilità)", value=valore_cassa, inline=False)
    
    valore_colpo = "\n".join(colpaccio) + f"\n\n💰 **Vincita Potenziale con 5€:** `{round(vincita_colpaccio, 2)}€`" if colpaccio else "Nessun match."
    embed_bet.add_field(name="🚀 IL COLPACCIO (Schedina 5€)", value=valore_colpo, inline=False)

    await channel.send(embed=embed_bet)


# --- SISTEMA GESTIONE PIRAMIDE (STANZE TEMPORANEE) ---

class PyramidView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="➕ Nuova Schedina Piramidale", style=discord.ButtonStyle.green, custom_id="btn_nuova_piramide")
    async def create_pyramid_room(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        
        # Controllo limite massimo di 10 stanze temporali attive
        existing_rooms = [ch for ch in guild.channels if ch.name.startswith("piramide-")]
        if len(existing_rooms) >= 10:
            await interaction.response.send_message("❌ Raggiunto il limite massimo di 10 stanze piramidali attive!", ephemeral=True)
            return

        # Trova la categoria corrente o la crea
        category = interaction.channel.category
        
        # Configurazione permessi (Visibile solo all'utente che clicca e al bot)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }

        # Crea il canale temporaneo
        room_name = f"piramide-{interaction.user.name}"
        channel = await guild.create_text_channel(name=room_name, category=category, overwrites=overwrites)
        
        # Inizializza la cassa di questa stanza (es. 20€ iniziali)
        active_pyramids[channel.id] = {"cassa": 20.0, "giocata_attiva": 0.0}

        # Messaggio guida all'interno della stanza
        embed = discord.Embed(
            title="💎 Sessione Piramidale Attivata",
            description=(
                "Benvenuti nella vostra stanza privata per la gestione della piramide.\n\n"
                "**Comandi disponibili:**\n"
                "• `!gioca [importo]` ➔ Scala l'importo dalla cassa e registra la giocata.\n"
                "• `!vinto [importo_vincita]` ➔ Registra la vincita e aggiorna la cassa.\n"
                "• `!perso` ➔ Registra la perdita (se sei in plus la stanza resta aperta).\n"
                "• `!soldi` ➔ Mostra lo stato attuale della cassa nella stanza.\n"
                "• `!out` ➔ Preleva i profitti e chiude definitivamente la stanza."
            ),
            color=discord.Color.blue()
        )
        embed.add_field(name="Cassa Iniziale", value="20.00€", inline=False)
        await channel.send(content=f"{interaction.user.mention}", embed=embed)

        await interaction.response.send_message(f"✅ Stanza creata con successo: {channel.mention}", ephemeral=True)


# Comando per generare il pannello con il bottone nella categoria
@bot.command(name="setup_piramide")
@commands.has_permissions(administrator=True)
async def setup_piramide(ctx):
    embed = discord.Embed(
        title="💎 GESTIONE PIRAMIDE BETS",
        description="Clicca sul bottone sottostante per aprire una stanza temporale privata e avviare un nuovo ciclo di scommesse piramidali.",
        color=discord.Color.gold()
    )
    view = PyramidView()
    await ctx.send(embed=embed, view=view)
    await ctx.message.delete()


# --- COMANDI DELLA STANZA PIRAMIDALE ---

@bot.command(name="gioca")
async def cmd_gioca(ctx, importo: float = None):
    if ctx.channel.id not in active_pyramids:
        return
    
    if importo is None:
        await ctx.send("❌ Specifica l'importo giocato. Esempio: `!gioca 10`")
        return

    data = active_pyramids[ctx.channel.id]
    if importo > data["cassa"]:
        await ctx.send(f"❌ Non hai abbastanza fondi in cassa! Disponibili: `{data['cassa']}€`")
        return

    data["cassa"] -= importo
    data["giocata_attiva"] = importo
    await ctx.send(f"✅ **Schedina registrata!** Puntati `{importo}€`. Fondi rimanenti in cassa: `{round(data['cassa'], 2)}€`")


@bot.command(name="vinto")
async def cmd_vinto(ctx, vincita_totale: float = None):
    if ctx.channel.id not in active_pyramids:
        return
        
    if vincita_totale is None:
        await ctx.send("❌ Specifica l'importo totale vinto. Esempio: `!vinto 35.50`")
        return

    data = active_pyramids[ctx.channel.id]
    data["cassa"] += vincita_totale
    await ctx.send(f"🎉 **VITTORIA REGISTRATA!** Incassati `{vincita_totale}€`. **Cassa aggiornata totale:** `{round(data['cassa'], 2)}€`")


@bot.command(name="perso")
async def cmd_perso(ctx):
    if ctx.channel.id not in active_pyramids:
        return

    data = active_pyramids[ctx.channel.id]
    data["giocata_attiva"] = 0.0
    
    await ctx.send(f"⚠️ Schedina persa registrata. Cassa attuale rimasta: `{round(data['cassa'], 2)}€`")
    if data["cassa"] <= 0:
        await ctx.send("❌ Cassa a zero! Digita `!out` per chiudere la sessione.")
    else:
        await ctx.send("💪 Sei ancora in plus/gioco! La stanza rimane aperta per il prossimo livello della piramide.")


@bot.command(name="soldi")
async def cmd_soldi(ctx):
    if ctx.channel.id not in active_pyramids:
        return
    data = active_pyramids[ctx.channel.id]
    await ctx.send(f"📊 **Stato Cassa Attuale:** `{round(data['cassa'], 2)}€`")


@bot.command(name="out")
async def cmd_out(ctx):
    if ctx.channel.id not in active_pyramids:
        return
    
    data = active_pyramids[ctx.channel.id]
    saldo_finale = data["cassa"]
    
    await ctx.send(f"🔒 **Sessione chiusa.** Prelevati/Chiusi con un totale di `{round(saldo_finale, 2)}€`. La stanza verrà eliminata tra 5 secondi...")
    
    # Rimuove dai registri e cancella il canale dopo 5 secondi
    del active_pyramids[ctx.channel.id]
    await asyncio.sleep(5)
    await ctx.channel.delete()


async def main():
    await start_web_server()
    token = os.environ.get("DISCORD_TOKEN")
    await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())
