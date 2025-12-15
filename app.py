import streamlit as st
import pandas as pd
import datetime
import os
import json

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="Panel de Informes de Materiales", layout="wide")

# Archivo para guardar los datos persistentemente (simulando LocalStorage)
DB_FILE = "db_proyectos.json"

# --- FUNCIONES DE PERSISTENCIA (GUARDAR DATOS) ---
def cargar_datos():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return []
    return []

def guardar_datos(lista_proyectos):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(lista_proyectos, f, default=str)

# Inicializar estado de la sesión
if 'proyectos' not in st.session_state:
    st.session_state.proyectos = cargar_datos()

# --- LÓGICA DE PROCESAMIENTO (REPLICANDO TU JS) ---
def procesar_excel(df):
    """
    Replica la función 'generarResumenEjecutivo' de tu Script JS.
    """
    # Normalizar nombres de columnas (quitar espacios extra y mayúsculas)
    df.columns = [str(c).strip().upper() for c in df.columns]
    
    # KPIs Básicos
    total_registros = len(df)
    
    # Suma de Cantidad Disponible (manejo de errores si no es número)
    if "CANT DISPONIBLE" in df.columns:
        total_disponible = pd.to_numeric(df["CANT DISPONIBLE"], errors='coerce').fillna(0).sum()
    else:
        total_disponible = 0

    # Conteos de Estatus
    conteo_sc = df["ESTATUS S.C."].value_counts().to_dict() if "ESTATUS S.C." in df.columns else {}
    conteo_oc = df["ESTATUS O.C."].value_counts().to_dict() if "ESTATUS O.C." in df.columns else {}

    # Lógica de Materiales Críticos
    # Critico si: Cancelado OR (Prometida Vencida AND Sin fecha llegada)
    criticos = []
    
    # Aseguramos formato fecha
    hoy = pd.Timestamp.now()
    
    # Copia para trabajar fechas sin alertas
    df_proc = df.copy()
    
    cols_fecha = ["FECHA PROMETIDA", "FECHA DE LLEGADA"]
    for col in cols_fecha:
        if col in df_proc.columns:
            df_proc[col] = pd.to_datetime(df_proc[col], errors='coerce')

    if "FECHA PROMETIDA" in df_proc.columns and "FECHA DE LLEGADA" in df_proc.columns:
        for index, row in df_proc.iterrows():
            est_sc = str(row.get("ESTATUS S.C.", "")).upper()
            est_oc = str(row.get("ESTATUS O.C.", "")).upper()
            
            es_cancelado = ("CANCELADA" in est_sc) or ("CANCELADA" in est_oc)
            
            fecha_prom = row["FECHA PROMETIDA"]
            fecha_lleg = row["FECHA DE LLEGADA"]
            
            # Lógica JS: prometidoVencido && sinLlegada
            vencido = False
            if pd.notnull(fecha_prom) and pd.isnull(fecha_lleg):
                if fecha_prom < hoy:
                    vencido = True
            
            if es_cancelado or vencido:
                criticos.append({
                    "No. S.C.": row.get("NO. S.C.", "-"),
                    "Titulo": row.get("TITULO DE LA REQUISICION", "Sin título"),
                    "Estatus SC": est_sc,
                    "Prometida": row["FECHA PROMETIDA"].strftime('%d/%m/%Y') if pd.notnull(row["FECHA PROMETIDA"]) else "-",
                    "Motivo": "CANCELADA" if es_cancelado else "VENCIDA"
                })

    return {
        "total_registros": total_registros,
        "total_disponible": total_disponible,
        "conteo_sc": conteo_sc,
        "conteo_oc": conteo_oc,
        "criticos": criticos
    }

# --- INTERFAZ GRÁFICA ---

# Estilos CSS personalizados para parecerse a tu HTML original
st.markdown("""
    <style>
    .big-font { font-size:20px !important; font-weight: bold; color: #1f4e79; }
    .header-style { background-color: #1f4e79; color: white; padding: 10px; border-radius: 5px; }
    div[data-testid="stMetricValue"] { font-size: 24px; }
    </style>
    """, unsafe_allow_html=True)

# Encabezado
st.markdown('<div class="header-style"><h1>📋 Informe Ejecutivo de Control de Materiales</h1></div>', unsafe_allow_html=True)
st.write("")

# --- SIDEBAR: PANEL DE ADMINISTRACIÓN ---
with st.sidebar:
    st.header("⚙️ Panel de Administración")
    
    # Input de contraseña (replicando tu JS)
    password = st.text_input("Clave de Administrador", type="password")
    
    if password == "1234":
        st.success("🔓 Acceso Concedido")
        st.markdown("---")
        st.subheader("Subir Nuevo Proyecto")
        
        nuevo_nombre = st.text_input("Nombre del Proyecto (Ej. R-1916)")
        nuevo_archivo = st.file_uploader("Cargar Excel (.xlsx)", type=["xlsx"])
        
        if st.button("Procesar y Guardar"):
            if nuevo_nombre and nuevo_archivo:
                try:
                    df = pd.read_excel(nuevo_archivo)
                    resumen = procesar_excel(df)
                    
                    nuevo_proyecto = {
                        "id": f"proj_{datetime.datetime.now().timestamp()}",
                        "nombre": nuevo_nombre,
                        "resumen": resumen
                    }
                    
                    st.session_state.proyectos.append(nuevo_proyecto)
                    guardar_datos(st.session_state.proyectos) # Guardar en JSON
                    st.success(f"Proyecto '{nuevo_nombre}' guardado éxito.")
                    st.rerun() # Recargar para actualizar lista
                except Exception as e:
                    st.error(f"Error al leer el Excel: {e}")
            else:
                st.warning("Falta nombre o archivo.")
        
        st.markdown("---")
        st.subheader("Gestionar Proyectos")
        if st.session_state.proyectos:
            df_proys = pd.DataFrame(st.session_state.proyectos)
            st.dataframe(df_proys[["nombre"]], hide_index=True)
            
            if st.button("🗑️ Eliminar TODOS los proyectos", type="primary"):
                st.session_state.proyectos = []
                guardar_datos([])
                st.rerun()
        else:
            st.info("No hay proyectos cargados.")
            
    else:
        if password:
            st.error("Clave incorrecta")
        st.info("Introduce la clave para cargar o borrar proyectos.")

# --- ZONA PÚBLICA (MAIN) ---

# Selector de Proyecto
if not st.session_state.proyectos:
    st.info("👋 No hay proyectos cargados. Por favor, usa el panel de administración (izquierda) para subir uno.")
else:
    nombres_proyectos = [p["nombre"] for p in st.session_state.proyectos]
    seleccion = st.selectbox("📂 Seleccione un proyecto:", nombres_proyectos)
    
    # Buscar datos del proyecto seleccionado
    proyecto_actual = next((p for p in st.session_state.proyectos if p["nombre"] == seleccion), None)
    
    if proyecto_actual:
        r = proyecto_actual["resumen"]
        
        st.markdown("---")
        st.markdown(f"<div class='big-font'>Resumen: {proyecto_actual['nombre']}</div>", unsafe_allow_html=True)
        
        # 1. Métricas Principales (Tarjetas)
        col1, col2 = st.columns(2)
        col1.metric("Total de Partidas", r["total_registros"])
        col2.metric("Cantidad Disponible", f"{r['total_disponible']:,.2f}")
        
        st.markdown("---")
        
        # 2. Gráficos de Estatus (Reemplaza las listas de texto del HTML)
        c1, c2 = st.columns(2)
        
        with c1:
            st.subheader("Estatus S.C.")
            if r["conteo_sc"]:
                df_sc = pd.DataFrame(list(r["conteo_sc"].items()), columns=["Estatus", "Cantidad"])
                st.dataframe(df_sc, use_container_width=True, hide_index=True)
            else:
                st.info("Sin datos de S.C.")

        with c2:
            st.subheader("Estatus O.C.")
            if r["conteo_oc"]:
                df_oc = pd.DataFrame(list(r["conteo_oc"].items()), columns=["Estatus", "Cantidad"])
                st.dataframe(df_oc, use_container_width=True, hide_index=True)
            else:
                st.info("Sin datos de O.C.")

        # 3. Materiales Críticos
        st.markdown("---")
        st.subheader("🚨 Materiales Críticos (Cancelados o Vencidos)")
        
        criticos = r["criticos"]
        if criticos:
            # Mostrar tabla bonita
            st.dataframe(pd.DataFrame(criticos), use_container_width=True)
        else:
            st.success("✅ ¡Excelente! No se detectaron materiales críticos con la lógica actual.")
