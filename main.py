import os
import asyncio
import random
import string
from datetime import datetime, time, timezone
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

active_pyramids = {}

@bot.event
async def on_ready():
    print(f"Bot connesso con successo come {bot.user}")
    bot.add_view(PersistentPyramidView())
    await restore_active_pyramids()
    await fetch_and_post_matches()
    
    if not daily_midnight_task.is_running():
        daily_midnight_task.start()

# --- FUNZIONE PER RIPRISTINARE LE LOBBY DOPO UN RIAVVIO ---
async def restore_active_pyramids():
    for guild in bot.guilds:
        for channel in guild.text_channels:
            if channel.name.startswith("bet-"):
                try:
                    cassa_iniziale = 20.0
                    cassa_corrente = 20.0
                    host = guild.owner
                    invitati = []
                    
                    async for message in channel.history(limit=50, oldest_first=True):
                        if message.embeds:
                            embed = message.embeds[0]
                            if embed.title and "Sessione Bet" in embed.title:
                                if message.mentions:
                                    host = message.mentions[0]
                                    invitati = message.mentions[1:]
                                for field in embed.fields:
                                    if field.name and "Cassa Iniziale" in field.name:
                                        try:
                                            val_clean = field.value.replace("€", "").replace("`", "").strip()
                                            cassa_iniziale = float(val_clean)
                                            cassa_corrente = cassa_iniziale
                                        except:
                                            pass
                        
                        if message.content.startswith("!"):
                            parts = message.content.split()
                            cmd = parts[0].lower()
                            if cmd == "!gioca" and len(parts) > 1:
                                try:
                                    imp = float(parts[1].replace(",", "."))
                                    cassa_corrente -= imp
                                except:
                                    pass
                            elif cmd == "!vinto" and len(parts) > 1:
                                try:
                                    inc = float(parts[1].replace(",", "."))
                                    cassa_corrente += inc
                                except:
                                    pass

                    active_pyramids[channel.id] = {
                        "cassa_iniziale": cassa_iniziale,
                        "cassa": cassa_corrente,
                        "giocata_attiva": 0.0,
                        "host": host,
                        "invitati": invitati,
                        "extra_count": 0
                    }
                except Exception as e:
                    print(f"Errore nel ripristino della lobby {channel.name}: {e}")

# --- FUNZIONE CONDIVISA PER RECUPERARE LE PARTITE E QUOTE REALI VARIATE ---
async def fetch_and_post_matches():
    channel = discord.utils.get(bot.get_all_channels(), name=TARGET_CHANNEL_NAME)
    if not channel:
        return

    try:
        await channel.purge(limit=100)
    except Exception:
        pass

    if not ODDS_API_KEY:
        await channel.send("⚠️ Chiave `ODDS_API_KEY` non configurata nelle variabili d'ambiente di Render!")
        return

    today_str = datetime.now().strftime("%Y-%m-%d")
    cassaforte = []
    colpaccio = []
    vincita_cassaforte = 5.0
    vincita_colpaccio = 5.0
    matches_collected = 0
    found_any_matches = False

    embed_matches = discord.Embed(title=f"📅 Partite di Oggi ({today_str}) - Coppe & Leghe", color=discord.Color.green())

    for league_name, league_key in LEAGUES.items():
        url = f"https://api.the-odds-api.com/v4/sports/{league_key}/odds/?apiKey={ODDS_API_KEY}&regions=eu&markets=h2h"
        try:
            response = requests.get(url, timeout=5).json()
            if isinstance(response, list) and len(response) > 0:
                todays_matches = []
                for match in response:
                    commence_time = match.get("commence_time", "")
                    if not commence_time.startswith(today_str):
                        continue
                    
                    home = match["home_team"]
                    away = match["away_team"]
                    todays_matches.append(f"• {home} vs {away}")
                    found_any_matches = True

                    # Estrazione quote reali 1X2 dall'API per ogni match
                    if matches_collected < 4:
                        odd_home = 2.00
                        odd_draw = 3.20
                        odd_away = 3.50
                        try:
                            bookmakers = match.get("bookmakers", [])
                            if bookmakers:
                                outcomes = bookmakers[0]["markets"][0]["outcomes"]
                                for o in outcomes:
                                    name = o.get("name")
                                    price = float(o.get("price", 0))
                                    if name == home:
                                        odd_home = price
                                    elif name == away:
                                        odd_away = price
                                    elif name.lower() in ["draw", "pareggio", "x"]:
                                        odd_draw = price
                        except Exception:
                            pass

                        # CASSA: Scegliamo dinamicamente e in modo vario tra 1, 2, X o doppia chance reale
                        scelte_cassa = [
                            ("1 (Segno 1)", odd_home),
                            ("2 (Segno 2)", odd_away),
                            ("X (Pareggio)", odd_draw),
                            ("1X (Doppia Chance)", round(odd_home * 1.12, 2))
                        ]
                        # Ordiniamo o filtriamo per prendere esiti con quote equilibrate per la cassa (preferibilmente < 2.50)
                        scelte_cassa_ordinate = sorted(scelte_cassa, key=lambda x: x[1])
                        # Alterniamo in base all'indice della partita raccolta per non mettere sempre la stessa cosa
                        scelta_cassa = scelte_cassa_ordinate[matches_collected % len(scelte_cassa_ordinate)]
                        
                        mercato_cassa, quota_cassa = scelta_cassa
                        cassaforte.append(f"• **{home} vs {away}** ({league_name}) ➔ **{mercato_cassa}** @{quota_cassa}")
                        vincita_cassaforte *= quota_cassa

                        # COLPACCIO: Scegliamo esiti più alti o opposti per variare completamente la schedina
                        scelte_colpo = [
                            ("2 (Segno 2)", odd_away),
                            ("X (Pareggio)", odd_draw),
                            ("1 (Segno 1)", odd_home),
                            ("Gol (Entrambe a segno)", round(max(odd_home, odd_away) * 0.90, 2))
                        ]
                        # Prendiamo l'inverso o ruotiamo per garantire varietà
                        scelta_colpo = scelte_colpo[(matches_collected + 2) % len(scelte_colpo)]
                        
                        mercato_colpo, quota_colpo = scelta_colpo
                        colpaccio.append(f"• **{home} vs {away}** ({league_name}) ➔ **{mercato_colpo}** @{quota_colpo}")
                        vincita_colpaccio *= quota_colpo
                        
                        matches_collected += 1

                if todays_matches:
                    embed_matches.add_field(name=league_name, value="\n".join(todays_matches), inline=False)
        except Exception:
            continue

    if not found_any_matches:
        embed_matches.description = "Nessuna partita in programma oggi nei campionati monitorati."

    await channel.send(embed=embed_matches)

    embed_bet = discord.Embed(title=f"🔥 PRONOSTICI DEL GIORNO ({today_str})", color=discord.Color.gold())
    valore_cassa = "\n".join(cassaforte) + f"\n\n💰 **Vincita Potenziale con 5€:** `{round(vincita_cassaforte, 2)}€`" if cassaforte else "Nessun match disponibile per la cassa."
    embed_bet.add_field(name="🛡️ LA CASSAFORTE (Alta Probabilità)", value=valore_cassa, inline=False)
    
    valore_colpo = "\n".join(colpaccio) + f"\n\n💰 **Vincita Potenziale con 5€:** `{round(vincita_colpaccio, 2)}€`" if colpaccio else "Nessun match disponibile per il colpaccio."
    embed_bet.add_field(name="🚀 IL COLPACCIO (Schedina 5€)", value=valore_colpo, inline=False)

    await channel.send(embed=embed_bet)

@tasks.loop(time=time(hour=0, minute=0, tzinfo=timezone.utc))
async def daily_midnight_task():
    await fetch_and_post_matches()

@bot.command(name="aggiorna_partite")
@commands.has_permissions(administrator=True)
async def cmd_aggiorna_partite(ctx):
    await ctx.send("🔄 Aggiornamento manuale delle partite in corso...")
    await fetch_and_post_matches()
    try:
        await ctx.message.delete()
    except:
        pass

# --- RESTO DEL CODICE (Modale, View, Comandi stanza) ---
class PyramidModal(discord.ui.Modal, title="Configura Nuova Sessione Bet"):
    initial_cash = discord.ui.TextInput(label="Cassa Iniziale (Minimo 5€)", placeholder="Es. 20 o 50", min_length=1, max_length=5, required=True)
    invited_users = discord.ui.TextInput(label="Tagga amici o indica numero (es. @Nome o +3)", placeholder="Es. @Amico oppure +3", required=False, max_length=100)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
            guild = interaction.guild
            existing_rooms = [ch for ch in guild.channels if ch.name.startswith("bet-")]
            if len(existing_rooms) >= 10:
                err_msg = await interaction.followup.send("❌ Raggiunto il limite massimo di 10 stanze Bet attive!", ephemeral=True)
                await asyncio.sleep(4)
                try: await err_msg.delete()
                except: pass
                return

            try:
                cassa_valore = float(self.initial_cash.value.replace(",", "."))
                if cassa_valore < 5.0:
                    err_msg = await interaction.followup.send("❌ La cassa iniziale deve essere di almeno **5€**!", ephemeral=True)
                    await asyncio.sleep(4)
                    try: await err_msg.delete()
                    except: pass
                    return
            except ValueError:
                err_msg = await interaction.followup.send("❌ Inserisci un importo numerico valido per la cassa!", ephemeral=True)
                await asyncio.sleep(4)
                try: await err_msg.delete()
                except: pass
                return

            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
            }

            text_input = self.invited_users.value.strip() if self.invited_users.value else ""
            invited_list = []
            extra_count = 0

            if text_input.startswith("+") and text_input[1:].isdigit():
                extra_count = int(text_input[1:])
            else:
                for member in guild.members:
                    if (str(member.id) in text_input or member.name.lower() in text_input.lower()) and member.id != interaction.user.id:
                        if member not in invited_list:
                            invited_list.append(member)

            totale_extra = len(invited_list) + extra_count
            if totale_extra > 3:
                err_msg = await interaction.followup.send("❌ Puoi aggiungere al **massimo 3 compagni** in totale. Riprova!", ephemeral=True)
                await asyncio.sleep(4)
                try: await err_msg.delete()
                except: pass
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
                "invitati": invited_list,
                "extra_count": extra_count
            }

            partecipanti_str = f"• {interaction.user.mention} (Host)"
            for user in invited_list:
                partecipanti_str += f"\n• {user.mention}"
            if extra_count > 0:
                partecipanti_str += f"\n• `{extra_count} Amici esterni/fisici`"

            num_totale_giocatori = 1 + len(invited_list) + extra_count

            embed = discord.Embed(
                title=f"💎 Sessione Bet [{channel_full_name.upper()}]",
                description=f"Stanza privata e protetta!\n\n👥 **Partecipanti ({num_totale_giocatori}/4):**\n{partecipanti_str}",
                color=discord.Color.blue()
            )
            embed.add_field(name="💰 Cassa Iniziale", value=f"`{round(cassa_valore, 2)}€`", inline=False)
            comandi_guida = (
                "• `!gioca [importo]` ➔ Registra giocata *(puoi allegare screen)*\n"
                "• `!vinto [totale]` ➔ Accredita vincita\n"
                "• `!perso` ➔ Schedina persa\n"
                "• `!soldi` ➔ Saldo cassa\n"
                "• `!out` ➔ Chiudi e invia report"
            )
            embed.add_field(name="📖 Comandi Rapidi", value=comandi_guida, inline=False)
            
            mentions_text = f"{interaction.user.mention} " + " ".join([u.mention for u in invited_list])
            await channel.send(content=mentions_text, embed=embed)
            msg = await interaction.followup.send(f"✅ Stanza privata creata con successo: {channel.mention}", ephemeral=True)
            await asyncio.sleep(4)
            try: await msg.delete()
            except: pass
        except Exception as e:
            print(f"Errore nel modale: {e}")

class PersistentPyramidView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="➕ Nuova Schedina Piramidale", style=discord.ButtonStyle.green, custom_id="persistent_view:nuova_schedina_piramidale")
    async def open_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PyramidModal())

@bot.command(name="setup_piramide")
@commands.has_permissions(administrator=True)
async def setup_piramide(ctx):
    embed = discord.Embed(title="💎 GESTIONE PIRAMIDE BETS", description="Clicca sul bottone sottostante per impostare il budget iniziale e invitare fino a 3 compagni.", color=discord.Color.gold())
    view = PersistentPyramidView()
    await ctx.send(embed=embed, view=view)
    try: await ctx.message.delete()
    except: pass

@bot.command(name="gioca")
async def cmd_gioca(ctx, importo: float = None):
    if ctx.channel.id not in active_pyramids: return
    if importo is None:
        await ctx.send("❌ Specifica l'importo. Esempio: `!gioca 10`")
        return
    data = active_pyramids[ctx.channel.id]
    if importo > data["cassa"]:
        await ctx.send(f"❌ Fondi insufficienti! Disponibili: `{data['cassa']}€`")
        return
    data["cassa"] -= importo
    data["giocata_attiva"] = importo
    has_attachment = len(ctx.message.attachments) > 0
    msg_extra = " 📸 *(Screenshot registrato!)*" if has_attachment else ""
    await ctx.send(f"✅ **Schedina registrata!** Puntati `{importo}€`. Rimasti in cassa: `{round(data['cassa'], 2)}€`{msg_extra}")

@bot.command(name="vinto")
async def cmd_vinto(ctx, vincita_totale: float = None):
    if ctx.channel.id not in active_pyramids: return
    if vincita_totale is None:
        await ctx.send("❌ Specifica l'importo vinto. Esempio: `!vinto 35.50`")
        return
    data = active_pyramids[ctx.channel.id]
    data["cassa"] += vincita_totale
    await ctx.send(f"🎉 **VITTORIA!** Incassati `{vincita_totale}€`. **Cassa totale:** `{round(data['cassa'], 2)}€`")

@bot.command(name="perso")
async def cmd_perso(ctx):
    if ctx.channel.id not in active_pyramids: return
    data = active_pyramids[ctx.channel.id]
    data["giocata_attiva"] = 0.0
    await ctx.send(f"⚠️ Schedina persa. Cassa attuale: `{round(data['cassa'], 2)}€`")
    if data["cassa"] <= 0:
        await ctx.send("❌ Cassa a zero! Digita `!out` per chiudere la sessione.")
    else:
        await ctx.send("💪 Siete ancora in gioco!")

@bot.command(name="soldi")
async def cmd_soldi(ctx):
    if ctx.channel.id not in active_pyramids: return
    data = active_pyramids[ctx.channel.id]
    await ctx.send(f"📊 **Stato Cassa:** `{round(data['cassa'], 2)}€`")

@bot.command(name="out")
async def cmd_out(ctx):
    if ctx.channel.id not in active_pyramids: return
    data = active_pyramids[ctx.channel.id]
    saldo_finale = data["cassa"]
    cassa_iniziale = data["cassa_iniziale"]
    
    discord_members = [data["host"]] + data["invitati"]
    extra_count = data["extra_count"]
    num_giocatori = len(discord_members) + extra_count
    tag_membri = " ".join([m.mention for m in discord_members])
    testo_partecipanti = tag_membri + (f" + {extra_count} ospiti fisici" if extra_count > 0 else "")

    guild = ctx.guild
    report_channel = discord.utils.get(guild.text_channels, name=REPORT_CHANNEL_NAME)
    if not report_channel:
        try: report_channel = await guild.create_text_channel(name=REPORT_CHANNEL_NAME)
        except: report_channel = None

    if saldo_finale >= cassa_iniziale:
        profitto = saldo_finale - cassa_iniziale
        quota_cadauno = saldo_finale / num_giocatori
        embed_report = discord.Embed(
            title="🏆 SESSIONE CONCLUSA - IN PLUS!",
            description=(
                f"Complimenti al team! 🚀\n\n"
                f"👥 **Partecipanti ({num_giocatori}):** {testo_partecipanti}\n"
                f"💰 **Cassa Iniziale:** `{round(cassa_iniziale, 2)}€`\n"
                f"💎 **Bottino Totale:** `{round(saldo_finale, 2)}€`\n"
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
                f"Peccato! La piramide è crollata. 💪\n\n"
                f"👥 **Partecipanti ({num_giocatori}):** {testo_partecipanti}\n"
                f"💰 **Cassa Iniziale:** `{round(cassa_iniziale, 2)}€`\n"
                f"📉 **Cassa Persa:** `{round(perdita, 2)}€` (Restati: `{round(saldo_finale, 2)}€`)"
            ),
            color=discord.Color.red()
        )

    if report_channel:
        await report_channel.send(content=tag_membri, embed=embed_report)

    await ctx.send("🔒 **Sessione chiusa.** Report inviato. Chiusura canale tra 5 secondi...")
    del active_pyramids[ctx.channel.id]
    await asyncio.sleep(5)
    await ctx.channel.delete()

async def main():
    await start_web_server()
    token = os.environ.get("DISCORD_TOKEN")
    await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())
