import discord
from discord.ext import commands, tasks
import requests
import os
import random
import datetime as dt
import pytz 
from pymongo import MongoClient
from dotenv import load_dotenv
from keep_alive import keep_alive

# Cargar variables de entorno
load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
DISCORD_CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID")
GAS_WEB_APP_URL = os.getenv("GAS_WEB_APP_URL")

# Configuración de Zona Horaria
ARG_TZ = pytz.timezone('America/Argentina/Buenos_Aires')

# Datos de Integrantes
INTEGRANTES_DATA = {
    "Juan Carlos Urquiza": "1460706682274451467",
    "Catriel Caruso": "1311265389723783179",
    "Angel Mendez": "1362026774988591299",
    "Sol Gosso": "1184514902963015710",
    "Luis Márquez": "1302037681227825215",
    "Matias Camiletti": "1043717500128481310",
    "Christian Ferrer": "1433452588183064658"
}
INTEGRANTES = list(INTEGRANTES_DATA.keys())

mongo_client = MongoClient(MONGO_URI)
db = mongo_client["kupyo_bot"] 
history_collection = db["historial_dailys"] 
logs_collection = db["logs_ejecucion"] 


def get_now_arg():
    return dt.datetime.now(ARG_TZ)

def get_db_history():
    doc = history_collection.find_one({"_id": "estado_ruleta"})
    if not doc:
        doc = {"_id": "estado_ruleta", "this_week": [], "last_week": [], "week_num": -1}
        history_collection.insert_one(doc)
    return doc

def save_db_history(history_data):
    history_collection.update_one({"_id": "estado_ruleta"}, {"$set": history_data}, upsert=True)

def guardar_log(evento, detalles):
    ahora = get_now_arg()
    log_doc = {
        "fecha": ahora,
        "fecha_str": ahora.strftime("%Y-%m-%d %H:%M:%S"),
        "evento": evento,
        "detalles": detalles
    }
    logs_collection.insert_one(log_doc)
    print(f"📝 Log guardado: {evento}")

def get_mention(nombre):
    user_id = INTEGRANTES_DATA.get(nombre)
    return f"<@{user_id}>" if user_id else nombre


def get_calendar_availability():
    """Consulta la Web App de Google para feriados y ausencias"""
    if not GAS_WEB_APP_URL:
        print("⚠️ Advertencia: GAS_WEB_APP_URL no definida")
        return None, {}, []
    
    try:
        response = requests.get(GAS_WEB_APP_URL, timeout=10)
        data = response.json()
        
        motivo = data.get("motivo_cancelacion")
        ausentes = data.get("ausentes", {})
        cumples = data.get("cumpleañeros", [])
        
        return motivo, ausentes, cumples
    except Exception as e:
        print(f"🔥 Error consultando Google Calendar: {e}")
        return None, {}, []


class SelectorNotas(discord.ui.Select):
    def __init__(self):
        opciones = [discord.SelectOption(label=nombre) for nombre in INTEGRANTES]
        super().__init__(
            placeholder="¿Alguien más tomó las notas hoy?",
            min_values=1, max_values=1, options=opciones,
            custom_id="selector_notas_v1" 
        )

    async def callback(self, interaction: discord.Interaction):
        self.disabled = True
        await interaction.response.edit_message(view=self.view)

        try:
            embed = interaction.message.embeds[0]
            principal_asignado = "Desconocido"
            for field in embed.fields:
                if "Principal" in field.name:
                    u_id = field.value.replace("<@", "").replace(">", "").replace("!", "")
                    for n, uid in INTEGRANTES_DATA.items():
                        if uid == u_id: principal_asignado = n; break
            
            anotador_real = self.values[0]
            hist = get_db_history()
            
            if principal_asignado in hist["this_week"]: hist["this_week"].remove(principal_asignado)
            if anotador_real not in hist["this_week"]: hist["this_week"].append(anotador_real)
            
            save_db_history(hist) 
            guardar_log("Cambio Manual de Notas", f"De {principal_asignado} a {anotador_real}")
            await interaction.followup.send(f"✅ Notas registradas a nombre de **{anotador_real}**.", ephemeral=True)
        except Exception as e:
            print(f"🔥 Error en el callback: {e}")

class VistaRuleta(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None) 
        self.add_item(SelectorNotas())


async def ejecutar_ruleta(canal):
    motivo, ausentes_dict, cumples = get_calendar_availability()
    history = get_db_history()
    today = get_now_arg()
    current_week = today.isocalendar()[1]
    
    embed = discord.Embed(color=0x3498DB)
    embed.set_footer(text=f"Semana {current_week} • {today.strftime('%d/%m/%Y')}")
    
    if motivo:
        es_feriado = "feriado" in motivo.lower() or "argentina" in motivo.lower()
        embed.title = "🏖️ ¡Día de Relax!" if es_feriado else "🔇 Modo Concentración"
        embed.color = 0x2ECC71 if es_feriado else 0x95A5A6
        
        saludo = "¡Disfruten muchísimo del descanso y recarguen pilas, equipo! Nos vemos a la vuelta. 👋☀️" if es_feriado else "¡Día libre de reuniones! Aprovechen para meterle a fondo al código/validaciones/tasks 👨‍💻🚀"
        
        embed.description = f"Hoy no corremos la ruleta porque tenemos: **{motivo}**.\n\n{saludo}"
        
        await canal.send(embed=embed)
        guardar_log("Ruleta Cancelada", motivo)
        return

    if history["week_num"] != current_week:
        history["last_week"], history["this_week"], history["week_num"] = history["this_week"], [], current_week

    candidatos = [m for m in INTEGRANTES if m not in history["this_week"] and m not in ausentes_dict]

    if not candidatos:
        embed.title = "⚠️ Sin candidatos"
        embed.description = "Parece que hoy no hay nadie disponible para el sorteo (o ya todos pasaron esta semana)."
        await canal.send(embed=embed)
    else:
        # --- 3. SORTEO ---
        prioridad = [m for m in candidatos if m not in history["last_week"]]
        principal = random.choice(prioridad) if prioridad else random.choice(candidatos)
        
        posibles_suplentes = [m for m in INTEGRANTES if m != principal and m not in ausentes_dict]
        suplente = random.choice(posibles_suplentes) if posibles_suplentes else "N/A"

        history["this_week"].append(principal)
        save_db_history(history)

        mencion_p = get_mention(principal)
        mencion_s = get_mention(suplente)
        
        embed.title = "🎲 Ruleta de la Daily"
        embed.description = "¡El destino ha hablado! Estos son los responsables de hoy:"
        embed.add_field(name="📝 Principal", value=mencion_p, inline=True)
        embed.add_field(name="🛡️ Suplente", value=mencion_s, inline=True)
        
        if ausentes_dict:
            txt = "\n".join([f"• **{p}**: {m}" for p, m in ausentes_dict.items()])
            embed.add_field(name="📋 Quiénes no están hoy", value=txt, inline=False)
        
        if cumples:
            txt = "\n".join([f"✨ ¡Feliz nivel nuevo {get_mention(c)}! Todos en **Kupyo** te deseamos un maravilloso día lleno de alegría. 🎂🚀" for c in cumples])
            embed.add_field(name="🌟 ¡Hoy celebramos!", value=txt, inline=False)

        guardar_log("Sorteo Realizado", f"P: {principal} | S: {suplente}")
        await canal.send(content=f"🔔 ¡Atención {mencion_p}! El escenario es tuyo.", embed=embed, view=VistaRuleta())


intents = discord.Intents.default()
intents.message_content = True 
bot = commands.Bot(command_prefix="!", intents=intents)

@tasks.loop(time=dt.time(hour=17, minute=30, tzinfo=dt.timezone.utc))
async def tarea_diaria_ruleta():
    ahora = get_now_arg()
    if ahora.weekday() <= 4: 
        canal = bot.get_channel(int(DISCORD_CHANNEL_ID))
        if canal: await ejecutar_ruleta(canal)

@bot.event
async def on_ready():
    print(f"🚀 Bot {bot.user} encendido y sincronizado con Google Calendar")
    bot.add_view(VistaRuleta()) 
    if not tarea_diaria_ruleta.is_running():
        tarea_diaria_ruleta.start()

@bot.command()
async def ruleta(ctx):
    """Comando manual para forzar la ruleta"""
    await ejecutar_ruleta(ctx.channel)

if __name__ == "__main__":
    keep_alive() 
    bot.run(DISCORD_TOKEN)