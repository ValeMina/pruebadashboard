import streamlit as st
import pandas as pd
import datetime as dt
import os
import json
import re
import plotly.graph_objects as go
from io import BytesIO

# =========================
# CONFIG
# =========================
st.set_page_config(page_title="TNG | Control de Materiales", layout="wide")

DB_FILE = "db_proyectos.json"
ADMIN_PASS = os.getenv("ADMIN_PASS", "1234")
PDF_DIR = "pdf_notas"

if not os.path.exists(PDF_DIR):
    os.makedirs(PDF_DIR)

# Detecta: SERVICIO / SERVICIOS / SERVICIO-PRECIO FIJO / etc.
SERVICIO_RE = re.compile(r"\bSERVICI", re.IGNORECASE)

# =========================
# PERSISTENCIA
# =========================
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
        json.dump(lista_proyectos, f, ensure_ascii=False, indent=2, default=str)

def upsert_proyecto(lista, nuevo):
    nombre = nuevo["nombre"]
    out = [p for p in lista if p.get("nombre") != nombre]
    out.append(nuevo)
    return out

def dedup_items_por_clave(items, keys):
    seen = set()
    out = []
    for it in items:
        k = tuple(str(it.get(x, "")).strip() for x in keys)
        if k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out

# =========================
# UTILIDADES
# =========================
def dias_restantes(fecha_prometida):
    hoy = pd.Timestamp.today().normalize()
    if pd.isna(fecha_prometida):
        return None
    return int((pd.Timestamp(fecha_prometida).normalize() - hoy).days)

def safe_int(x, default=0):
    try:
        return int(x)
    except:
        return default

def is_empty_oc(v):
    if pd.isna(v):
        return True
    s = str(v).strip().lower()
    return s in ["", "0", "0.0", "nan", "none"]

def item_es_servicio(it: dict) -> bool:
    desc = str(it.get("descripcion", "") or "")
    return bool(SERVICIO_RE.search(desc))

def filtrar_items_servicios(items: list) -> list:
    return [it for it in (items or []) if not item_es_servicio(it)]

def style_light_table(df: pd.DataFrame):
    # st.dataframe soporta pandas.Styler [web:425]
    return (
        df.style
        .set_properties(**{
            "background-color": "rgba(255,255,255,.85)",
            "color": "#0F172A",
            "border-color": "rgba(15,23,42,.12)",
        })
        .set_table_styles([
            {
                "selector": "th",
                "props": [
                    ("background-color", "rgba(226,232,240,.95)"),
                    ("color", "#0F172A"),
                    ("border-color", "rgba(15,23,42,.12)"),
                    ("font-weight", "700"),
                ],
            },
            {
                "selector": "td",
                "props": [("border-color", "rgba(15,23,42,.10)")],
            },
        ])
    )

# =========================
# ESTADO
# =========================
if "proyectos" not in st.session_state:
    st.session_state.proyectos = cargar_datos()
if "modo" not in st.session_state:
    st.session_state.modo = None
if "admin_ok" not in st.session_state:
    st.session_state.admin_ok = False

if "login_choice" not in st.session_state:
    st.session_state.login_choice = None
if "login_error" not in st.session_state:
    st.session_state.login_error = ""

# =========================
# LECTURA EXCEL
# =========================
def leer_nombre_proyecto_excel(file_bytes: bytes) -> str:
    df0 = pd.read_excel(BytesIO(file_bytes), header=None, engine="openpyxl")
    nombre = str(df0.iloc[3, 2]).strip()  # C4
    nombre = nombre.replace("NOMBRE DEL PROYECTO", "").replace(":", "").strip()
    if nombre.lower() in ["nan", "none", ""]:
        return "PROYECTO_SIN_NOMBRE"
    return nombre

def leer_tabla_excel(file_bytes: bytes) -> pd.DataFrame:
    raw = pd.read_excel(BytesIO(file_bytes), header=None, engine="openpyxl")
    header_row = None
    for i in range(len(raw)):
        row = raw.iloc[i].astype(str).tolist()
        if "No. S.C." in row:
            header_row = i
            break
    if header_row is None:
        raise ValueError("No se encontró el encabezado 'No. S.C.' en el Excel.")

    df = pd.read_excel(BytesIO(file_bytes), header=header_row, engine="openpyxl")
    df.columns = [str(c).replace("\n", " ").strip() for c in df.columns]
    return df

def filtrar_servicios(df: pd.DataFrame) -> pd.DataFrame:
    col_desc = "DESCRIPCION DE LA PARTIDA"
    if col_desc not in df.columns:
        cand = [c for c in df.columns if "DESCRIPCION" in c.upper() and "PARTIDA" in c.upper()]
        if cand:
            df = df.rename(columns={cand[0]: col_desc})
        else:
            raise ValueError("No existe la columna 'DESCRIPCION DE LA PARTIDA'.")

    # Quita SERVICIO, SERVICIOS, SERVICIO-..., etc. (por regex)
    mask = df[col_desc].astype(str).str.contains(r"\bSERVICI", case=False, na=False, regex=True)
    return df[~mask].copy()

# =========================
# ESTATUS
# =========================
ESTADOS_ORDEN = ["COMPLETADO", "PENDIENTE A LLEGAR", "SIN PEDIDO", "CANCELADO"]

def map_estatus_sc(valor):
    v = str(valor).strip().upper()
    if v == "A":
        return "COMPLETADO"
    if v == "Q":
        return "SIN PEDIDO"
    if v == "U":
        return "CANCELADO"
    return "PENDIENTE A LLEGAR"

def map_estatus_oc(valor):
    v = str(valor).strip().upper()
    if v == "A":
        return "COMPLETADO"
    if v == "C":
        return "CANCELADO"
    return "PENDIENTE A LLEGAR"

# =========================
# RESUMEN (dona + tendencia semanal)
# =========================
def clase_general_from_item(it: dict) -> str:
    no_oc = it.get("no_oc", "")
    est_sc = str(it.get("estatus_sc", "")).upper().strip()
    est_oc = str(it.get("estatus_oc", "")).upper().strip()

    if is_empty_oc(no_oc):
        return "SIN OC"
    if "CANCEL" in est_sc or "CANCEL" in est_oc:
        return "CANCELADO"
    if est_sc == "CANCELADO" or est_oc == "CANCELADO":
        return "CANCELADO"
    if est_sc == "COMPLETADO" or est_oc == "COMPLETADO":
        return "COMPLETADO"
    return "PENDIENTE A LLEGAR"

def construir_conteo_general_y_trend_desde_items(items: list) -> tuple[dict, list]:
    items = filtrar_items_servicios(items)
    if not items:
        return {}, []

    df = pd.DataFrame(items).copy()
    df["clase_general"] = df.apply(lambda r: clase_general_from_item(r.to_dict()), axis=1)
    conteo_general = df["clase_general"].value_counts(dropna=False).to_dict()

    trend = []
    if "fecha_prometida" in df.columns:
        df["fecha_prometida_dt"] = pd.to_datetime(df["fecha_prometida"], errors="coerce")
        dft = df[pd.notnull(df["fecha_prometida_dt"])].copy()
        if not dft.empty:
            g = dft.groupby(pd.Grouper(key="fecha_prometida_dt", freq="W-MON")).agg(
                solicitudes=("fecha_prometida_dt", "size")
            ).reset_index()
            g = g.rename(columns={"fecha_prometida_dt": "SEMANA"})
            trend = g.to_dict("records")

    return conteo_general, trend

def procesar_resumen(df: pd.DataFrame) -> dict:
    df2 = df.copy()
    df2.columns = [str(c).strip().upper() for c in df2.columns]
    total_registros = len(df2)

    if "CANT DISPONIBLE" in df2.columns:
        total_disponible = pd.to_numeric(df2["CANT DISPONIBLE"], errors="coerce").fillna(0).sum()
    else:
        total_disponible = 0

    if "ESTATUS S.C." in df2.columns:
        sc_cat = df2["ESTATUS S.C."].apply(map_estatus_sc)
        conteo_sc = sc_cat.value_counts(dropna=False).to_dict()
    else:
        conteo_sc = {}

    if "ESTATUS O.C." in df2.columns:
        oc_cat = df2["ESTATUS O.C."].apply(map_estatus_oc)
        conteo_oc = oc_cat.value_counts(dropna=False).to_dict()
    else:
        conteo_oc = {}

    conteo_sc = {k: safe_int(conteo_sc.get(k, 0)) for k in ESTADOS_ORDEN}
    conteo_oc = {k: safe_int(conteo_oc.get(k, 0)) for k in ESTADOS_ORDEN}

    for col in ["FECHA PROMETIDA", "FECHA DE LLEGADA"]:
        if col in df2.columns:
            df2[col] = pd.to_datetime(df2[col], errors="coerce")

    # Críticos
    criticos = []
    hoy = pd.Timestamp.now()

    if "FECHA PROMETIDA" in df2.columns and "FECHA DE LLEGADA" in df2.columns:
        for _, row in df2.iterrows():
            est_sc_raw = str(row.get("ESTATUS S.C.", "")).upper().strip()
            est_oc_raw = str(row.get("ESTATUS O.C.", "")).upper().strip()

            es_cancelado = (est_sc_raw == "U") or (est_oc_raw == "C") or ("CANCEL" in est_sc_raw) or ("CANCEL" in est_oc_raw)
            fecha_prom = row.get("FECHA PROMETIDA", pd.NaT)
            fecha_lleg = row.get("FECHA DE LLEGADA", pd.NaT)

            vencido = False
            if pd.notnull(fecha_prom) and pd.isnull(fecha_lleg) and fecha_prom < hoy:
                vencido = True

            if es_cancelado or vencido:
                criticos.append({
                    "No. S.C.": row.get("NO. S.C.", "-"),
                    "Título": row.get("TITULO DE LA REQUISICION", "Sin título"),
                    "Estatus S.C.": map_estatus_sc(row.get("ESTATUS S.C.", "")),
                    "Estatus O.C.": map_estatus_oc(row.get("ESTATUS O.C.", "")),
                    "Fecha prometida": fecha_prom.strftime("%d/%m/%Y") if pd.notnull(fecha_prom) else "-"
                })

    # Items persistidos
    items = []
    cols = {
        "NO. S.C.": "no_sc",
        "TITULO DE LA REQUISICION": "titulo",
        "DESCRIPCION DE LA PARTIDA": "descripcion",
        "ESTATUS S.C.": "estatus_sc_raw",
        "ESTATUS O.C.": "estatus_oc_raw",
        "NO. O.C.": "no_oc",
        "FECHA PROMETIDA": "fecha_prometida",
        "FECHA DE LLEGADA": "fecha_llegada",
    }
    for _, row in df2.iterrows():
        it = {}
        for k, outk in cols.items():
            it[outk] = row.get(k, "")
        it["estatus_sc"] = map_estatus_sc(it.get("estatus_sc_raw", ""))
        it["estatus_oc"] = map_estatus_oc(it.get("estatus_oc_raw", ""))
        items.append(it)

    items = dedup_items_por_clave(items, keys=["no_sc", "descripcion", "no_oc"])
    items = filtrar_items_servicios(items)  # seguridad extra

    sin_oc_real = int(pd.Series([x.get("no_oc", None) for x in items]).apply(is_empty_oc).sum()) if items else 0
    conteo_general, trend = construir_conteo_general_y_trend_desde_items(items)

    return {
        "total_registros": int(len(items)),  # ojo: ya sin servicios
        "total_disponible": float(total_disponible),
        "conteo_sc": conteo_sc,
        "conteo_oc": conteo_oc,
        "criticos": criticos,
        "items": items,
        "sin_oc_real": sin_oc_real,
        "conteo_general": {k: safe_int(v) for k, v in conteo_general.items()},
        "trend": trend
    }

# =========================
# KPI CARD
# =========================
def kpi_card(label, value, hint="", tone="accent"):
    tone_map = {
        "accent": ("rgba(14,165,233,.18)", "#0EA5E9"),
        "ok": ("rgba(34,197,94,.18)", "#16A34A"),
        "warn": ("rgba(251,146,60,.18)", "#FB923C"),
        "danger": ("rgba(239,68,68,.18)", "#DC2626"),
    }
    bg, color = tone_map.get(tone, tone_map["accent"])
    st.markdown(
        f"""
        <div class="kpi">
          <div class="kpi-top">
            <div class="kpi-dot" style="background:{bg}; border-color:{color};"></div>
            <div class="kpi-label">{label}</div>
          </div>
          <div class="kpi-value">{value}</div>
          <div class="kpi-hint">{hint}</div>
        </div>
        """,
        unsafe_allow_html=True
    )

# =========================
# GRÁFICAS
# =========================
def donut_general(conteo_general: dict, titulo="Estado actual"):
    order = ["COMPLETADO", "PENDIENTE A LLEGAR", "SIN OC", "CANCELADO"]
    colors = {
        "COMPLETADO": "#22C55E",
        "PENDIENTE A LLEGAR": "#60A5FA",
        "SIN OC": "#FB923C",
        "CANCELADO": "#EF4444"
    }
    labels = order
    values = [int(conteo_general.get(k, 0)) for k in order]

    fig = go.Figure(data=[go.Pie(
        labels=labels,
        values=values,
        hole=0.68,
        marker=dict(
            colors=[colors.get(x, "#94A3B8") for x in labels],
            line=dict(color="rgba(15,23,42,.18)", width=2)
        ),
        textinfo="percent",
        textposition="inside",
        hovertemplate="<b>%{label}</b><br>Cantidad: %{value}<br>%{percent}<extra></extra>"
    )])

    fig.update_layout(
        title=dict(text=titulo, font=dict(color="#0F172A", size=18)),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#0F172A"),
        margin=dict(l=10, r=10, t=50, b=10),
        height=360,
        legend=dict(
            orientation="h",
            y=-0.28,
            font=dict(color="#0F172A", size=12),
            bgcolor="rgba(255,255,255,.80)",
            bordercolor="rgba(15,23,42,.15)",
            borderwidth=1
        )
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

def tendencia_semanal(trend_records, titulo="Tendencia semanal de solicitudes"):
    if not trend_records:
        fig = go.Figure()
        fig.update_layout(
            title=dict(text=titulo, font=dict(color="#0F172A", size=18)),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            height=360,
            margin=dict(l=10, r=10, t=55, b=10),
            annotations=[dict(text="Sin fechas para graficar", x=0.5, y=0.5, showarrow=False)]
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        return

    df_tr = pd.DataFrame(trend_records).copy()
    df_tr["SEMANA"] = pd.to_datetime(df_tr["SEMANA"], errors="coerce")
    df_tr["solicitudes"] = pd.to_numeric(df_tr["solicitudes"], errors="coerce").fillna(0).astype(int)
    df_tr = df_tr.sort_values("SEMANA")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_tr["SEMANA"],
        y=df_tr["solicitudes"],
        mode="lines+markers",
        name="Solicitudes",
        line=dict(color="#0EA5E9", width=3.5),
        marker=dict(size=8, color="#0EA5E9"),
        hovertemplate="Semana: %{x|%d/%m/%Y}<br>Solicitudes: %{y}<extra></extra>"
    ))

    fig.update_layout(
        title=dict(text=titulo, font=dict(color="#0F172A", size=18)),
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#0F172A"),
        margin=dict(l=10, r=10, t=55, b=45),
        height=360,
        xaxis=dict(
            title="Semana (lunes)",
            showgrid=True,
            gridcolor="rgba(15,23,42,.08)",
            linecolor="rgba(15,23,42,.25)",
            tickformat="%d/%m\n%Y",
            tickfont=dict(color="#0F172A", size=11),
            ticks="outside"
        ),
        yaxis=dict(
            title="Cantidad",
            showgrid=True,
            gridcolor="rgba(15,23,42,.08)",
            linecolor="rgba(15,23,42,.25)",
            tickfont=dict(color="#0F172A", size=11),
            rangemode="tozero",
            ticks="outside"
        ),
        legend=dict(orientation="h", y=1.12, x=0.01, font=dict(color="#0F172A")),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

# =========================
# CSS / TEMA
# =========================
st.markdown("""
<style>
:root{
  --bg:#E7F1EE;
  --bg2:#DDEBE7;
  --card:#ffffff;
  --border:rgba(15,23,42,.12);
  --accent:#0EA5E9;
}

.stApp{
  background:
    radial-gradient(1200px 600px at 15% 0%, rgba(14,165,233,.12), transparent 55%),
    radial-gradient(900px 500px at 85% 10%, rgba(34,197,94,.10), transparent 55%),
    linear-gradient(180deg, var(--bg) 0%, var(--bg2) 100%) !important;
}

html, body, p, span, label, div, h1, h2, h3, h4, h5, h6,
[data-testid="stMarkdownContainer"] *,
[data-testid="stWidgetLabel"] *,
[data-testid="stCaptionContainer"] *,
[data-testid="stSidebar"] *,
.stTextInput *, .stTextArea *, .stButton *{
  color: #0F172A !important;
}

.block-container{ padding-top: 1.0rem !important; max-width: 1240px; }

.tng-hero{
  background: rgba(255,255,255,.75);
  border: 1px solid var(--border);
  border-radius: 18px;
  padding: 16px;
  box-shadow: 0 12px 28px rgba(15,23,42,.11);
}
.tng-title{ font-size: 2.1rem; font-weight: 950; letter-spacing:-.6px; text-align:center; margin:0; }
.tng-subtitle{ text-align:center; margin-top:4px; font-size:.95rem; }

.logo-wrap{ display:flex; justify-content:center; margin-bottom:10px; }
.logo-card{ padding:10px 14px; background: rgba(255,255,255,.85); border:1px solid var(--border); border-radius:12px; }

.tng-card{
  background: var(--card) !important;
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 18px;
  box-shadow: 0 10px 24px rgba(15,23,42,.10);
}

/* KPI */
.kpi{
  background: #FFFFFF !important;
  border: 1px solid rgba(15,23,42,.12);
  border-radius: 16px;
  padding: 14px 16px;
  box-shadow: 0 10px 24px rgba(15,23,42,.08);
}
.kpi-top{ display:flex; align-items:center; gap:10px; }
.kpi-dot{ width: 12px; height: 12px; border-radius: 999px; border: 2px solid var(--accent); }
.kpi-label{ font-weight: 800; font-size:.95rem; }
.kpi-value{ font-size: 2.3rem; font-weight: 950; letter-spacing:-.6px; margin-top: 6px; }
.kpi-hint{ font-size: .88rem; margin-top: 2px; }

/* Sidebar */
section[data-testid="stSidebar"]{
  background: rgba(255,255,255,.75) !important;
  border-right:1px solid var(--border);
}

/* Botones */
button[kind="primary"], button[data-testid="baseButton-primary"]{
  background: linear-gradient(135deg, var(--accent) 0%, #0284C7 100%) !important;
  color: #ffffff !important;
  border:none !important;
  border-radius: 12px !important;
  font-weight: 850 !important;
  min-height: 44px !important;
}
button[kind="secondary"], button[data-testid="baseButton-secondary"]{
  background: rgba(255,255,255,.95) !important;
  color: #0F172A !important;
  border: 1.5px solid rgba(15,23,42,.18) !important;
  border-radius: 12px !important;
  font-weight: 850 !important;
  min-height: 44px !important;
}

/* Inputs */
div[data-baseweb="input"] > div{
  background: rgba(255,255,255,.92) !important;
  border: 1px solid rgba(15,23,42,.14) !important;
  border-radius: 12px !important;
}
div[data-baseweb="input"] input{ color:#0F172A !important; }
div[data-baseweb="input"] button{ background: transparent !important; color:#0F172A !important; }

/* Selectbox input blanco */
.stSelectbox > div[data-baseweb="select"] > div{
  background: rgba(255,255,255,.92) !important;
  border: 1px solid rgba(15,23,42,.14) !important;
  border-radius: 12px !important;
}
.stSelectbox svg, .stSelectbox path { fill: #0F172A !important; color:#0F172A !important; }

/* Dropdown LISTA */
div[role="listbox"], ul[role="listbox"], div[data-baseweb="menu"]{
  background: #0B2230 !important;
  border: 1px solid rgba(255,255,255,.14) !important;
  border-radius: 14px !important;
  box-shadow: 0 18px 36px rgba(15,23,42,.35) !important;
}
div[role="listbox"] li, ul[role="listbox"] li{ background: transparent !important; }
div[role="listbox"] li * , ul[role="listbox"] li *{ color: #FFFFFF !important; }
div[role="listbox"] li:hover, ul[role="listbox"] li:hover{ background: rgba(14,165,233,.25) !important; }

/* File uploader dropzone blanco */
[data-testid="stFileUploaderDropzone"]{
  background: rgba(255,255,255,.92) !important;
  border: 1px dashed rgba(15,23,42,.25) !important;
  border-radius: 14px !important;
}
[data-testid="stFileUploaderDropzone"] *{ color: #0F172A !important; }

footer{ visibility:hidden; }
</style>
""", unsafe_allow_html=True)

# =========================
# HEADER
# =========================
st.markdown('<div class="tng-hero">', unsafe_allow_html=True)
if os.path.exists("LOGOTNG.jpg"):
    st.markdown('<div class="logo-wrap"><div class="logo-card">', unsafe_allow_html=True)
    st.image("LOGOTNG.jpg", width=140)
    st.markdown("</div></div>", unsafe_allow_html=True)
st.markdown('<h1 class="tng-title">Control de Materiales</h1>', unsafe_allow_html=True)
st.markdown('<p class="tng-subtitle">Panel ejecutivo de proyectos y estatus de compras</p>', unsafe_allow_html=True)
st.markdown("</div>", unsafe_allow_html=True)
st.write("")

# =========================
# PANTALLA DE ENTRADA
# =========================
if st.session_state.modo is None:
    _, center, _ = st.columns([1, 2, 1])
    with center:
        st.markdown('<div class="tng-card">', unsafe_allow_html=True)
        st.subheader("Elegir modo de acceso")

        c1, c2 = st.columns(2)
        with c1:
            if st.button("Invitado", type="secondary", use_container_width=True):
                st.session_state.modo = "guest"
                st.session_state.admin_ok = False
                st.session_state.login_choice = None
                st.session_state.login_error = ""
                st.rerun()

        with c2:
            if st.button("Administrador", type="primary", use_container_width=True):
                st.session_state.login_choice = "admin"
                st.session_state.login_error = ""

        if st.session_state.login_choice == "admin":
            with st.form("admin_login_form", clear_on_submit=False):
                pwd = st.text_input("Contraseña de administrador", type="password")
                submit = st.form_submit_button("Acceder", type="primary", use_container_width=True)

            if submit:
                if pwd == ADMIN_PASS:
                    st.session_state.modo = "admin"
                    st.session_state.admin_ok = True
                    st.session_state.login_choice = None
                    st.session_state.login_error = ""
                    st.rerun()
                else:
                    st.session_state.admin_ok = False
                    st.session_state.login_error = "Contraseña incorrecta."

            if st.session_state.login_error:
                st.error(st.session_state.login_error)

        st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

# =========================
# SIDEBAR
# =========================
with st.sidebar:
    st.header("Panel")
    st.write(f"Modo: **{st.session_state.modo}**")

    if st.session_state.modo == "admin":
        if st.session_state.admin_ok:
            st.success("Administrador activo")
        else:
            st.warning("Admin no validado. Cambia modo y vuelve a entrar.")
    else:
        st.info("Invitado: solo lectura.")

    st.divider()
    if st.button("Cambiar modo / salir", use_container_width=True):
        st.session_state.modo = None
        st.session_state.admin_ok = False
        st.session_state.login_choice = None
        st.session_state.login_error = ""
        st.rerun()

# =========================
# ADMIN: CARGA MULTIPLE + PDF
# =========================
if st.session_state.modo == "admin" and st.session_state.admin_ok:
    st.markdown('<div class="tng-card">', unsafe_allow_html=True)
    st.subheader("Cargar proyectos (múltiples)")
    st.caption("Selecciona varios archivos .xlsx para actualizar proyectos (se reemplaza por nombre de proyecto).")

    excel_files = st.file_uploader("Subir Excel (.xlsx)", type=["xlsx"], accept_multiple_files=True)

    colx1, colx2 = st.columns([1, 1])
    with colx1:
        do_replace = st.checkbox("Actualizar/Reemplazar si ya existe", value=True)
    with colx2:
        do_dedup = st.checkbox("Eliminar duplicados dentro del proyecto", value=True)

    if st.button("Procesar y guardar", type="primary"):
        if not excel_files:
            st.warning("Selecciona al menos un archivo Excel.")
        else:
            ok, errores = 0, 0
            for f in excel_files:
                try:
                    data = f.getvalue()
                    nombre = leer_nombre_proyecto_excel(data)
                    df = leer_tabla_excel(data)
                    df = filtrar_servicios(df)  # <-- SERVICIO/SERVICIOS fuera desde carga
                    resumen = procesar_resumen(df)

                    nuevo = {
                        "id": f"proj_{dt.datetime.now().timestamp()}",
                        "nombre": nombre,
                        "fecha_carga": dt.datetime.now().isoformat(timespec="seconds"),
                        "archivo": f.name,
                        "resumen": resumen
                    }

                    if do_replace:
                        st.session_state.proyectos = upsert_proyecto(st.session_state.proyectos, nuevo)
                    else:
                        st.session_state.proyectos.append(nuevo)
                    ok += 1
                except Exception as e:
                    errores += 1
                    st.error(f"Error en {getattr(f,'name','archivo')}: {e}")

            if do_dedup:
                for p in st.session_state.proyectos:
                    items = p.get("resumen", {}).get("items", [])
                    p["resumen"]["items"] = dedup_items_por_clave(items, keys=["no_sc", "descripcion", "no_oc"])

            guardar_datos(st.session_state.proyectos)
            st.success(f"Procesados: {ok}. Errores: {errores}.")
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)
    st.write("")

    st.markdown('<div class="tng-card">', unsafe_allow_html=True)
    st.subheader("📄 Subir PDF")
    st.caption("Sube un PDF para que esté disponible para todos (admin + invitados).")

    pdf_file = st.file_uploader("Subir PDF", type=["pdf"], key="pdf_uploader")
    if pdf_file:
        safe_name = pdf_file.name.replace(" ", "_")
        path = os.path.join(PDF_DIR, safe_name)
        with open(path, "wb") as out:
            out.write(pdf_file.getbuffer())
        st.success(f"PDF guardado: {safe_name}")

    st.markdown("</div>", unsafe_allow_html=True)
    st.write("")

# =========================
# DASHBOARD
# =========================
if not st.session_state.proyectos:
    st.info("No hay proyectos cargados todavía.")
    st.stop()

nombres = sorted([p["nombre"] for p in st.session_state.proyectos])
seleccion = st.selectbox("Selecciona un proyecto", nombres, key="select_proyecto")

proyecto = next((p for p in st.session_state.proyectos if p["nombre"] == seleccion), None)
if not proyecto:
    st.warning("Proyecto no encontrado.")
    st.stop()

r = proyecto["resumen"]

# Limpieza por si BD vieja trae SERVICIO/SERVICIOS
r["items"] = filtrar_items_servicios(r.get("items", []))

# Recalcular si faltan campos (BD vieja) usando items ya limpios
items_bd = r.get("items", [])
if ("conteo_general" not in r) or (not isinstance(r.get("conteo_general", None), dict)) or ("trend" not in r):
    conteo_general_tmp, trend_tmp = construir_conteo_general_y_trend_desde_items(items_bd)
    r["conteo_general"] = conteo_general_tmp
    r["trend"] = trend_tmp
if "sin_oc_real" not in r:
    r["sin_oc_real"] = int(pd.Series([x.get("no_oc", None) for x in items_bd]).apply(is_empty_oc).sum()) if items_bd else 0

st.markdown('<div class="tng-card">', unsafe_allow_html=True)
st.subheader(f"Proyecto: {proyecto['nombre']}")
st.markdown(
    f"<div style='font-size:.9rem;'>Última carga: {proyecto.get('fecha_carga','-')} | Archivo: {proyecto.get('archivo','-')}</div>",
    unsafe_allow_html=True
)
st.markdown("</div>", unsafe_allow_html=True)
st.write("")

# KPIs
k1, k2, k3, k4 = st.columns(4)
total_partidas = r.get("total_registros", 0)
conteo_general = r.get("conteo_general", {}) or {}
completados = int(conteo_general.get("COMPLETADO", 0))
sin_oc_real = int(r.get("sin_oc_real", 0))
avance_pct = (completados * 100.0 / total_partidas) if total_partidas else 0.0

with k1:
    kpi_card("Items Solicitados", f"{total_partidas:,}", "Total de partidas", tone="accent")
with k2:
    kpi_card("Completados", f"{completados:,}", "General (OC/SC)", tone="ok")
with k3:
    kpi_card("Items sin OC", f"{sin_oc_real:,}", "No. O.C. vacío/NaN", tone="warn")
with k4:
    kpi_card("Avance", f"{avance_pct:.1f}%", "Completados / total", tone="ok" if avance_pct >= 75 else "warn")

st.write("")

# Gráficas
g1, g2 = st.columns([2, 1])
with g1:
    st.markdown('<div class="tng-card">', unsafe_allow_html=True)
    tendencia_semanal(r.get("trend", []), "Tendencia semanal de solicitudes")
    st.markdown('</div>', unsafe_allow_html=True)

with g2:
    st.markdown('<div class="tng-card">', unsafe_allow_html=True)
    donut_general(conteo_general, "Estado actual")
    st.markdown('</div>', unsafe_allow_html=True)

# =========================
# TABLA CRÍTICOS (SIN FILTROS) - ESTILO CLARO
# =========================
st.write("")
st.subheader("📋 Gestión de Pedidos (Items Críticos)")

crit = r.get("criticos", [])
if crit:
    dfc = pd.DataFrame(crit).copy()

    if "Prometida" in dfc.columns and "Fecha prometida" not in dfc.columns:
        dfc = dfc.rename(columns={"Prometida": "Fecha prometida"})

    dfc["Fecha_prometida_dt"] = pd.to_datetime(dfc.get("Fecha prometida", None), format="%d/%m/%Y", errors="coerce")
    dfc["Dias"] = dfc["Fecha_prometida_dt"].apply(dias_restantes)

    def calc_avance(dias, est_sc, est_oc):
        est_sc = str(est_sc).strip().upper()
        est_oc = str(est_oc).strip().upper()

        if est_sc == "COMPLETADO" and est_oc == "COMPLETADO":
            return 100, "Completado"
        if est_sc == "CANCELADO" or est_oc == "CANCELADO":
            return 0, "Cancelado"
        if dias is None:
            return 5, "Sin fecha"
        if dias < 0:
            return 0, f"Vencido {abs(dias)} días"

        maxwin = 30
        pct = int(max(0, min(100, (maxwin - min(dias, maxwin)) * 100 / maxwin)))
        return pct, f"{dias} días restantes"

    dfc[["Avance %", "Detalle avance"]] = dfc.apply(
        lambda x: pd.Series(calc_avance(x.get("Dias"), x.get("Estatus S.C."), x.get("Estatus O.C."))),
        axis=1
    )

    cols_show = ["No. S.C.", "Título", "Estatus S.C.", "Estatus O.C.", "Fecha prometida", "Avance %", "Detalle avance"]
    dfc = dfc[cols_show].copy()

    st.dataframe(
        style_light_table(dfc),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Avance %": st.column_config.ProgressColumn("Avance", min_value=0, max_value=100, format="%d%%"),
        },
    )
else:
    st.success("✅ Sin materiales críticos con la lógica actual.")

# =========================
# TABLA COMPLETA (SIN FILTROS) - ESTILO CLARO
# =========================
with st.expander("Ver tabla completa del proyecto"):
    items = filtrar_items_servicios(r.get("items", []))
    if not items:
        st.info("No hay items guardados en este proyecto.")
    else:
        dfi = pd.DataFrame(items).copy()

        dfi["No. S.C."] = dfi.get("no_sc", "")
        dfi["Título"] = dfi.get("titulo", "")
        dfi["Descripción"] = dfi.get("descripcion", "")
        dfi["No. O.C."] = dfi.get("no_oc", "")
        dfi["Estatus S.C."] = dfi.get("estatus_sc", "")
        dfi["Estatus O.C."] = dfi.get("estatus_oc", "")
        dfi["Fecha prometida"] = pd.to_datetime(dfi.get("fecha_prometida", ""), errors="coerce")
        dfi["Fecha llegada"] = pd.to_datetime(dfi.get("fecha_llegada", ""), errors="coerce")

        show = dfi[[
            "No. S.C.", "Título", "Descripción", "No. O.C.",
            "Estatus S.C.", "Estatus O.C.", "Fecha prometida", "Fecha llegada"
        ]].copy()

        st.dataframe(style_light_table(show), use_container_width=True, hide_index=True)

# =========================
# DESCARGA DE NOTAS (PDF) - TODOS
# =========================
st.write("")
st.subheader("📥 Notas Descargables")

pdfs = [f for f in os.listdir(PDF_DIR) if f.lower().endswith(".pdf")]
if pdfs:
    st.markdown('<div class="tng-card">', unsafe_allow_html=True)
    st.caption("Haz clic en el botón para descargar las notas del proyecto.")
    for pdf_name in pdfs:
        path = os.path.join(PDF_DIR, pdf_name)
        with open(path, "rb") as f:
            pdf_bytes = f.read()
        st.download_button(
            label=f"📄 Descargar {pdf_name}",
            data=pdf_bytes,
            file_name=pdf_name,
            mime="application/pdf",
            key=f"download_{pdf_name}"
        )
    st.markdown('</div>', unsafe_allow_html=True)
else:
    st.info("No hay PDFs disponibles. El administrador puede subirlos en su panel.")
