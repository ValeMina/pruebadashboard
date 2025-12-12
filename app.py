import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# Configuración de la página
st.set_page_config(page_title="Dashboard de Materiales - Astillero", layout="wide")

st.title("🚢 Dashboard de Control de Materiales y Logística")
st.markdown("""
Esta herramienta compara el **Control de Materiales (Solicitado)** contra las **Entradas y Salidas (Almacén)** para identificar faltantes, excedentes y el estatus real del suministro.
""")

# --- SECCIÓN DE CARGA DE ARCHIVOS ---
st.sidebar.header("📥 Cargar Documentos")
uploaded_control = st.sidebar.file_uploader("1. Cargar 'Control de Materiales' (Excel/CSV)", type=["xlsx", "csv"])
uploaded_transacciones = st.sidebar.file_uploader("2. Cargar 'Entradas y Salidas' (Excel/CSV)", type=["xlsx", "csv"])

# --- FUNCIONES DE LIMPIEZA Y CARGA ---
@st.cache_data
def load_control_data(file):
    try:
        # 1. Leemos el archivo sin encabezado primero para inspeccionar
        if file.name.endswith('.csv'):
            df_raw = pd.read_csv(file, header=None)
        else:
            df_raw = pd.read_excel(file, header=None)
        
        # 2. Buscamos automáticamente en qué fila está la columna "CODIGO DE PIEZA"
        header_row_index = None
        for i, row in df_raw.iterrows():
            # Convertimos la fila a texto y buscamos la palabra clave
            row_str = row.astype(str).str.upper().str.strip()
            if row_str.str.contains('CODIGO DE PIEZA').any() or row_str.str.contains('CÓDIGO DE PIEZA').any():
                header_row_index = i
                break
        
        if header_row_index is None:
            st.error("Error Crítico: No se encontró la fila de encabezados que contenga 'CODIGO DE PIEZA'. Verifica el archivo.")
            return None

        # 3. Recargamos el archivo usando la fila encontrada como encabezado
        if file.name.endswith('.csv'):
            df = pd.read_csv(file, header=header_row_index)
        else:
            df = pd.read_excel(file, header=header_row_index)
            
        # Normalizar nombres de columnas
        df.columns = df.columns.str.strip().str.upper()
        
        # Verificar nuevamente por seguridad
        if 'CODIGO DE PIEZA' not in df.columns:
            st.error(f"Error: Se detectó el encabezado en la fila {header_row_index}, pero la columna no se llama exactamente 'CODIGO DE PIEZA'. Columnas encontradas: {list(df.columns)}")
            return None
            
        # Limpieza básica
        df = df.dropna(subset=['CODIGO DE PIEZA'])
        df['CANT ITEM S.C.'] = pd.to_numeric(df['CANT ITEM S.C.'], errors='coerce').fillna(0)
        
        # Agrupar por código
        df_grouped = df.groupby('CODIGO DE PIEZA').agg({
            'DESCRIPCION DE LA PARTIDA': 'first',
            'CANT ITEM S.C.': 'sum'
        }).reset_index()
        
        return df_grouped

    except Exception as e:
        st.error(f"Error al procesar Control de Materiales: {e}")
        return None
            
        # Limpieza básica
        df = df.dropna(subset=['CODIGO DE PIEZA'])
        # Convertir cantidades a numérico
        df['CANT ITEM S.C.'] = pd.to_numeric(df['CANT ITEM S.C.'], errors='coerce').fillna(0)
        
        # Agrupar por código (por si hay múltiples líneas del mismo material)
        df_grouped = df.groupby('CODIGO DE PIEZA').agg({
            'DESCRIPCION DE LA PARTIDA': 'first', # Tomamos la primera descripción
            'CANT ITEM S.C.': 'sum'
        }).reset_index()
        
        return df_grouped
    except Exception as e:
        st.error(f"Error al procesar Control de Materiales: {e}")
        return None

@st.cache_data
def load_transacciones_data(file):
    try:
        if file.name.endswith('.csv'):
            df = pd.read_csv(file)
        else:
            df = pd.read_excel(file)
            
        df.columns = df.columns.str.strip().str.upper()
        
        # Verificar columnas
        required_cols = ['PIEZA', 'CANTIDAD', 'TRANSACCION']
        if not all(col in df.columns for col in required_cols):
            st.error(f"Error: Faltan columnas requeridas en Entradas/Salidas ({required_cols})")
            return None

        # Estandarizar transacciones
        df['TRANSACCION'] = df['TRANSACCION'].str.upper().str.strip()
        df['CANTIDAD'] = pd.to_numeric(df['CANTIDAD'], errors='coerce').fillna(0)
        
        # Pivotar para obtener Recepciones y Despachos por pieza
        pivot = df.pivot_table(
            index='PIEZA', 
            columns='TRANSACCION', 
            values='CANTIDAD', 
            aggfunc='sum', 
            fill_value=0
        ).reset_index()
        
        # Asegurar que existan las columnas aunque no haya datos
        if 'RECEPCIONES' not in pivot.columns: pivot['RECEPCIONES'] = 0
        if 'DESPACHOS' not in pivot.columns: pivot['DESPACHOS'] = 0
        
        return pivot
    except Exception as e:
        st.error(f"Error al procesar Entradas y Salidas: {e}")
        return None

# --- LÓGICA PRINCIPAL ---
if uploaded_control and uploaded_transacciones:
    
    # 1. Cargar Datos
    df_control = load_control_data(uploaded_control)
    df_trans = load_transacciones_data(uploaded_transacciones)

    if df_control is not None and df_trans is not None:
        
        # 2. Unir DataFrames (Merge)
        # Usamos 'left' para mantener todo lo solicitado, aunque no tenga movimientos
        df_master = pd.merge(
            df_control, 
            df_trans, 
            left_on='CODIGO DE PIEZA', 
            right_on='PIEZA', 
            how='left'
        )
        
        # Llenar NaN con 0 en recepciones/despachos (para items que no han llegado)
        df_master['RECEPCIONES'] = df_master['RECEPCIONES'].fillna(0)
        df_master['DESPACHOS'] = df_master['DESPACHOS'].fillna(0)
        
        # 3. Cálculos de KPIs
        df_master['PENDIENTE POR RECIBIR'] = df_master['CANT ITEM S.C.'] - df_master['RECEPCIONES']
        df_master['STOCK EN ALMACEN'] = df_master['RECEPCIONES'] - df_master['DESPACHOS']
        
        # Renombrar para presentación
        df_final = df_master[[
            'CODIGO DE PIEZA', 'DESCRIPCION DE LA PARTIDA', 
            'CANT ITEM S.C.', 'RECEPCIONES', 'DESPACHOS', 
            'PENDIENTE POR RECIBIR', 'STOCK EN ALMACEN'
        ]].rename(columns={'CANT ITEM S.C.': 'SOLICITADO'})

        # --- DASHBOARD VISUAL ---
        
        # Métricas Globales (Top Metrics)
        col1, col2, col3, col4 = st.columns(4)
        total_solicitado = df_final['SOLICITADO'].sum()
        total_recibido = df_final['RECEPCIONES'].sum()
        total_despachado = df_final['DESPACHOS'].sum()
        avance_suministro = (total_recibido / total_solicitado * 100) if total_solicitado > 0 else 0

        col1.metric("Total Items Solicitados", f"{total_solicitado:,.0f}")
        col2.metric("Total Recibidos", f"{total_recibido:,.0f}")
        col3.metric("Total Despachados", f"{total_despachado:,.0f}")
        col4.metric("Avance Suministro", f"{avance_suministro:.1f}%")

        st.markdown("---")

        # Filtros Interactivos
        st.subheader("🔍 Análisis Detallado")
        
        filtro_status = st.multiselect(
            "Filtrar por Estatus:",
            ["Completo (Recibido >= Solicitado)", "Incompleto (Faltante)", "Sin Movimiento", "Crítico (Solicitado pero nada recibido)"],
            default=["Incompleto (Faltante)", "Crítico (Solicitado pero nada recibido)"]
        )
        
        # Lógica de filtrado
        df_view = df_final.copy()
        conditions = []
        if "Completo (Recibido >= Solicitado)" in filtro_status:
            conditions.append(df_view['RECEPCIONES'] >= df_view['SOLICITADO'])
        if "Incompleto (Faltante)" in filtro_status:
            conditions.append((df_view['RECEPCIONES'] < df_view['SOLICITADO']) & (df_view['RECEPCIONES'] > 0))
        if "Sin Movimiento" in filtro_status:
            conditions.append((df_view['RECEPCIONES'] == 0) & (df_view['DESPACHOS'] == 0))
        if "Crítico (Solicitado pero nada recibido)" in filtro_status:
            conditions.append((df_view['SOLICITADO'] > 0) & (df_view['RECEPCIONES'] == 0))
            
        if conditions:
            # Combinar condiciones con OR lógico
            final_condition = conditions[0]
            for c in conditions[1:]:
                final_condition = final_condition | c
            df_view = df_view[final_condition]

        # Tabla Interactiva
        st.dataframe(
            df_view.style.background_gradient(subset=['PENDIENTE POR RECIBIR'], cmap='Reds'),
            use_container_width=True
        )

        # Gráfico Comparativo
        st.subheader("📊 Comparativa Visual (Top 20 Items Filtrados)")
        if not df_view.empty:
            # Limitar a top 20 para que el gráfico sea legible
            df_chart = df_view.head(20)
            
            fig = go.Figure()
            fig.add_trace(go.Bar(name='Solicitado', x=df_chart['CODIGO DE PIEZA'], y=df_chart['SOLICITADO'], marker_color='blue'))
            fig.add_trace(go.Bar(name='Recibido', x=df_chart['CODIGO DE PIEZA'], y=df_chart['RECEPCIONES'], marker_color='green'))
            fig.add_trace(go.Bar(name='Despachado', x=df_chart['CODIGO DE PIEZA'], y=df_chart['DESPACHOS'], marker_color='orange'))
            
            fig.update_layout(barmode='group', title="Solicitado vs Recibido vs Despachado")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No hay datos para mostrar con los filtros seleccionados.")

        # Botón de Descarga
        csv = df_final.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="💾 Descargar Reporte Consolidado (CSV)",
            data=csv,
            file_name='reporte_consolidado_materiales.csv',
            mime='text/csv',
        )

else:
    st.info("👋 Esperando archivos. Por favor carga el 'Control de Materiales' y 'Entradas y Salidas' en el panel lateral.")

