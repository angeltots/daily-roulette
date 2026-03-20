import discord
from discord.ext import commands, tasks
import requests
import os
import random
import datetime as dt
import pytz  # IMPORTANTE: Agregar a requirements.txt
from pymongo import MongoClient
from dotenv import load_dotenv
from keep_alive import keep_alive

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
CLICKUP_TOKEN = os.getenv("CLICKUP_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
DISCORD_CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID")
TEAM_ID = "31625254"

ARG_TZ = pytz.timezone('America/Argentina/Buenos_Aires')

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
    """Retorna la fecha y hora actual en Argentina."""
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
    print(f"📝 Log guardado: {evento} ({ahora.strftime('%H:%M')} ART)")

def get_mention(nombre):
    user_id = INTEGRANTES_DATA.get(nombre)
    return f"<@{user_id}>" if user_id else nombre

# --- LÓGICA CLICKUP ---
def get_clickup_availability():
    if not CLICKUP_TOKEN:
        guardar_log("Error ClickUp", "No se encontró el token de ClickUp")
        return None, {}, []

    url = f"https://api.clickup.com/api/v2/team/{TEAM_ID}/task"
    ahora_arg = get_now_arg()
    now_ms = int(ahora_arg.timestamp() * 1000)
    
    headers = {"Authorization": CLICKUP_TOKEN, "Content-Type": "application/json"}
    params = {"include_closed": "true", "subtasks": "true"}
    
    try:
        response = requests.get(url, headers=headers, params=params)
        tasks_data = response.json().get("tasks", [])
        
        ausentes = {} 
        cumpleañeros = []
        motivo_cancelacion = None 

        for task in tasks_data:
            name = task["name"].lower()
            start = task.get("start_date")
            due = task.get("due_date")
            en_rango = False 
            
            if start and due:
                en_rango = int(start) <= now_ms <= int(due)
            elif due and not start:
                due_date_dt = dt.datetime.fromtimestamp(int(due) / 1000, tz=dt.timezone.utc).astimezone(ARG_TZ)
                if due_date_dt.date() == ahora_arg.date():
                    en_rango = True
            
            if en_rango:
                if "feriado" in name or "argentina" in name:
                    motivo_cancelacion = "Feriado Nacional 🇦🇷"
                elif "free meetings day" in name:
                    motivo_cancelacion = "Free Meetings Day 🚫📅"
                
                for persona in INTEGRANTES:
                    partes = persona.lower().split()
                    primer_nombre = partes[0]
                    apellido = partes[-1]
                    
                    if primer_nombre in name or apellido in name or (primer_nombre == "christian" and "chris" in name):
                        if "half people day" in name:
                            ausentes[persona] = "Half People Day 🌗"
                        elif "people day" in name:
                            ausentes[persona] = "People Day 🌴"
                        elif "vacaciones" in name:
                            ausentes[persona] = "Vacaciones ✈️"
                        elif "birthday" in name or "cumple" in name:
                            ausentes[persona] = "Cumpleaños 🎉"
                            if persona not in cumpleañeros:
                                cumpleañeros.append(persona)
                        else:
                            ausentes[persona] = "Ausente 🛌"
        
        guardar_log("Lectura ClickUp Exitosa", {
            "motivo_cancelacion": motivo_cancelacion,
            "ausentes": ausentes,
            "cumpleañeros": cumpleañeros
        })
        return motivo_cancelacion, ausentes, cumpleañeros
    except Exception as e:
        guardar_log("Error ClickUp", str(e))
        return None, {}, []


class SelectorNotas(discord.ui.Select):
    def __init__(self, principal_asignado):
        self.principal_asignado = principal_asignado
        opciones = [discord.SelectOption(label=nombre) for nombre in INTEGRANTES]
        super().__init__(placeholder="¿Alguien más tomó las notas hoy?", min_values=1, max_values=1, options=opciones)

    async def callback(self, interaction: discord.Interaction):
        # 1. Desactivamos el menú visualmente y avisamos a Discord que estamos trabajando
        self.disabled = True
        # Usamos edit_message para responder a la interacción AL INSTANTE
        await interaction.response.edit_message(view=self.view)

        try:
            # 2. Ahora sí, hacemos el laburo pesado de MongoDB sin apuro
            anotador_real = self.values[0]
            hist = get_db_history()
            
            if self.principal_asignado in hist["this_week"]:
                hist["this_week"].remove(self.principal_asignado)
            if anotador_real not in hist["this_week"]:
                hist["this_week"].append(anotador_real)
                
            save_db_history(hist) 
            guardar_log("Cambio Manual de Notas", f"De {self.principal_asignado} a {anotador_real}")
            
           
            await interaction.followup.send(
                f"✅ ¡Hecho! Notas registradas a nombre de **{anotador_real}**. Base de datos actualizada 💾.",
                ephemeral=True
            )

        except Exception as e:
            print(f"🔥 Error en el callback: {e}")
            await interaction.followup.send("Hubo un problema al conectar con la base de datos.", ephemeral=True)

class VistaRuleta(discord.ui.View):
    def __init__(self, principal_asignado):
        super().__init__(timeout=None) 
        self.add_item(SelectorNotas(principal_asignado))

async def ejecutar_ruleta(canal):
    motivo_cancelacion, ausentes_dict, cumpleañeros = get_clickup_availability()
    history = get_db_history()
    today = get_now_arg()
    current_week = today.isocalendar()[1]
    ausentes_lista = list(ausentes_dict.keys()) 

    embed = discord.Embed(title="🎲 Ruleta de la Daily", color=0x3498DB)
    embed.set_footer(text=f"Semana {current_week} • ART: {today.strftime('%d/%m/%Y')}")
    
    if motivo_cancelacion:
        mensaje_texto = f"🛑 ¡Hola equipo! Hoy no hay ruleta porque: **{motivo_cancelacion}**."
        embed.description = "Día libre de notas. ⚡"
        guardar_log("Ruleta Cancelada", motivo_cancelacion)
        await canal.send(content=mensaje_texto, embed=embed)
        return

    if history["week_num"] != current_week:
        history["last_week"] = history["this_week"]
        history["this_week"] = []
        history["week_num"] = current_week

    candidatos = [m for m in INTEGRANTES if m not in history["this_week"] and m not in ausentes_lista]

    if not candidatos:
        mensaje_texto = "⚠️ No hay candidatos disponibles hoy."
        guardar_log("Ruleta Sin Candidatos", "Todos ausentes o ya participaron")
        await canal.send(content=mensaje_texto, embed=embed)
    else:
        prioridad = [m for m in candidatos if m not in history["last_week"]]
        principal = random.choice(prioridad) if prioridad else random.choice(candidatos)
        posibles_suplentes = [m for m in INTEGRANTES if m != principal and m not in ausentes_lista]
        suplente = random.choice(posibles_suplentes) if posibles_suplentes else "N/A"

        history["this_week"].append(principal)
        save_db_history(history)

        mencion_principal = get_mention(principal)
        mencion_suplente = get_mention(suplente)
        
        mensaje_texto = f"🔔 ¡Atención {mencion_principal}! Te toca la daily de hoy."
        embed.description = "¡El destino ha decidido los responsables de las notas de hoy!"
        embed.add_field(name="📝 Principal", value=mencion_principal, inline=True)
        embed.add_field(name="🛡️ Suplente", value=mencion_suplente, inline=True)
        
        if ausentes_dict:
            texto_ausencias = "\n".join([f"• **{p}**: {m}" for p, m in ausentes_dict.items()])
            embed.add_field(name="📋 Novedades", value=texto_ausencias, inline=False)

        if cumpleañeros:
            texto_cumple = "\n".join([f"🎉 ¡Feliz cumple {get_mention(c)}!" for c in cumpleañeros])
            mensaje_texto += f"\n\n{texto_cumple}"
            embed.add_field(name="🎁 Cumpleaños", value=texto_cumple, inline=False)
            embed.color = 0xF1C40F

        guardar_log("Sorteo Realizado", f"P: {principal} | S: {suplente}")
        await canal.send(content=mensaje_texto, embed=embed, view=VistaRuleta(principal))


intents = discord.Intents.default()
intents.message_content = True 
bot = commands.Bot(command_prefix="!", intents=intents)

HORA_EJECUCION = dt.time(hour=17, minute=30, tzinfo=dt.timezone.utc)

@tasks.loop(time=HORA_EJECUCION)
async def tarea_diaria_ruleta():
    if get_now_arg().weekday() > 4: 
        return
    
    canal = bot.get_channel(int(DISCORD_CHANNEL_ID))
    if canal:
        await ejecutar_ruleta(canal)

@bot.event
async def on_ready():
    print(f"🚀 Bot {bot.user} encendido en Render")
    if not tarea_diaria_ruleta.is_running():
        tarea_diaria_ruleta.start()

@bot.command()
async def ruleta(ctx):
    await ejecutar_ruleta(ctx.channel)

if __name__ == "__main__":
    keep_alive() 
    bot.run(DISCORD_TOKEN)