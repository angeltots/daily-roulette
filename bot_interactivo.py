import discord
from discord.ext import commands, tasks
import requests
import os
import random
import datetime as dt
from pymongo import MongoClient
from dotenv import load_dotenv
from keep_alive import keep_alive

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
CLICKUP_TOKEN = os.getenv("CLICKUP_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
DISCORD_CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID")
TEAM_ID = "31625254"

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

def get_db_history():
    doc = history_collection.find_one({"_id": "estado_ruleta"})
    if not doc:
        doc = {"_id": "estado_ruleta", "this_week": [], "last_week": [], "week_num": -1}
        history_collection.insert_one(doc)
    return doc

def save_db_history(history_data):
    history_collection.update_one({"_id": "estado_ruleta"}, {"$set": history_data}, upsert=True)

def guardar_log(evento, detalles):
   
    log_doc = {
        "fecha": dt.datetime.utcnow(),
        "evento": evento,
        "detalles": detalles
    }
    logs_collection.insert_one(log_doc)
    print(f"📝 Log guardado: {evento}")

def get_mention(nombre):
    user_id = INTEGRANTES_DATA.get(nombre)
    return f"<@{user_id}>" if user_id else nombre

def get_clickup_availability():
    if not CLICKUP_TOKEN:
        guardar_log("Error ClickUp", "No se encontró el token de ClickUp")
        return None, {}, []

    url = f"https://api.clickup.com/api/v2/team/{TEAM_ID}/task"
    now_ms = int(dt.datetime.now().timestamp() * 1000)
    
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
                due_date_dt = dt.datetime.fromtimestamp(int(due) / 1000)
                if due_date_dt.date() == dt.datetime.now().date():
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
        opciones = [discord.SelectOption(label=nombre, description="Registrar notas a nombre de este usuario") for nombre in INTEGRANTES]
        super().__init__(placeholder="¿Alguien más tomó las notas hoy?", min_values=1, max_values=1, options=opciones)

    async def callback(self, interaction: discord.Interaction):
        anotador_real = self.values[0]
        hist = get_db_history()
        
        if self.principal_asignado in hist["this_week"]:
            hist["this_week"].remove(self.principal_asignado)
            
        if anotador_real not in hist["this_week"]:
            hist["this_week"].append(anotador_real)
            
        save_db_history(hist) 
        
        guardar_log("Cambio Manual de Notas", f"{interaction.user.name} cambió las notas de {self.principal_asignado} a {anotador_real}")
        
        self.disabled = True 
        await interaction.message.edit(view=self.view)
        await interaction.response.send_message(f"✅ ¡Hecho! Las notas de hoy quedaron registradas a nombre de **{anotador_real}**. Base de datos actualizada 💾.")

class VistaRuleta(discord.ui.View):
    def __init__(self, principal_asignado):
        super().__init__(timeout=None) 
        self.add_item(SelectorNotas(principal_asignado))


async def ejecutar_ruleta(canal):
    motivo_cancelacion, ausentes_dict, cumpleañeros = get_clickup_availability()
    history = get_db_history()
    today = dt.datetime.now()
    current_week = today.isocalendar()[1]
    ausentes_lista = list(ausentes_dict.keys()) 

    embed = discord.Embed(title="🎲 Ruleta de la Daily", color=0x3498DB)
    embed.set_footer(text=f"Semana {current_week} • Daily Bot 🚀")
    mensaje_texto = ""
    vista_interactiva = None 

    if motivo_cancelacion:
        mensaje_texto = f"🛑 ¡Hola equipo! Hoy no hay ruleta de daily porque tenemos **{motivo_cancelacion}**."
        embed.description = "Hoy es un día libre de notas. Disfruten este dia al maximo⚡"
        guardar_log("Ruleta Cancelada", motivo_cancelacion)
    else:
        if history["week_num"] != current_week:
            history["last_week"] = history["this_week"]
            history["this_week"] = []
            history["week_num"] = current_week

        candidatos = [m for m in INTEGRANTES if m not in history["this_week"] and m not in ausentes_lista]

        if not candidatos:
            if not cumpleañeros and not ausentes_dict:
                guardar_log("Ruleta Omitida", "Sin eventos ni candidatos")
                return 
            
            mensaje_texto = "Hoy no hay candidatos disponibles para la daily."
            embed.description = "Todos están exentos o ausentes hoy."
            guardar_log("Ruleta Sin Candidatos", "Todos ausentes")
        else:
            prioridad = [m for m in candidatos if m not in history["last_week"]]
            principal = random.choice(prioridad) if prioridad else random.choice(candidatos)
            posibles_suplentes = [m for m in INTEGRANTES if m != principal and m not in ausentes_lista]
            suplente = random.choice(posibles_suplentes) if posibles_suplentes else "N/A"

            history["this_week"].append(principal)
            save_db_history(history)

            mencion_principal = get_mention(principal)
            mencion_suplente = get_mention(suplente) if suplente != "N/A" else "N/A"
            
            mensaje_texto = f"🔔 ¡Atención {mencion_principal}! Te toca la daily de hoy."
            embed.description = "¡El destino ha decidido los responsables de las notas de hoy!"
            embed.add_field(name="📝 Principal", value=mencion_principal, inline=True)
            embed.add_field(name="🛡️ Suplente", value=mencion_suplente, inline=True)
            
            vista_interactiva = VistaRuleta(principal)
            
            # Guardamos el resultado de la ruleta en los logs
            guardar_log("Sorteo Realizado", f"Principal: {principal} | Suplente: {suplente}")

    if ausentes_dict:
        texto_ausencias = "\n".join([f"• **{p}**: {m}" for p, m in ausentes_dict.items()])
        embed.add_field(name="📋 Novedades del equipo hoy", value=texto_ausencias, inline=False)

    if cumpleañeros:
        mensajes_feliz_cumple = [f"🎉 ¡Feliz cumpleaños {get_mention(c)}! Todos en Kupyo deseamos que pases un día espectacular. 🎂🚀" for c in cumpleañeros]
        texto_cumple = "\n\n".join(mensajes_feliz_cumple)
        mensaje_texto += f"\n\n{texto_cumple}" 
        embed.add_field(name="🎁 ¡Día de Cumpleaños!", value=texto_cumple, inline=False)
        embed.color = 0xF1C40F 

    if vista_interactiva:
        await canal.send(content=mensaje_texto, embed=embed, view=vista_interactiva)
    else:
        await canal.send(content=mensaje_texto, embed=embed)

# --- 5. EVENTOS Y TAREAS AUTOMÁTICAS ---
intents = discord.Intents.default()
intents.message_content = True 
bot = commands.Bot(command_prefix="!", intents=intents)

# Configuramos la hora: 14:30 Argentina = 17:30 UTC
HORA_EJECUCION = dt.time(hour=17, minute=30, tzinfo=dt.timezone.utc)

@tasks.loop(time=HORA_EJECUCION)
async def tarea_diaria_ruleta():
    if dt.datetime.now().weekday() > 4:
        return
    
    canal = bot.get_channel(int(DISCORD_CHANNEL_ID))
    if canal:
        print("⏰ Ejecutando ruleta programada...")
        await ejecutar_ruleta(canal)
    else:
        print("❌ Error: No se encontró el canal de Discord. Revisa el DISCORD_CHANNEL_ID.")

@bot.event
async def on_ready():
    print(f"🚀 ¡Bot {bot.user} encendido!")
    tarea_diaria_ruleta.start() # Arrancamos el reloj interno
    print("⏰ Temporizador activado: La ruleta correrá a las 14:30 ART (Lunes a Viernes).")

@bot.command()
async def ruleta(ctx):
    await ejecutar_ruleta(ctx.channel)

if __name__ == "__main__":
    keep_alive() 
    bot.run(DISCORD_TOKEN)