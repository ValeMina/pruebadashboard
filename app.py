import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(
    page_title="Tablero de Control Logístico - Naval",
    page_icon="⚓",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- ESTILOS CSS PERSONALIZADOS ---
st.markdown("""
    <style>
    .big-font { font-size:20px !important; font-weight: bold; }
    .metric-card { background-color: #f0f2f6; padding: 15px; border-radius: 10px; border-left: 5px solid #1f77b4; }
    </style>
    """, unsafe_allow_html=True)

# --- FUNCIONES DE CARGA Y LIMPIEZA ---
@st.cache_data
def load_data(uploaded_file):
    try:
        # Intentamos leer buscando el encabezado correcto. 
        # En tu archivo, los encabezados reales parecen empezar donde está "No. S.C."
        df = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
        
        # Búsqueda dinámica del encabezado si el archivo tiene filas vacías al inicio
        if 'No. S.C.' not in df.columns:
            # Buscar en las primeras 10 filas dónde está el encabezado
            for i in range(10):
                df_temp = pd.read_csv(uploaded_file, header=i) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file, header=i)
                if 'No. S.C.' in df_temp.columns:
                    df = df_temp
                    break
        
        # Limpieza de fechas
        date_cols = ['FECHA PROMETIDA', 'FECHA DE LLEGADA', 'FECHA REP MCC']
        for col in date_cols:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce')

        return df
    except Exception as e:
        st.error(f"Error al procesar el archivo: {e}")
        return None

# --- SIDEBAR: ADMINISTRADOR ---
with st.sidebar:
    st.image("https://img.icons8.com/ios-filled/100/1f77b4/cargo-ship.png", width=50)
    st.title("Admin Panel")
    
    # Simulación de Login Simple
    password = st.text_input("Contraseña de Admin", type="password")
    
    uploaded_file = None
    if password == "admin123":  # Contraseña ejemplo
        st.success("Acceso Concedido")
        st.markdown("---")
        st.subheader("📂 Cargar Control de Materiales")
        uploaded_file = st.file_uploader("Sube tu Excel o CSV aquí", type=['xlsx', 'csv'])
    elif password:
        st.error("Contraseña incorrecta")
    else:
        st.info("Ingresa la contraseña para cargar datos.")

    st.markdown("---")
    st.caption("Sistema de Gestión de Astillero v2.0")

# --- ÁREA PRINCIPAL ---

if uploaded_file is not None:
    df = load_data(uploaded_file)
    
    if df is not None:
        # --- PROCESAMIENTO DE KPIS ---
        # Filtros básicos derivados de tu archivo
        total_items = len(df)
        recibidos = df[df['ESTATUS GRN'] == 'RECV'].shape[0]
        cancelados = df[df['ESTATUS O.C.'] == 'CANCELADA'].shape[0] # Ajustado según tu data
        pendientes = total_items - recibidos - cancelados
        pct_avance = (recibidos / (total_items - cancelados)) * 100 if (total_items - cancelados) > 0 else 0
        
        # Cálculo de Tiempos (Días de Retraso)
        if 'FECHA PROMETIDA' in df.columns and 'FECHA DE LLEGADA' in df.columns:
            df['Dias_Retraso'] = (df['FECHA DE LLEGADA'] - df['FECHA PROMETIDA']).dt.days
            # Consideramos "A tiempo" si llegó antes o el mismo día (<= 0)
            a_tiempo = df[df['Dias_Retraso'] <= 0].shape[0]
            con_retraso = df[df['Dias_Retraso'] > 0].shape[0]
            # Solo consideramos items que ya llegaron para el KPI de eficiencia
            items_con_fecha = df.dropna(subset=['FECHA DE LLEGADA'])
            otd_rate = (a_tiempo / len(items_con_fecha)) * 100 if len(items_con_fecha) > 0 else 0
        
        st.title(f"⚓ Dashboard Ejecutivo: {df['NOMBRE DEL PROYECTO'].iloc[0] if 'NOMBRE DEL PROYECTO' in df.columns else 'Control de Materiales'}")
        st.markdown("Vista de alto nivel del estatus de la cadena de suministro.")

        # --- FILA 1: METRICAS CLAVE (KPIs) ---
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric(label="Total Solicitudes (Items)", value=total_items)
        with col2:
            st.metric(label="Material Recibido", value=recibidos, delta=f"{pct_avance:.1f}% Completado")
        with col3:
            st.metric(label="Eficiencia Entrega (OTD)", value=f"{otd_rate:.1f}%", delta_color="inverse" if otd_rate < 80 else "normal")
        with col4:
            st.metric(label="Pendientes Críticos", value=pendientes, delta_color="off")

        st.markdown("---")

        # --- TABS PARA VISTAS DETALLADAS ---
        tab1, tab2, tab3 = st.tabs(["📊 Análisis Gráfico", "⏱️ Tiempos de Entrega", "📋 Base de Datos"])

        with tab1:
            c1, c2 = st.columns(2)
            
            with c1:
                st.subheader("Estatus de Materiales")
                # Gráfico de Dona para Estatus
                status_counts = df['ESTATUS GRN'].fillna('PENDIENTE').value_counts().reset_index()
                status_counts.columns = ['Estatus', 'Cantidad']
                fig_pie = px.pie(status_counts, values='Cantidad', names='Estatus', hole=0.4, 
                                 color_discrete_sequence=px.colors.sequential.RdBu)
                st.plotly_chart(fig_pie, use_container_width=True)

            with c2:
                st.subheader("Top Materiales Solicitados")
                # Extraemos palabras clave o usamos la descripción
                if 'DESCRIPCION DE LA PARTIDA' in df.columns:
                    # Contamos frecuencia de descripciones
                    top_mats = df['DESCRIPCION DE LA PARTIDA'].value_counts().head(10).sort_values(ascending=True)
                    fig_bar = px.bar(top_mats, orientation='h', title="Top 10 Items más frecuentes")
                    fig_bar.update_layout(xaxis_title="Cantidad", yaxis_title="Material")
                    st.plotly_chart(fig_bar, use_container_width=True)

        with tab2:
            st.subheader("Análisis de Cumplimiento de Fechas")
            
            if 'FECHA PROMETIDA' in df.columns and 'FECHA DE LLEGADA' in df.columns:
                # Scatter plot comparativo
                df_dates = df.dropna(subset=['FECHA PROMETIDA', 'FECHA DE LLEGADA']).copy()
                fig_scatter = px.scatter(df_dates, x='FECHA PROMETIDA', y='FECHA DE LLEGADA', 
                                         color='Dias_Retraso',
                                         hover_data=['DESCRIPCION DE LA PARTIDA', 'No. S.C.'],
                                         title="Fecha Prometida vs. Fecha Real de Llegada",
                                         labels={'Dias_Retraso': 'Días de Retraso'},
                                         color_continuous_scale='RdYlGn_r') # Verde bueno, Rojo retraso
                
                # Línea de referencia (lo ideal es x=y)
                fig_scatter.add_shape(type="line",
                    x0=df_dates['FECHA PROMETIDA'].min(), y0=df_dates['FECHA PROMETIDA'].min(),
                    x1=df_dates['FECHA PROMETIDA'].max(), y1=df_dates['FECHA PROMETIDA'].max(),
                    line=dict(color="Gray", width=2, dash="dash"),
                )
                st.plotly_chart(fig_scatter, use_container_width=True)
                
                st.info("💡 Nota: Los puntos por encima de la línea punteada representan entregas tardías. El color indica la gravedad del retraso.")

        with tab3:
            st.subheader("Detalle de Registros")
            # Filtros interactivos simples
            search = st.text_input("🔍 Buscar por descripción o código de pieza:")
            
            df_display = df.copy()
            if search:
                df_display = df_display[df_display.apply(lambda row: row.astype(str).str.contains(search, case=False).any(), axis=1)]
            
            st.dataframe(df_display, use_container_width=True)

else:
    # Pantalla de bienvenida cuando no hay archivo
    st.markdown("""
    <div style='text-align: center; padding: 50px;'>
        <h1>Bienvenido al Sistema de Control Logístico</h1>
        <p>Por favor, ingrese como administrador en el menú lateral para cargar el archivo de control de materiales.</p>
        <p style='color: gray;'>Esperando carga de datos...</p>
    </div>
    """, unsafe_allow_html=True)
