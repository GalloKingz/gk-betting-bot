import os
import asyncio
import random
import string
from datetime import datetime, timezone
from aiohttp import web
import discord
from discord.ext import commands, tasks
import requests

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
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

ODDS_API_KEY = os.environ.get("ODDS_API_KEY")
TARGET_CHANNEL_NAME = "partite-e-pronostici" 
REPORT_CHANNEL_NAME = "vincite-e-perdite"

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

# Dizionario in memoria per tracciare le casse e i partecipanti
active_pyramids = {}

@bot.event
async def on_ready():
    print(f"Bot connesso con successo come {bot.user}")
    bot.add_view(PyramidView())
    if not daily_bet_task.is_running():
        daily_bet_task.start()

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


# --- MODALE DI CONFIGURAZIONE ---

class PyramidModal(discord.ui.Modal, title="Configura Nuova Sessione Bet"):
    initial_cash = discord.ui.TextInput(
        label="Cassa Iniziale (Minimo 5€)",
        placeholder="Es. 20 o 50",
        min_length=1,
        max_length=5,
        required=True
    )
    
    invited_users = discord.ui.TextInput(
        label="Tagga amici (Max 3, es. @Nome)",
        placeholder="Lascia vuoto se giochi da solo",
        required=False,
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        existing_rooms = [ch for ch in guild.channels if ch.name.startswith("bet-")]
        if len(existing_rooms) >= 10:
            await interaction.followup.send("❌ Raggiunto il limite massimo di 10 stanze Bet attive!", ephemeral=True)
            return

        try:
            cassa_valore = float(self.initial_cash.value.replace(",", "."))
            if cassa_valore < 5.0:
                await interaction.followup.send("❌ La cassa iniziale deve essere di almeno **5€**!", ephemeral=True)
                return
        except ValueError:
            await interaction.followup.send("❌ Inserisci un importo numerico valido per la cassa!", ephemeral=True)
            return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }

        text_input = self.invited_users.value
        invited_list = []
        
        for member in guild.members:
            if (str(member.id) in text_input or member.name.lower() in text_input.lower()) and member.id != interaction.user.id:
                if member not in invited_list:
                    invited_list.append(member)

        if len(invited_list) > 3:
            await interaction.followup.send("❌ Puoi invitare al **massimo 3 amici** (totale 4 giocatori). Correggi e riprova!", ephemeral=True)
            return

        for user in invited_list:
            overwrites[user] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        category = interaction.channel.category
        random_code = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
        channel_full_name = f"bet-{random_code}"

        channel = await guild.create_text_channel(name=channel_full_name, category=category, overwrites=overwrites)
        
        active_pyramids[channel.id] = {
            "cassa_iniziale": cassa_valore,
            "cassa": cassa_valore, 
            "giocata_attiva": 0.0,
            "host": interaction.user,
            "invitati": invited_list
        }

        partecipanti_str = f"• {interaction.user.mention} (Host)"
        for user in invited_list:
            partecipanti_str += f"\n• {user.mention}"

        embed = discord.Embed(
            title=f"💎 Sessione Bet [{channel_full_name.upper()}]",
            description=f"Stanza privata e protetta!\n\n👥 **Partecipanti ({len(invited_list) + 1}/4):**\n{partecipanti_str}",
            color=discord.Color.blue()
        )
        embed.add_field(name="💰 Cassa Iniziale", value=f"`{round(cassa_valore, 2)}€`", inline=False)
        
        # AGGIUNTA GUIDA COMANDI COMPATTA NELL'EMBED
        comandi_guida = (
            "📌 **Come gestire la sessione:**\n"
            "• `!gioca [importo]` ➔ Scala i soldi e registra la giocata *(puoi allegare lo screenshot)*\n"
            "• `!vinto [totale]` ➔ Acredita la vincita totale in cassa\n"
            "• `!perso` ➔ Registra la schedina persa\n"
            "• `!soldi` ➔ Controlla il saldo attuale della cassa\n"
            "• `!out` ➔ Preleva il bottone finale, chiudi e invia il report!"
        )
        embed.add_field(name="📖 Guida Rapida Comandi", value=comandi_guida, inline=False)
        
        mentions_text = f"{interaction.user.mention} " + " ".join([u.mention for u in invited_list])
        await channel.send(content=mentions_text, embed=embed)

        msg = await interaction.followup.send(f"✅ Stanza privata creata con successo: {channel.mention}", ephemeral=True)
        await asyncio.sleep(4)
        try:
            await msg.delete()
        except Exception:
            pass


class PyramidView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="➕ Nuova Schedina Piramidale", style=discord.ButtonStyle.green, custom_id="btn_nuova_piramide")
    async def open_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PyramidModal())


@bot.command(name="setup_piramide")
@commands.has_permissions(administrator=True)
async def setup_piramide(ctx):
    embed = discord.Embed(
        title="💎 GESTIONE PIRAMIDE BETS",
        description="Clicca sul bottone sottostante per impostare il budget iniziale e invitare fino a 3 compagni.",
        color=discord.Color.gold()
    )
    view = PyramidView()
    await ctx.send(embed=embed, view=view)
    await ctx.message.delete()


# --- COMANDI DELLA STANZA ---

@bot.command(name="gioca")
async def cmd_gioca(ctx, importo: float = None):
    if ctx.channel.id not in active_pyramids:
        return
    
    if importo is None:
        await ctx.send("❌ Specifica l'importo giocato. Esempio: `!gioca 10` (puoi allegare lo screenshot della schedina nello stesso messaggio!)")
        return

    data = active_pyramids[ctx.channel.id]
    if importo > data["cassa"]:
        await ctx.send(f"❌ Non hai abbastanza fondi in cassa! Disponibili: `{data['cassa']}€`")
        return

    data["cassa"] -= importo
    data["giocata_attiva"] = importo

    has_attachment = len(ctx.message.attachments) > 0
    msg_extra = " 📸 *(Screenshot allegato registrato!)*" if has_attachment else ""

    await ctx.send(f"✅ **Schedina registrata!** Puntati `{importo}€`. Fondi rimanenti in cassa: `{round(data['cassa'], 2)}€`{msg_extra}")


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
        await ctx.send("❌ Cassa a zero! Digita `!out` per chiudere la sessione e inviare il report.")
    else:
        await ctx.send("💪 Siete ancora in plus/gioco! La stanza rimane aperta per il prossimo livello.")


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
    cassa_iniziale = data["cassa_iniziale"]
    
    membri_stanza = [data["host"]] + data["invitati"]
    num_giocatori = len(membri_stanza)
    tag_membri = " ".join([m.mention for m in membri_stanza])

    guild = ctx.guild
    report_channel = discord.utils.get(guild.text_channels, name=REPORT_CHANNEL_NAME)
    if not report_channel:
        try:
            report_channel = await guild.create_text_channel(name=REPORT_CHANNEL_NAME)
        except Exception:
            report_channel = None

    if saldo_finale >= cassa_iniziale:
        profitto = saldo_finale - cassa_iniziale
        quota_cadauno = saldo_finale / num_giocatori
        embed_report = discord.Embed(
            title="🏆 SESSIONE CONCLUSA - IN PLUS!",
            description=(
                f"Complimenti al team! Obiettivo raggiunto con successo. 🚀\n\n"
                f"👥 **Giocatori ({num_giocatori}):** {tag_membri}\n"
                f"💰 **Cassa Iniziale:** `{round(cassa_iniziale, 2)}€`\n"
                f"💎 **Bottino Totale Prelevato:** `{round(saldo_finale, 2)}€`\n"
                f"📈 **Profitto Netto:** `+{round(profitto, 2)}€`\n\n"
                f"💵 **Spetta a ciascuno:** `~{round(quota_cadauno, 2)}€` a testa"
            ),
            color=discord.Color.green()
        )
    else:
        perdita = cassa_iniziale - saldo_finale
        embed_report = discord.Embed(
            title="💀 SESSIONE CONCLUSA - CASSA PERSA",
            description=(
                f"Peccato! La piramide è crollata, ma ci si rifà la prossima volta. 💪\n\n"
                f"👥 **Giocatori ({num_giocatori}):** {tag_membri}\n"
                f"💰 **Cassa Iniziale:** `{round(cassa_iniziale, 2)}€`\n"
                f"📉 **Cassa Persa:** `{round(perdita, 2)}€` (Saldo finale: `{round(saldo_finale, 2)}€`)"
            ),
            color=discord.Color.red()
        )

    if report_channel:
        await report_channel.send(content=tag_membri, embed=embed_report)

    await ctx.send(f"🔒 **Sessione chiusa.** Report inviato in {report_channel.mention if report_channel else 'chat pubblica'}. Eliminazione stanza tra 5 secondi...")
    
    del active_pyramids[ctx.channel.id]
    await asyncio.sleep(5)
    await ctx.channel.delete()


async def main():
    await start_web_server()
    token = os.environ.get("DISCORD_TOKEN")
    await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())
