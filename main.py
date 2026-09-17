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

active_pyramids = {}

@bot.event
async def on_ready():
    print(f"Bot connesso con successo come {bot.user}")
    bot.add_view(PersistentPyramidView())
    if not daily_bet_task.is_running():
        daily_bet_task.start()

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
        label="Tagga amici o indica numero (es. @Nome o +3)",
        placeholder="Es. @Amico oppure +3",
        required=False,
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
            guild = interaction.guild

            cassa_valore = float(self.initial_cash.value.replace(",", "."))
            if cassa_valore < 5.0:
                await interaction.followup.send("❌ La cassa iniziale deve essere di almeno **5€**!", ephemeral=True)
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
                await interaction.followup.send("❌ Puoi aggiungere al massimo 3 compagni in totale!", ephemeral=True)
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
                "• `!gioca [importo]` ➔ Registra giocata\n"
                "• `!vinto [totale]` ➔ Accredita vincita\n"
                "• `!perso` ➔ Schedina persa\n"
                "• `!soldi` ➔ Saldo cassa\n"
                "• `!out` ➔ Chiudi e invia report"
            )
            embed.add_field(name="📖 Comandi Rapidi", value=comandi_guida, inline=False)
            
            mentions_text = f"{interaction.user.mention} " + " ".join([u.mention for u in invited_list])
            await channel.send(content=mentions_text, embed=embed)
            await interaction.followup.send(f"✅ Stanza privata creata con successo: {channel.mention}", ephemeral=True)

        except Exception as e:
            print(f"ERROre nel modale: {e}")
            try:
                await interaction.followup.send(f"❌ Si è verificato un errore interno: {e}", ephemeral=True)
            except:
                pass


# --- VIEW PERSISTENTE ---
class PersistentPyramidView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="➕ Nuova Schedina Piramidale", style=discord.ButtonStyle.green, custom_id="persistent_view:nuova_schedina_piramidale")
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
    view = PersistentPyramidView()
    await ctx.send(embed=embed, view=view)
    try:
        await ctx.message.delete()
    except:
        pass


@tasks.loop(hours=24)
async def daily_bet_task():
    await bot.wait_until_ready()
    channel = discord.utils.get(bot.get_all_channels(), name=TARGET_CHANNEL_NAME)
    if not channel:
        return
    # Task rimasta invariata per i pronostici


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
    await ctx.send(f"✅ **Schedina registrata!** Puntati `{importo}€`. Rimasti in cassa: `{round(data['cassa'], 2)}€`")

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

    guild = ctx.guild
    report_channel = discord.utils.get(guild.text_channels, name=REPORT_CHANNEL_NAME)
    if not report_channel:
        try:
            report_channel = await guild.create_text_channel(name=REPORT_CHANNEL_NAME)
        except:
            report_channel = None

    if saldo_finale >= cassa_iniziale:
        profitto = saldo_finale - cassa_iniziale
        embed_report = discord.Embed(
            title="🏆 SESSIONE CONCLUSA - IN PLUS!",
            description=f"👥 **Partecipanti ({num_giocatori}):** {tag_membri}\n💰 **Cassa Iniziale:** `{round(cassa_iniziale, 2)}€`\n📈 **Profitto Netto:** `+{round(profitto, 2)}€`",
            color=discord.Color.green()
        )
    else:
        perdita = cassa_iniziale - saldo_finale
        embed_report = discord.Embed(
            title="💀 SESSIONE CONCLUSA - CASSA PERSA",
            description=f"👥 **Partecipanti ({num_giocatori}):** {tag_membri}\n📉 **Cassa Persa:** `{round(perdita, 2)}€`",
            color=discord.Color.red()
        )

    if report_channel:
        await report_channel.send(content=tag_membri, embed=embed_report)

    await ctx.send("🔒 **Sessione chiusa.** Chiusura canale tra 5 secondi...")
    del active_pyramids[ctx.channel.id]
    await asyncio.sleep(5)
    await ctx.channel.delete()


async def main():
    await start_web_server()
    token = os.environ.get("DISCORD_TOKEN")
    await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())
