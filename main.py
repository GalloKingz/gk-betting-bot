import os
import asyncio
import random
import string
from datetime import datetime, timezone
from aiohttp import web
import discord
from discord.ext import commands, tasks
import json

# --- MINI SERVER WEB PER MANTENERE ATTIVO IL WEB SERVICE SU RENDER ---
async def handle(request):
    return web.Response(text="GK Betting Bot Online!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

# Inizializzazione Bot Discord
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

REPORT_CHANNEL_NAME = "🏆・vincite-e-perdite"
LOG_CHANNEL_NAME = "🤖-bot-log"
DB_CHANNEL_NAME = "🗄️-database-persistente"

active_pyramids = {}
user_balances = {} # Dizionario in memoria per i conti utente
last_health_check_message_id = None

# --- SISTEMA DI PERSISTENZA TRAMITE MESSAGGIO ROTATIVO SU DISCORD ---
async def load_database_from_discord(guild):
    global user_balances
    try:
        category = discord.utils.get(guild.categories, name="🛡️ OWNER & STAFF")
        if not category:
            return
        channel = discord.utils.get(category.text_channels, name=DB_CHANNEL_NAME)
        if not channel:
            return
        
        async for message in channel.history(limit=5):
            if message.author == guild.me and message.content.startswith("```json"):
                content = message.content.replace("```json", "").replace("```", "").strip()
                user_balances = json.loads(content)
                print("Database dei conti caricato con successo da Discord!")
                return
    except Exception as e:
        print(f"Errore nel caricamento del database da Discord: {e}")

async def save_database_to_discord(guild):
    try:
        category = discord.utils.get(guild.categories, name="🛡️ OWNER & STAFF")
        if not category:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }
            category = await guild.create_category(name="🛡️ OWNER & STAFF", overwrites=overwrites)

        channel = discord.utils.get(category.text_channels, name=DB_CHANNEL_NAME)
        if not channel:
            channel = await guild.create_text_channel(name=DB_CHANNEL_NAME, category=category)

        json_data = f"```json\n{json.dumps(user_balances, indent=4)}\n```"

        last_msg = None
        async for message in channel.history(limit=10):
            if message.author == guild.me:
                last_msg = message
                break
        
        if last_msg:
            await last_msg.edit(content=json_data)
        else:
            await channel.send(content=json_data)
    except Exception as e:
        print(f"Errore nel salvataggio del database su Discord: {e}")

async def send_bot_log(guild, message_text, color=discord.Color.blue()):
    try:
        category = discord.utils.get(guild.categories, name="🛡️ OWNER & STAFF")
        if not category:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }
            category = await guild.create_category(name="🛡️ OWNER & STAFF", overwrites=overwrites)

        channel = discord.utils.get(category.text_channels, name=LOG_CHANNEL_NAME)
        if not channel:
            channel = await guild.create_text_channel(name=LOG_CHANNEL_NAME, category=category)
        
        embed = discord.Embed(
            title="🤖 [GK BOT SYSTEM LOG]",
            description=message_text,
            color=color,
            timestamp=datetime.now(timezone.utc)
        )
        await channel.send(embed=embed)
    except Exception as e:
        print(f"Errore nell'invio del log su Discord: {e}")

@bot.event
async def on_ready():
    print(f"Bot connesso con successo come {bot.user}")
    
    for guild in bot.guilds:
        await load_database_from_discord(guild)
        break 

    bot.add_view(PersistentPyramidView())
    await restore_active_pyramids()
    
    for guild in bot.guilds:
        await send_bot_log(guild, f"🟢 **Bot avviato con successo!** Connesso come `{bot.user}`. Gestione lobby e conti attivi.", discord.Color.green())

    if not keep_alive_ping_log.is_running():
        keep_alive_ping_log.start()

@tasks.loop(minutes=10)
async def keep_alive_ping_log():
    global last_health_check_message_id
    for guild in bot.guilds:
        try:
            category = discord.utils.get(guild.categories, name="🛡️ OWNER & STAFF")
            if not category:
                continue
            channel = discord.utils.get(category.text_channels, name=LOG_CHANNEL_NAME)
            if not channel:
                continue

            if last_health_check_message_id:
                try:
                    old_msg = await channel.fetch_message(last_health_check_message_id)
                    await old_msg.delete()
                except Exception:
                    pass

            embed = discord.Embed(
                title="🤖 [GK BOT SYSTEM LOG]",
                description="💓 **Health Check periodico:** Il bot è attivo e il server web risponde correttamente.",
                color=discord.Color.teal(),
                timestamp=datetime.now(timezone.utc)
            )
            new_msg = await channel.send(embed=embed)
            last_health_check_message_id = new_msg.id
        except Exception as e:
            print(f"Errore nel task di health check: {e}")

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

# --- MODALE E VIEW PIRAMIDE ---
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
                err_msg = await interaction.followup.send("❌ Inserisci un importo numerico valido!", ephemeral=True)
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
                err_msg = await interaction.followup.send("❌ Puoi aggiungere al **massimo 3 compagni** in totale.", ephemeral=True)
                await asyncio.sleep(4)
                try: await err_msg.delete()
                except: pass
                return

            for user in invited_list:
                overwrites[user] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

            category = discord.utils.get(guild.categories, name="STANZE PRIVACY")
            if not category:
                for cat in guild.categories:
                    if "STANZE PRIVACY" in cat.name.upper():
                        category = cat
                        break

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
                description=f"Stanza privata protetta!\n\n👥 **Partecipanti ({num_totale_giocatori}/4):**\n{partecipanti_str}",
                color=discord.Color.blue()
            )
            embed.add_field(name="💰 Cassa Iniziale", value=f"`{round(cassa_valore, 2)}€`", inline=False)
            
            comandi_guida = (
                "• `!gioca [importo]` ➔ Registra giocata\n"
                "• `!vinto [totale]` ➔ Accredita vincita\n"
                "• `!perso` ➔ Schedina persa\n"
                "• `!soldi` ➔ Saldo cassa\n"
                "• `!out` ➔ Chiudi e invia report"
            )
            embed.add_field(name="📖 Comandi Rapidi", value=comandi_guida, inline=False)
            
            mentions_text = f"{interaction.user.mention} " + " ".join([u.mention for u in invited_list])
            await channel.send(content=mentions_text, embed=embed)

            msg = await interaction.followup.send(f"✅ Stanza creata: {channel.mention}", ephemeral=True)
            await asyncio.sleep(4)
            try: await msg.delete()
            except: pass
            
            await send_bot_log(guild, f"📂 **Nuova Lobby:** `{channel_full_name}` aperta da {interaction.user.name}.", discord.Color.purple())

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
    embed = discord.Embed(title="💎 GESTIONE PIRAMIDE BETS", description="Clicca sul bottone per impostare il budget iniziale.", color=discord.Color.gold())
    await ctx.send(embed=embed, view=PersistentPyramidView())
    try: await ctx.message.delete()
    except: pass

# --- COMANDI DELLA STANZA ---
@bot.command(name="gioca")
async def cmd_gioca(ctx, importo: float = None):
    if ctx.channel.id not in active_pyramids:
        return
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
    if ctx.channel.id not in active_pyramids:
        return
    if vincita_totale is None:
        await ctx.send("❌ Specifica l'importo vinto. Esempio: `!vinto 35.50`")
        return
    data = active_pyramids[ctx.channel.id]
    data["cassa"] += vincita_totale
    await ctx.send(f"🎉 **VITTORIA!** Incassati `{vincita_totale}€`. **Cassa totale:** `{round(data['cassa'], 2)}€`")

@bot.command(name="perso")
async def cmd_perso(ctx):
    if ctx.channel.id not in active_pyramids:
        return
    data = active_pyramids[ctx.channel.id]
    data["giocata_attiva"] = 0.0
    await ctx.send(f"⚠️ Schedina persa. Cassa attuale: `{round(data['cassa'], 2)}€`")
    if data["cassa"] <= 0:
        await ctx.send("❌ Cassa a zero! Digita `!out` per chiudere la sessione.")
    else:
        await ctx.send("💪 Siete ancora in gioco!")

@bot.command(name="soldi")
async def cmd_soldi(ctx):
    if ctx.channel.id not in active_pyramids:
        return
    data = active_pyramids[ctx.channel.id]
    await ctx.send(f"📊 **Stato Cassa:** `{round(data['cassa'], 2)}€`")

@bot.command(name="out")
async def cmd_out(ctx):
    if ctx.channel.id not in active_pyramids:
        return
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
        try:
            report_channel = await guild.create_text_channel(name=REPORT_CHANNEL_NAME)
        except:
            report_channel = None

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
    await send_bot_log(guild, f"🔒 **Lobby chiusa:** `{ctx.channel.name}`. Saldo finale: `{saldo_finale}€`.", discord.Color.orange())
    
    del active_pyramids[ctx.channel.id]
    await asyncio.sleep(5)
    await ctx.channel.delete()

# --- AVVIO PRINCIPALE ---
async def main():
    await start_web_server()
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        print("❌ ERRORE: Token di Discord non trovato!")
        return
    await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())
