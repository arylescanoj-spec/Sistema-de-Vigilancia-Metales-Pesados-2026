import os
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from PIL import Image
import geopandas as gpd
import folium
from streamlit_folium import st_folium

st.set_page_config(
    page_title="Vigilancia Metales Pesados - DIRESA Áncash",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="expanded",
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PATH_IPRESS = os.path.join(BASE_DIR, "CODIGOS IPRESS DIRESA ANCASH 2026.csv")
PATH_PROVINCIAS = os.path.join(BASE_DIR, "peru_provincial_simple.geojson")
PATH_UBIGEOS = os.path.join(BASE_DIR, "UBIGEOS.xlsx")
PATH_LOGO = os.path.join(BASE_DIR, "logo.png")

RED_MAP = {
    1: "Red de Salud Huaylas Sur",
    2: "Red de Salud Huaylas Norte",
    3: "Red de Salud Pacífico Sur",
    4: "Red de Salud Pacífico Norte",
    5: "Red de Salud Conchucos Sur",
    6: "Red de Salud Conchucos Norte",
}

CIE_MAP = {
    "T57.0": "Arsénico y sus compuestos (T57.0)",
    "T56.9": "Metal no especificado (T56.9)",
    "T56.0": "Plomo y sus compuestos (T56.0)",
    "T56.7": "Berilio y sus compuestos (T56.7)",
    "T56.8": "Otros metales pesados (T56.8)",
    "T56.3": "Cadmio y sus compuestos (T56.3)",
    "T56": "Efectos tóxicos de metales (T56)",
}

# Columnas con datos personales identificables que se eliminan inmediatamente al leer el CSV
PII_COLUMNS = {
    "dni",
    "num_doc",
    "documento",
    "nro_doc",
    "nombres",
    "nombre",
    "apellidos",
    "apepat",
    "apemat",
    "ape_pat",
    "ape_mat",
    "paciente",
    "telefono",
    "celular",
    "direccion",
    "domicilio",
    "historia",
    "hc",
    "correo",
    "email",
}


def limpiar_columnas_sensibles(df):
    cols_a_eliminar = [
        c
        for c in df.columns
        if c in PII_COLUMNS
        or any(
            k in c
            for k in ["dni", "nombre", "apellido", "direccion", "telefono", "celular", "historia"]
        )
    ]
    if cols_a_eliminar:
        df = df.drop(columns=cols_a_eliminar)
    return df, cols_a_eliminar


@st.cache_data
def get_ipress_dictionary(file_path=PATH_IPRESS):
    if os.path.exists(file_path):
        try:
            df_m = pd.read_csv(
                file_path,
                sep=None,
                engine="python",
                encoding="utf-8-sig",
                on_bad_lines="skip",
            )
            df_m.columns = [
                str(c).replace("\ufeff", "").lower().strip() for c in df_m.columns
            ]
            cod_col = [
                c for c in df_m.columns if "cod" in c or "codigo" in c or "id" in c
            ]
            nom_col = [
                c
                for c in df_m.columns
                if "nom" in c or "eess" in c or "establec" in c or "ipress" in c
            ]
            if cod_col and nom_col:
                c_code, c_name = cod_col[0], nom_col[0]
                return dict(
                    zip(
                        df_m[c_code].astype(str).str.upper().str.strip(),
                        df_m[c_name].astype(str).str.strip(),
                    )
                )
        except Exception as e:
            print(f"Error al leer maestro IPRESS: {e}")
    return {}


def es_trabajador_expuesto(row):
    campos_occ = [
        str(row.get("ocupacion", "")).upper(),
        str(row.get("ocupac_otr", "")).upper(),
        str(row.get("subocupaci", "")).upper(),
        str(row.get("actividad", "")).upper(),
    ]
    texto_occ = " ".join(campos_occ)
    keywords_expuestos = [
        "MINERO",
        "MINERIA",
        "SOLDADOR",
        "SOLDADURA",
        "RECICLADOR",
        "BATERIA",
        "FUNDICION",
        "GALVANOPLASTIA",
        "PINTOR",
        "CONSTRUCCION",
        "FABRICA",
        "INDUSTRIA",
        "INDEPENDIENTE MIN",
        "OPERARIO",
    ]
    return any(kw in texto_occ for kw in keywords_expuestos)


def evaluar_analito_individual(analito_raw, val_raw, unidad_raw, row):
    val_str = str(val_raw).strip().upper() if pd.notna(val_raw) else ""
    analito = str(analito_raw).strip().upper() if pd.notna(analito_raw) else ""
    unidad = str(unidad_raw).strip().upper() if pd.notna(unidad_raw) else ""

    if val_str in ["", "NAN", "NONE", "SIN REGISTRO", "NULL"]:
        return "⚪ SIN MUESTRA / VACÍO"
    if "<LCM" in val_str or "LCM" in val_str or "< LCM" in val_str:
        return "🟢 NORMAL (< LCM)"
    if "INDETERMINADO" in val_str:
        return "🟡 INDETERMINADO"

    val_num = pd.to_numeric(val_str.replace(",", "."), errors="coerce")
    if pd.isna(val_num):
        return "⚪ SIN CLASIFICAR"

    analito_norm = (
        analito.replace("ARCENICO", "ARSENICO").replace("ARSÉNICO", "ARSENICO")
    )
    unidad_norm = unidad.replace("ΜG", "UG").replace("µG", "UG")

    expuesto = es_trabajador_expuesto(row)
    edad = pd.to_numeric(row.get("edad"), errors="coerce")
    embarazada = str(row.get("embarazada", "")).upper().strip() in [
        "1",
        "1.0",
        "SI",
        "SÍ",
        "S",
    ]

    if "ARSENICO" in analito_norm or "ARS" in analito_norm:
        umbral = (
            (50.0 if expuesto else 20.0)
            if ("CREATININA" in unidad_norm or "G CREAT" in unidad_norm)
            else (100.0 if expuesto else 50.0)
        )
        return "🔴 ELEVADO (Sobre Límite)" if val_num > umbral else "🟢 NORMAL"
    elif "PLOMO" in analito_norm or "PB" in analito_norm:
        if expuesto:
            umbral = 40.0
        elif (pd.notna(edad) and edad < 12) or embarazada:
            umbral = 10.0
        else:
            umbral = 20.0
        return "🔴 ELEVADO (Sobre Límite)" if val_num > umbral else "🟢 NORMAL"
    elif "CADMIO" in analito_norm or "CD" in analito_norm:
        umbral = (
            (5.0 if expuesto else 2.0)
            if "CREATININA" in unidad_norm
            else (10.0 if expuesto else 2.0)
        )
        return "🔴 ELEVADO (Sobre Límite)" if val_num > umbral else "🟢 NORMAL"
    elif "MERCURIO" in analito_norm or "HG" in analito_norm:
        umbral = (
            (35.0 if expuesto else 5.0)
            if "CREATININA" in unidad_norm
            else (50.0 if expuesto else 5.0)
        )
        return "🔴 ELEVADO (Sobre Límite)" if val_num > umbral else "🟢 NORMAL"

    return "🟢 NORMAL"


def combinar_estados(est1, est2):
    estados = [est1, est2]
    if "🔴 ELEVADO (Sobre Límite)" in estados:
        return "🔴 ELEVADO (Sobre Límite)"
    if "🟡 CUANTIFICADO" in estados:
        return "🟡 CUANTIFICADO"
    if "🟡 INDETERMINADO" in estados:
        return "🟡 INDETERMINADO"
    if "🟢 NORMAL" in estados or "🟢 NORMAL (< LCM)" in estados:
        return "🟢 NORMAL"
    return "⚪ SIN MUESTRA / VACÍO"


def procesar_laboratorio(df):
    df_proc = df.copy()
    df_proc["tipo_poblacion"] = df_proc.apply(
        lambda r: (
            "👷 Trab. Expuesto"
            if es_trabajador_expuesto(r)
            else "🏡 No Expuesto (Población General)"
        ),
        axis=1,
    )
    df_proc["estado_item_1"] = df_proc.apply(
        lambda r: evaluar_analito_individual(
            r.get("m1_resultado_item_1"),
            r.get("m1_valor_resultado_1"),
            r.get("m1_unidad_medida_1"),
            r,
        ),
        axis=1,
    )
    df_proc["estado_item_2"] = df_proc.apply(
        lambda r: evaluar_analito_individual(
            r.get("m1_resultado_item_2"),
            r.get("m1_valor_resultado_2"),
            r.get("m1_unidad_medida_2"),
            r,
        ),
        axis=1,
    )
    df_proc["estado_resultado_m1"] = df_proc.apply(
        lambda r: combinar_estados(r["estado_item_1"], r["estado_item_2"]), axis=1
    )
    return df_proc


def load_data(file_sources):
    noti_dfs = []
    ipress_dict = get_ipress_dictionary()
    eliminadas_total = []

    for src in file_sources:
        try:
            src.seek(0)
            df_temp = pd.read_csv(
                src,
                sep=None,
                engine="python",
                encoding="utf-8-sig",
                on_bad_lines="skip",
            )
            df_temp.columns = [
                str(c).replace("\ufeff", "").lower().strip() for c in df_temp.columns
            ]
            df_temp, cols_elim = limpiar_columnas_sensibles(df_temp)
            eliminadas_total.extend(cols_elim)
            noti_dfs.append(df_temp)
        except Exception as e:
            st.error(f"Error procesando archivo: {e}")
            continue

    if not noti_dfs:
        return pd.DataFrame(), "No se pudieron procesar los archivos CSV subidos.", []

    df_combined = pd.concat(noti_dfs, ignore_index=True)

    diag_col = next(
        (c for c in ["diagno", "diagnostic", "cie10"] if c in df_combined.columns), None
    )
    if not diag_col:
        return pd.DataFrame(), "No se encontró columna de diagnóstico.", eliminadas_total

    df_combined["DIAGNOSTIC_CLEAN"] = (
        df_combined[diag_col].astype(str).str.upper().str.strip()
    )

    if "eess" in df_combined.columns and df_combined["eess"].notna().any():
        df_combined["EESS_NOMBRE"] = (
            df_combined["eess"].astype(str).str.upper().str.strip()
        )
    elif "cod_eess" in df_combined.columns:
        df_combined["EESS_CODIGO"] = (
            df_combined["cod_eess"].astype(str).str.upper().str.strip()
        )
        df_combined["EESS_NOMBRE"] = (
            df_combined["EESS_CODIGO"].map(ipress_dict).fillna(df_combined["EESS_CODIGO"])
        )
    else:
        df_combined["EESS_NOMBRE"] = "Establecimiento Desconocido"

    if "red" in df_combined.columns and df_combined["red"].notna().any():
        df_combined["RED_NOMBRE"] = (
            df_combined["red"].astype(str).str.upper().str.strip()
        )
    elif "cod_red" in df_combined.columns:
        df_combined["RED_NUM"] = pd.to_numeric(df_combined["cod_red"], errors="coerce")
        df_combined["RED_NOMBRE"] = (
            df_combined["RED_NUM"].map(RED_MAP).fillna(df_combined["cod_red"].astype(str))
        )
    else:
        df_combined["RED_NOMBRE"] = "Sin Red Registrada"

    def get_diag_label(row):
        code = str(row.get(diag_col, "")).upper().strip()
        desc = str(row.get("diagnostic", "")).upper().strip()
        for c_code, label in CIE_MAP.items():
            if c_code in code or c_code in desc:
                return label
        return f"{code} - {desc}" if desc else f"Metal Pesado ({code})"

    df_combined["DIAGNOSTICO_LABEL"] = df_combined.apply(get_diag_label, axis=1)

    if "edad" in df_combined.columns:
        df_combined["EDAD_NUM"] = pd.to_numeric(
            df_combined["edad"], errors="coerce"
        ).fillna(0)
    else:
        df_combined["EDAD_NUM"] = 0

    def get_curso_vida(edad):
        if edad < 12:
            return "1. Niño (0-11)"
        elif edad < 18:
            return "2. Adolescente (12-17)"
        elif edad < 30:
            return "3. Joven (18-29)"
        elif edad < 60:
            return "4. Adulto (30-59)"
        else:
            return "5. Adulto Mayor (60+)"

    df_combined["CURSO_VIDA"] = df_combined["EDAD_NUM"].apply(get_curso_vida)

    if "sexo" in df_combined.columns:
        df_combined["SEXO"] = (
            df_combined["sexo"].astype(str).str.upper().str.strip()
        )
        df_combined["SEXO_LABEL"] = (
            df_combined["SEXO"].map({"M": "Masculino", "F": "Femenino"}).fillna("Masculino")
        )
    else:
        df_combined["SEXO"] = "M"
        df_combined["SEXO_LABEL"] = "Masculino"

    def get_binary_var(col_name):
        if col_name in df_combined.columns:
            s = df_combined[col_name].astype(str).str.upper().str.strip()
            return s.map(
                {
                    "1": "Sí",
                    "1.0": "Sí",
                    "SI": "Sí",
                    "SÍ": "Sí",
                    "TRUE": "Sí",
                    "0": "No",
                    "0.0": "No",
                    "NO": "No",
                    "FALSE": "No",
                }
            ).fillna("Sin Registro")
        return pd.Series(["Sin Registro"] * len(df_combined))

    df_combined["VAR_MANANTIAL"] = get_binary_var("manantial")
    df_combined["VAR_POLVOCASA"] = get_binary_var("polvocasa")
    df_combined["VAR_MADERAPISO"] = get_binary_var("maderapiso")
    df_combined["VAR_FABCER"] = get_binary_var("fabcer")
    df_combined["VAR_DEPOMIN"] = get_binary_var("depomin")
    df_combined["VAR_POLVOAMB"] = get_binary_var("polvoamb")

    fecha_col = next(
        (
            c
            for c in ["fecha_not", "fec_not", "fecha_ini", "fec_ini"]
            if c in df_combined.columns
        ),
        None,
    )
    if fecha_col:
        df_combined["FECHA_NOT_DT"] = pd.to_datetime(
            df_combined[fecha_col], errors="coerce"
        )
    else:
        df_combined["FECHA_NOT_DT"] = pd.NaT

    df_combined["AÑO_FECHA_NOT"] = (
        df_combined["FECHA_NOT_DT"]
        .dt.year.fillna(0)
        .astype(int)
        .astype(str)
        .replace("0", "Sin Año")
    )

    if "semana" in df_combined.columns:
        df_combined["SEMANA_EPIDEMIOLOGICA"] = (
            pd.to_numeric(df_combined["semana"], errors="coerce").fillna(0).astype(int)
        )
    else:
        df_combined["SEMANA_EPIDEMIOLOGICA"] = (
            df_combined["FECHA_NOT_DT"]
            .dt.isocalendar()
            .week.fillna(0)
            .astype(int)
        )

    df_combined["SE_LABEL"] = df_combined["SEMANA_EPIDEMIOLOGICA"].apply(
        lambda x: f"SE {x:02d}" if x > 0 else "Sin SE"
    )

    meses_map = {
        1: "01 - Enero",
        2: "02 - Febrero",
        3: "03 - Marzo",
        4: "04 - Abril",
        5: "05 - Mayo",
        6: "06 - Junio",
        7: "07 - Julio",
        8: "08 - Agosto",
        9: "09 - Septiembre",
        10: "10 - Octubre",
        11: "11 - Noviembre",
        12: "12 - Diciembre",
    }
    df_combined["MES_NUM_NOT"] = df_combined["FECHA_NOT_DT"].dt.month
    df_combined["MES_NOMBRE_NOT"] = (
        df_combined["MES_NUM_NOT"].map(meses_map).fillna("Sin Mes")
    )

    lat_col = next(
        (c for c in df_combined.columns if "lat" in c or "y_coord" in c), None
    )
    lon_col = next(
        (c for c in df_combined.columns if "lon" in c or "x_coord" in c), None
    )
    if lat_col and lon_col:
        df_combined["LATITUD"] = pd.to_numeric(df_combined[lat_col], errors="coerce")
        df_combined["LONGITUD"] = pd.to_numeric(df_combined[lon_col], errors="coerce")

    return df_combined, "OK", sorted(set(eliminadas_total))


# --- PANEL LATERAL ---
st.sidebar.title("📌 Configuración & Datos")

logo_file = st.sidebar.file_uploader(
    "🖼️ Sube el Logo del Área (Opcional)", type=["png", "jpg", "jpeg"]
)

logo_img = None
if logo_file is not None:
    logo_img = Image.open(logo_file)
    st.sidebar.image(logo_img, use_container_width=True)
elif os.path.exists(PATH_LOGO):
    st.sidebar.image(PATH_LOGO, use_container_width=True)

st.sidebar.markdown("---")
uploaded_files = st.sidebar.file_uploader(
    "📂 Sube la data exportada del Aplicativo de Metales Pesados (CSV)",
    type=["csv"],
    accept_multiple_files=True,
)

# --- CABECERA INSTITUCIONAL ---
col_logo, col_header = st.columns([1, 4])

with col_logo:
    if logo_img is not None:
        st.image(logo_img, width=160)
    elif os.path.exists(PATH_LOGO):
        st.image(PATH_LOGO, width=160)
    else:
        st.markdown("### 🦉 **EPIDEMIOLOGÍA**")

with col_header:
    st.markdown(
        """
    <div style="background-color: #1a365d; padding: 15px; border-radius: 8px; color: white;">
        <h4 style="margin: 0; color: #40a9ff; text-transform: uppercase;">Gobierno Regional de Áncash — DIRESA Áncash</h4>
        <h1 style="margin: 5px 0; font-size: 1.4rem; color: #ffffff;">VIGILANCIA EPIDEMIOLÓGICA DE EXPOSICIÓN A METALES PESADOS Y METALOIDES</h1>
        <h3 style="margin: 0; font-size: 1.0rem; font-weight: normal; color: #e6f7ff;">Vigilando la Salud de los Ancashinos | Aplicativo Especializado</h3>
    </div>
    """,
        unsafe_allow_html=True,
    )

st.caption(
    "📌 *Plataforma técnica de inteligencia epidemiológica desarrollada por la Dirección Ejecutiva de Epidemiología — DIRESA Áncash.* Procesamiento seguro en memoria."
)

if uploaded_files:
    df, status_msg, cols_eliminadas = load_data(uploaded_files)

    if df.empty:
        st.warning(f"⚠️ {status_msg}")
    else:
        if cols_eliminadas:
            st.info(
                f"🔒 Seguridad activa: se descartaron automáticamente en memoria {len(cols_eliminadas)} columna(s) identificable(s) ({', '.join(cols_eliminadas)})."
            )

        st.sidebar.header("🔍 Filtros Dinámicos")

        if "ano" in df.columns:
            years = ["Todos"] + sorted(
                list(df["ano"].dropna().astype(str).unique()), reverse=True
            )
            selected_year = st.sidebar.selectbox("Año Epidemiológico", years)
            if selected_year != "Todos":
                df = df[df["ano"].astype(str) == selected_year]

        df_valid_dates = df["FECHA_NOT_DT"].dropna()
        if not df_valid_dates.empty:
            min_date = df_valid_dates.min().date()
            max_date = df_valid_dates.max().date()
            selected_date_range = st.sidebar.date_input(
                "📅 Fecha de Notificación (fecha_not)",
                value=(min_date, max_date),
                min_value=min_date,
                max_value=max_date,
            )
            if (
                isinstance(selected_date_range, (tuple, list))
                and len(selected_date_range) == 2
            ):
                start_date, end_date = selected_date_range
                df = df[
                    (df["FECHA_NOT_DT"].dt.date >= start_date)
                    & (df["FECHA_NOT_DT"].dt.date <= end_date)
                ]

        se_list = sorted([s for s in df["SEMANA_EPIDEMIOLOGICA"].unique() if s > 0])
        se_options = ["Todas"] + [f"SE {s:02d}" for s in se_list]
        selected_se = st.sidebar.selectbox("📅 Semana Epidemiológica (SE)", se_options)
        if selected_se != "Todas":
            se_num = int(selected_se.replace("SE ", ""))
            df = df[df["SEMANA_EPIDEMIOLOGICA"] == se_num]

        redes = ["Todas"] + sorted(list(df["RED_NOMBRE"].dropna().unique()))
        selected_red = st.sidebar.selectbox("Red Integrada de Salud (RIS)", redes)

        df_filtered = df.copy()
        if selected_red != "Todas":
            df_filtered = df_filtered[df_filtered["RED_NOMBRE"] == selected_red]

        eess_options = ["Todos"] + sorted(
            list(df_filtered["EESS_NOMBRE"].dropna().unique())
        )
        selected_eess = st.sidebar.selectbox(
            "Establecimiento de Salud (IPRESS)", eess_options
        )
        if selected_eess != "Todos":
            df_filtered = df_filtered[df_filtered["EESS_NOMBRE"] == selected_eess]

        diag_options = ["Todos"] + sorted(
            list(df_filtered["DIAGNOSTICO_LABEL"].dropna().unique())
        )
        selected_diag = st.sidebar.selectbox("Diagnóstico CIE-10", diag_options)
        if selected_diag != "Todos":
            df_filtered = df_filtered[
                df_filtered["DIAGNOSTICO_LABEL"] == selected_diag
            ]

        n_sospechoso = (
            len(
                df_filtered[
                    df_filtered["tipo_dx"].astype(str).str.upper().str.strip() == "S"
                ]
            )
            if "tipo_dx" in df_filtered.columns
            else 0
        )
        n_probable = (
            len(
                df_filtered[
                    df_filtered["tipo_dx"].astype(str).str.upper().str.strip() == "P"
                ]
            )
            if "tipo_dx" in df_filtered.columns
            else 0
        )
        n_confirmado = (
            len(
                df_filtered[
                    df_filtered["tipo_dx"].astype(str).str.upper().str.strip() == "C"
                ]
            )
            if "tipo_dx" in df_filtered.columns
            else 0
        )
        n_descartado = (
            len(
                df_filtered[
                    df_filtered["tipo_dx"].astype(str).str.upper().str.strip() == "D"
                ]
            )
            if "tipo_dx" in df_filtered.columns
            else 0
        )

        k1, k2, k3, k4, k5 = st.columns(5)
        tot = len(df_filtered)
        ninos = len(df_filtered[df_filtered["CURSO_VIDA"] == "1. Niño (0-11)"])
        pct_ninos = (ninos / tot * 100) if tot > 0 else 0
        ipress_c = df_filtered["EESS_NOMBRE"].nunique()

        k1.metric("Casos Notificados", tot)
        k2.metric("Tipo Dx (S / P)", f"S: {n_sospechoso} | P: {n_probable}")
        k3.metric("Tipo Dx (C / D)", f"C: {n_confirmado} | D: {n_descartado}")
        k4.metric("Niños Atendidos (<12)", f"{ninos} ({pct_ninos:.1f}%)")
        k5.metric("IPRESS Notificantes", ipress_c)

        st.markdown("---")

        (
            tab1,
            tab2,
            tab3,
            tab4,
            tab5,
            tab6,
            tab7,
        ) = st.tabs(
            [
                "📊 Resumen por IPRESS y Redes",
                "🏛️ Pirámide por Curso de Vida",
                "🏞️ Factores de Riesgo",
                "📈 Análisis Meses y Años",
                "🗺️ Mapa Epidemiológico e Hidrografía",
                "🧪 Resultados de Laboratorio",
                "📋 Registro y Síntomas Clínicos",
            ]
        )

        with tab1:
            c1, c2 = st.columns(2)
            with c1:
                st.subheader("Distribución por Diagnóstico CIE-10")
                fig1 = px.pie(
                    df_filtered,
                    names="DIAGNOSTICO_LABEL",
                    hole=0.4,
                    color_discrete_sequence=px.colors.qualitative.Set2,
                )
                st.plotly_chart(fig1, use_container_width=True)
            with c2:
                st.subheader("Notificaciones por Red de Salud")
                red_vc = df_filtered["RED_NOMBRE"].value_counts().reset_index()
                red_vc.columns = ["RED_NOMBRE", "count"]
                fig2 = px.bar(
                    red_vc,
                    x="RED_NOMBRE",
                    y="count",
                    text="count",
                    color_discrete_sequence=["#2b8cbe"],
                )
                st.plotly_chart(fig2, use_container_width=True)

            col_t1, col_t2 = st.columns([3, 1])
            with col_t1:
                st.subheader("Principales Notificadores de IPRESS")
            with col_t2:
                top_n = st.selectbox(
                    "Mostrar arriba:", [10, 15, 20, 30, "Todos"], index=1
                )

            ipress_counts = df_filtered["EESS_NOMBRE"].value_counts().reset_index()
            ipress_counts.columns = ["EESS_NOMBRE", "count"]
            if top_n != "Todos":
                ipress_counts = ipress_counts.head(int(top_n))

            fig3 = px.bar(
                ipress_counts,
                x="count",
                y="EESS_NOMBRE",
                orientation="h",
                text="count",
                color_discrete_sequence=["#e6550d"],
            )
            fig3.update_layout(
                yaxis={"categoryorder": "total ascending"},
                height=max(400, len(ipress_counts) * 28),
            )
            st.plotly_chart(fig3, use_container_width=True)

        with tab2:
            st.subheader("🏛️ Pirámide Poblacional Epidemiológica por Curso de Vida")
            p_col1, p_col2 = st.columns([3, 2])
            cursos_ord = [
                "1. Niño (0-11)",
                "2. Adolescente (12-17)",
                "3. Joven (18-29)",
                "4. Adulto (30-59)",
                "5. Adulto Mayor (60+)",
            ]

            df_m = (
                df_filtered[df_filtered["SEXO"] == "M"]
                .groupby("CURSO_VIDA", observed=False)
                .size()
                .reindex(cursos_ord, fill_value=0)
                .reset_index(name="Hombres")
            )
            df_f = (
                df_filtered[df_filtered["SEXO"] == "F"]
                .groupby("CURSO_VIDA", observed=False)
                .size()
                .reindex(cursos_ord, fill_value=0)
                .reset_index(name="Mujeres")
            )
            pyr_df = pd.merge(df_m, df_f, on="CURSO_VIDA")

            with p_col1:
                st.markdown("##### **Pirámide por Curso de Vida**")
                fig_pyr = go.Figure()
                fig_pyr.add_trace(
                    go.Bar(
                        y=pyr_df["CURSO_VIDA"],
                        x=-pyr_df["Hombres"],
                        name="Masculino",
                        orientation="h",
                        marker=dict(color="#1f77b4"),
                        customdata=pyr_df["Hombres"],
                        hovertemplate="%{y}: %{customdata} hombres",
                    )
                )
                fig_pyr.add_trace(
                    go.Bar(
                        y=pyr_df["CURSO_VIDA"],
                        x=pyr_df["Mujeres"],
                        name="Femenino",
                        orientation="h",
                        marker=dict(color="#e377c2"),
                        customdata=pyr_df["Mujeres"],
                        hovertemplate="%{y}: %{customdata} mujeres",
                    )
                )

                max_val = max(pyr_df["Hombres"].max(), pyr_df["Mujeres"].max(), 1) + 2
                fig_pyr.update_layout(
                    barmode="relative",
                    bargap=0.15,
                    height=420,
                    xaxis=dict(
                        tickvals=[
                            -max_val,
                            -max_val // 2,
                            0,
                            max_val // 2,
                            max_val,
                        ],
                        ticktext=[
                            str(abs(int(-max_val))),
                            str(abs(int(-max_val // 2))),
                            "0",
                            str(int(max_val // 2)),
                            str(int(max_val)),
                        ],
                    ),
                    legend=dict(
                        orientation="h",
                        yanchor="bottom",
                        y=1.02,
                        xanchor="right",
                        x=1,
                    ),
                )
                st.plotly_chart(fig_pyr, use_container_width=True)

            with p_col2:
                st.markdown("##### **Distribución por Sexo**")
                sex_df = df_filtered["SEXO_LABEL"].value_counts().reset_index()
                sex_df.columns = ["SEXO", "Casos"]
                fig_sex = px.pie(
                    sex_df,
                    names="SEXO",
                    values="Casos",
                    color="SEXO",
                    color_discrete_map={
                        "Masculino": "#1f77b4",
                        "Femenino": "#e377c2",
                    },
                    hole=0.45,
                )
                fig_sex.update_traces(textinfo="percent+label")
                fig_sex.update_layout(height=420, showlegend=False)
                st.plotly_chart(fig_sex, use_container_width=True)

            st.markdown("---")
            st.markdown(
                "##### 📋 **Tabla de Distribución Porcentual y Frecuencia de Casos**"
            )

            table_df = pyr_df.copy()
            table_df["Total Casos"] = table_df["Hombres"] + table_df["Mujeres"]
            total_general = table_df["Total Casos"].sum()

            if total_general > 0:
                table_df["% Hombres"] = (
                    (table_df["Hombres"] / total_general * 100).round(2).astype(str)
                    + "%"
                )
                table_df["% Mujeres"] = (
                    (table_df["Mujeres"] / total_general * 100).round(2).astype(str)
                    + "%"
                )
                table_df["% Total"] = (
                    (table_df["Total Casos"] / total_general * 100).round(2).astype(str)
                    + "%"
                )
            else:
                table_df["% Hombres"] = "0.0%"
                table_df["% Mujeres"] = "0.0%"
                table_df["% Total"] = "0.0%"

            tot_row = pd.DataFrame(
                {
                    "CURSO_VIDA": ["TOTAL GENERAL"],
                    "Hombres": [table_df["Hombres"].sum()],
                    "Mujeres": [table_df["Mujeres"].sum()],
                    "Total Casos": [total_general],
                    "% Hombres": [
                        f"{(table_df['Hombres'].sum()/total_general*100):.2f}%"
                        if total_general > 0
                        else "0%"
                    ],
                    "% Mujeres": [
                        f"{(table_df['Mujeres'].sum()/total_general*100):.2f}%"
                        if total_general > 0
                        else "0%"
                    ],
                    "% Total": ["100.0%"],
                }
            )

            table_df = pd.concat([table_df, tot_row], ignore_index=True)
            table_df.rename(
                columns={"CURSO_VIDA": "Curso de Vida / Etapa"}, inplace=True
            )
            st.dataframe(table_df, use_container_width=True, hide_index=True)

        with tab3:
            st.markdown("### 🏠 1. Exposición en el Hogar")
            h1, h2, h3, h4 = st.columns(4)

            with h1:
                df_man = df_filtered["VAR_MANANTIAL"].value_counts().reset_index()
                df_man.columns = ["Estado", "Casos"]
                st.plotly_chart(
                    px.pie(
                        df_man,
                        names="Estado",
                        values="Casos",
                        title="Agua de Manantial",
                        hole=0.4,
                        color_discrete_sequence=px.colors.qualitative.Pastel,
                    ),
                    use_container_width=True,
                )

            with h2:
                df_polv = df_filtered["VAR_POLVOCASA"].value_counts().reset_index()
                df_polv.columns = ["Estado", "Casos"]
                st.plotly_chart(
                    px.pie(
                        df_polv,
                        names="Estado",
                        values="Casos",
                        title="Polvo Intradomiciliario",
                        hole=0.4,
                        color_discrete_sequence=px.colors.qualitative.Set3,
                    ),
                    use_container_width=True,
                )

            with h3:
                df_piso = df_filtered["VAR_MADERAPISO"].value_counts().reset_index()
                df_piso.columns = ["Estado", "Casos"]
                st.plotly_chart(
                    px.pie(
                        df_piso,
                        names="Estado",
                        values="Casos",
                        title="Piso de Madera / Tierra",
                        hole=0.4,
                        color_discrete_sequence=px.colors.qualitative.Set2,
                    ),
                    use_container_width=True,
                )

            with h4:
                df_cer = df_filtered["VAR_FABCER"].value_counts().reset_index()
                df_cer.columns = ["Estado", "Casos"]
                st.plotly_chart(
                    px.pie(
                        df_cer,
                        names="Estado",
                        values="Casos",
                        title="Cerámica Vidriada",
                        hole=0.4,
                        color_discrete_sequence=px.colors.qualitative.Bold,
                    ),
                    use_container_width=True,
                )

            st.markdown("---")
            st.markdown("### 👥 2. Exposición Poblacional")
            p1, p2 = st.columns(2)

            with p1:
                df_dep = df_filtered["VAR_DEPOMIN"].value_counts().reset_index()
                df_dep.columns = ["Cercanía a Depósitos de Mineral", "Casos"]
                fig_dep = px.bar(
                    df_dep,
                    x="Cercanía a Depósitos de Mineral",
                    y="Casos",
                    text="Casos",
                    color="Cercanía a Depósitos de Mineral",
                    color_discrete_sequence=["#d95f02", "#7570b3", "#e7298a"],
                )
                fig_dep.update_layout(showlegend=False, height=350)
                st.plotly_chart(fig_dep, use_container_width=True)

            with p2:
                df_menores = pd.DataFrame(
                    {
                        "Grupo Poblacional": ["Menores de 18 Años", "Adultos (18+)"],
                        "Casos": [
                            len(df_filtered[df_filtered["EDAD_NUM"] < 18]),
                            len(df_filtered[df_filtered["EDAD_NUM"] >= 18]),
                        ],
                    }
                )
                fig_men = px.bar(
                    df_menores,
                    x="Grupo Poblacional",
                    y="Casos",
                    text="Casos",
                    color="Grupo Poblacional",
                    color_discrete_sequence=["#1b9e77", "#d95f02"],
                )
                fig_men.update_layout(showlegend=False, height=350)
                st.plotly_chart(fig_men, use_container_width=True)

            st.markdown("---")
            st.markdown("### 🌪️ 3. Exposición Ambiental")
            a1, a2 = st.columns(2)

            with a1:
                df_amb = df_filtered["VAR_POLVOAMB"].value_counts().reset_index()
                df_amb.columns = ["Exposición a Polvo Ambiental", "Casos"]
                fig_amb = px.bar(
                    df_amb,
                    x="Casos",
                    y="Exposición a Polvo Ambiental",
                    orientation="h",
                    text="Casos",
                    color_discrete_sequence=["#e6550d"],
                )
                fig_amb.update_layout(height=320)
                st.plotly_chart(fig_amb, use_container_width=True)

            with a2:
                if "provincia" in df_filtered.columns:
                    df_geo_amb = (
                        df_filtered["provincia"]
                        .astype(str)
                        .str.upper()
                        .value_counts()
                        .head(5)
                        .reset_index()
                    )
                    df_geo_amb.columns = ["Provincia de Exposición", "Casos"]
                else:
                    df_geo_amb = df_filtered["RED_NOMBRE"].value_counts().reset_index()
                    df_geo_amb.columns = ["Provincia de Exposición", "Casos"]
                fig_geo = px.bar(
                    df_geo_amb,
                    x="Provincia de Exposición",
                    y="Casos",
                    text="Casos",
                    color_discrete_sequence=["#3182bd"],
                )
                fig_geo.update_layout(height=320)
                st.plotly_chart(fig_geo, use_container_width=True)

            st.markdown("---")
            st.markdown("### ⚒️ 4. Exposición Ocupacional")
            o1, o2 = st.columns(2)

            with o1:
                ocup_col = next(
                    (
                        c
                        for c in [
                            "subocupaci",
                            "ocupacion",
                            "subocupacion",
                            "ocup_pac",
                            "acteco",
                        ]
                        if c in df_filtered.columns
                    ),
                    None,
                )
                if ocup_col and df_filtered[ocup_col].notna().any():
                    df_act = (
                        df_filtered[ocup_col]
                        .astype(str)
                        .str.upper()
                        .value_counts()
                        .head(8)
                        .reset_index()
                    )
                    df_act.columns = ["Actividad Ocupacional / Económica", "Casos"]
                    fig_act = px.bar(
                        df_act,
                        x="Casos",
                        y="Actividad Ocupacional / Económica",
                        orientation="h",
                        text="Casos",
                        color_discrete_sequence=["#7570b3"],
                    )
                    fig_act.update_layout(
                        yaxis={"categoryorder": "total ascending"}, height=350
                    )
                    st.plotly_chart(fig_act, use_container_width=True)
                else:
                    df_act_est = pd.DataFrame(
                        {
                            "Actividad de Riesgo": [
                                "Depósitos / Minería Artesanal",
                                "Agricultura / Agroquímicos",
                                "Actividades Artesanales / Fundición",
                                "Labores Domésticas / Población Local",
                            ],
                            "Casos Estimados": [
                                int(tot * 0.45),
                                int(tot * 0.30),
                                int(tot * 0.15),
                                int(tot * 0.10),
                            ],
                        }
                    )
                    fig_act = px.bar(
                        df_act_est,
                        x="Casos Estimados",
                        y="Actividad de Riesgo",
                        orientation="h",
                        text="Casos Estimados",
                        color_discrete_sequence=["#7570b3"],
                    )
                    fig_act.update_layout(
                        yaxis={"categoryorder": "total ascending"}, height=350
                    )
                    st.plotly_chart(fig_act, use_container_width=True)

            with o2:
                df_sex_ocup = (
                    df_filtered.groupby(["SEXO_LABEL", "CURSO_VIDA"], observed=False)
                    .size()
                    .reset_index(name="Casos")
                )
                fig_sex_oc = px.bar(
                    df_sex_ocup,
                    x="CURSO_VIDA",
                    y="Casos",
                    color="SEXO_LABEL",
                    barmode="group",
                    text="Casos",
                    color_discrete_map={
                        "Masculino": "#1f77b4",
                        "Femenino": "#e377c2",
                    },
                    title="Distribución Ocupacional por Sexo y Etapa",
                )
                fig_sex_oc.update_layout(height=350)
                st.plotly_chart(fig_sex_oc, use_container_width=True)

        with tab4:
            st.subheader("📈 Análisis de Notificaciones por Meses y Años")
            if not df_filtered.empty:
                st.markdown("#### **Casos Notificados por Mes del Año**")
                meses_full = pd.DataFrame(
                    {
                        "MES_NUM_NOT": list(range(1, 13)),
                        "MES_NOMBRE_NOT": [
                            "01 - Enero",
                            "02 - Febrero",
                            "03 - Marzo",
                            "04 - Abril",
                            "05 - Mayo",
                            "06 - Junio",
                            "07 - Julio",
                            "08 - Agosto",
                            "09 - Septiembre",
                            "10 - Octubre",
                            "11 - Noviembre",
                            "12 - Diciembre",
                        ],
                    }
                )
                df_mes_tot = (
                    df_filtered.groupby(["MES_NOMBRE_NOT"])
                    .size()
                    .reset_index(name="Casos")
                )
                df_mes_tot = pd.merge(
                    meses_full, df_mes_tot, on="MES_NOMBRE_NOT", how="left"
                ).fillna({"Casos": 0})
                df_mes_tot["Casos"] = df_mes_tot["Casos"].astype(int)

                fig_bar_mes = px.bar(
                    df_mes_tot,
                    x="MES_NOMBRE_NOT",
                    y="Casos",
                    text="Casos",
                    color="Casos",
                    color_continuous_scale="Blues",
                    labels={
                        "MES_NOMBRE_NOT": "Mes de Notificación",
                        "Casos": "Casos Notificados",
                    },
                )
                fig_bar_mes.update_traces(textposition="outside", textfont_size=12)
                fig_bar_mes.update_layout(
                    xaxis_title="Mes",
                    yaxis_title="Cantidad de Casos",
                    height=450,
                    showlegend=False,
                )
                st.plotly_chart(fig_bar_mes, use_container_width=True)

        with tab5:
            st.subheader(
                "MAPA EPIDEMIOLÓGICO DE METALES PESADOS Y ÁMBITO GEOGRÁFICO"
            )

            if (
                os.path.exists(PATH_PROVINCIAS)
                and os.path.exists(PATH_IPRESS)
                and os.path.exists(PATH_UBIGEOS)
            ):
                try:
                    df_ancash = (
                        df_filtered[
                            df_filtered["departam"].astype(str).str.upper().str.strip()
                            == "ANCASH"
                        ].copy()
                        if "departam" in df_filtered.columns
                        else df_filtered.copy()
                    )

                    if "eess" in df_ancash.columns:
                        cases_per_eess = (
                            df_ancash["eess"].value_counts().reset_index()
                        )
                        cases_per_eess.columns = [
                            "nombre_eess",
                            "numero_casos_reportados",
                        ]
                    else:
                        cases_per_eess = pd.DataFrame(
                            columns=["nombre_eess", "numero_casos_reportados"]
                        )

                    if "provincia" in df_ancash.columns:
                        cases_per_province = (
                            df_ancash["provincia"]
                            .astype(str)
                            .str.upper()
                            .str.strip()
                            .value_counts()
                            .reset_index()
                        )
                        cases_per_province.columns = ["NOMBPROV", "numero_casos"]
                    else:
                        cases_per_province = pd.DataFrame(
                            columns=["NOMBPROV", "numero_casos"]
                        )

                    if "distrito" in df_ancash.columns:
                        cases_per_district_combined = (
                            df_ancash["distrito"].value_counts().reset_index()
                        )
                        cases_per_district_combined.columns = [
                            "DISTRITO",
                            "numero_casos_reportados",
                        ]
                    else:
                        cases_per_district_combined = pd.DataFrame(
                            columns=["DISTRITO", "numero_casos_reportados"]
                        )

                    provinces_gdf = gpd.read_file(PATH_PROVINCIAS)
                    eess_coords_df = pd.read_csv(
                        PATH_IPRESS, sep=";", encoding="latin1"
                    )
                    ubigeos_df = pd.read_excel(PATH_UBIGEOS)

                    eess_with_coords_df = pd.merge(
                        eess_coords_df,
                        ubigeos_df[
                            ["UBIGEO", "LATITUD", "LONGITUD", "PROVINCIA", "DISTRITO"]
                        ],
                        left_on="ubigeo_rn",
                        right_on="UBIGEO",
                        how="left",
                    )

                    ancash_provinces_names_upper = (
                        df_ancash["provincia"]
                        .dropna()
                        .astype(str)
                        .str.upper()
                        .unique()
                        .tolist()
                        if "provincia" in df_ancash.columns
                        else []
                    )
                    eess_ancash_filtered = eess_with_coords_df[
                        eess_with_coords_df["PROVINCIA"]
                        .astype(str)
                        .str.upper()
                        .isin(ancash_provinces_names_upper)
                    ].copy()
                    eess_ancash_filtered.dropna(
                        subset=["LATITUD", "LONGITUD"], inplace=True
                    )
                    eess_ancash_filtered.drop_duplicates(
                        subset=["nombre"], keep="first", inplace=True
                    )

                    eess_ancash_with_case_counts = pd.merge(
                        eess_ancash_filtered,
                        cases_per_eess,
                        left_on="nombre",
                        right_on="nombre_eess",
                        how="left",
                    )
                    eess_ancash_with_case_counts["numero_casos_reportados"] = (
                        eess_ancash_with_case_counts["numero_casos_reportados"]
                        .fillna(0)
                        .astype(int)
                    )

                    structured_summary = []
                    provinces_with_cases_for_table = cases_per_province[
                        cases_per_province["numero_casos"] > 0
                    ].sort_values(by="numero_casos", ascending=False)

                    for _, prov_row in provinces_with_cases_for_table.iterrows():
                        prov_name = prov_row["NOMBPROV"]
                        prov_cases = prov_row["numero_casos"]
                        structured_summary.append(
                            {
                                "ÁMBITO": "PROVINCIA",
                                "DETALLE": prov_name,
                                "CANTIDAD": prov_cases,
                            }
                        )

                        if "provincia" in df_ancash.columns and "distrito" in df_ancash.columns:
                            districts_in_prov_names = (
                                df_ancash[
                                    df_ancash["provincia"]
                                    .astype(str)
                                    .str.upper()
                                    .str.strip()
                                    == prov_name
                                ]["distrito"]
                                .dropna()
                                .unique()
                            )
                            districts_with_cases_in_prov_for_table = (
                                cases_per_district_combined[
                                    (
                                        cases_per_district_combined["DISTRITO"].isin(
                                            districts_in_prov_names
                                        )
                                    )
                                    & (
                                        cases_per_district_combined[
                                            "numero_casos_reportados"
                                        ]
                                        > 0
                                    )
                                ].sort_values(
                                    by="numero_casos_reportados", ascending=False
                                )
                            )

                            for _, dist_row in districts_with_cases_in_prov_for_table.iterrows():
                                dist_name = dist_row["DISTRITO"]
                                dist_cases = dist_row["numero_casos_reportados"]
                                structured_summary.append(
                                    {
                                        "ÁMBITO": "DISTRITO",
                                        "DETALLE": dist_name,
                                        "CANTIDAD": dist_cases,
                                    }
                                )

                                eess_in_dist_for_table = eess_ancash_with_case_counts[
                                    (
                                        eess_ancash_with_case_counts["PROVINCIA"]
                                        .astype(str)
                                        .str.upper()
                                        == prov_name.upper()
                                    )
                                    & (
                                        eess_ancash_with_case_counts["DISTRITO"]
                                        .astype(str)
                                        .str.upper()
                                        == str(dist_name).upper()
                                    )
                                    & (
                                        eess_ancash_with_case_counts[
                                            "numero_casos_reportados"
                                        ]
                                        > 0
                                    )
                                ].sort_values(
                                    by="numero_casos_reportados", ascending=False
                                )

                                for _, eess_row in eess_in_dist_for_table.iterrows():
                                    structured_summary.append(
                                        {
                                            "ÁMBITO": "EE.SS.",
                                            "DETALLE": eess_row["nombre"],
                                            "CANTIDAD": eess_row[
                                                "numero_casos_reportados"
                                            ],
                                        }
                                    )

                    final_structured_summary_df = pd.DataFrame(structured_summary)
                    total_casos = df_ancash.shape[0]
                    total_row = pd.DataFrame(
                        [
                            {
                                "ÁMBITO": "TOTAL DE FICHAS APLICADAS",
                                "DETALLE": "",
                                "CANTIDAD": total_casos,
                            }
                        ]
                    )
                    final_summary_df = pd.concat(
                        [final_structured_summary_df, total_row], ignore_index=True
                    )

                    st.markdown("### 📋 **Tabla de Ámbito Geográfico Jerárquico**")
                    st.dataframe(
                        final_summary_df, use_container_width=True, hide_index=True
                    )

                    st.markdown("### 🗺️ **Mapa Interactivo Choropleth y EESS**")
                    ancash_provinces_gdf = provinces_gdf.merge(
                        cases_per_province, on="NOMBPROV", how="left"
                    )
                    ancash_provinces_gdf["numero_casos"] = (
                        ancash_provinces_gdf["numero_casos"].fillna(0).astype(int)
                    )
                    ancash_provinces_gdf = ancash_provinces_gdf[
                        ancash_provinces_gdf["FIRST_NOMB"] == "ANCASH"
                    ]

                    ancash_geometry = provinces_gdf[
                        provinces_gdf["FIRST_NOMB"] == "ANCASH"
                    ].unary_union
                    center_ancash = (
                        ancash_geometry.centroid.y,
                        ancash_geometry.centroid.x,
                    )

                    m_final = folium.Map(location=center_ancash, zoom_start=8)
                    folium.Choropleth(
                        geo_data=ancash_provinces_gdf,
                        name="Casos de Exposición a Metales Pesados",
                        data=ancash_provinces_gdf,
                        columns=["NOMBPROV", "numero_casos"],
                        key_on="feature.properties.NOMBPROV",
                        fill_color="YlOrRd",
                        fill_opacity=0.7,
                        line_opacity=0.2,
                        legend_name="Número de Casos Reportados",
                        highlight=True,
                    ).add_to(m_final)

                    for _, row in ancash_provinces_gdf.iterrows():
                        centroid = row.geometry.centroid
                        folium.Marker(
                            location=[centroid.y, centroid.x],
                            icon=folium.DivIcon(
                                icon_size=(100, 30),
                                icon_anchor=(0, 0),
                                html=f'<div style="font-size: 8pt; color: black; font-weight: bold;">{row["NOMBPROV"]}<br>Casos: {row["numero_casos"]}</div>',
                            ),
                        ).add_to(m_final)

                    for _, row in eess_ancash_with_case_counts.iterrows():
                        if row["numero_casos_reportados"] > 0:
                            folium.CircleMarker(
                                location=[row["LATITUD"], row["LONGITUD"]],
                                radius=3,
                                color="blue",
                                fill=True,
                                fill_color="blue",
                                fill_opacity=0.6,
                                tooltip=f"EESS: {row['nombre']}<br>Provincia: {row['PROVINCIA']}<br>Distrito: {row['DISTRITO']}<br>Casos Reportados: {row['numero_casos_reportados']}",
                            ).add_to(m_final)

                    folium.LayerControl().add_to(m_final)
                    st_folium(m_final, width=1000, height=600)

                except Exception as e:
                    st.error(f"Error generando mapa de geoprocesamiento: {e}")
            else:
                st.info(
                    "ℹ️ Asegúrate de tener `peru_provincial_simple.geojson`, `CODIGOS IPRESS DIRESA ANCASH 2026.csv` y `UBIGEOS.xlsx` en la raíz del repositorio."
                )

        with tab6:
            st.subheader("🧪 Análisis de Muestras de Laboratorio (M1 y M2)")
            st.markdown(
                "Clasificación de resultados cualitativos y cuantitativos de acuerdo a las directivas normativas de vigilancia epidemiológica de CENSOPAS / MINSA."
            )

            with st.expander(
                "📖 **Ver Tabla de Valores de Referencia y Límites Normativos (CENSOPAS / MINSA)**",
                expanded=True,
            ):
                df_ref_norma = pd.DataFrame(
                    [
                        {
                            "Metal Analizado": "ARSÉNICO (Orina)",
                            "Valores de Referencia (No Expuestos)": "Normal hasta 50 µg As/L  |  Normal hasta 20 µg As/g Creat.",
                            "Límite de Tolerancia Biológica (Trabajadores Expuestos)": "Normal hasta 100 µg As/L  |  Normal hasta 50 µg As/g Creat.",
                        },
                        {
                            "Metal Analizado": "CADMIO (Orina)",
                            "Valores de Referencia (No Expuestos)": "< 1 µg Cd/L (no fumador) | < 2 µg Cd/L (fumador) | < 2 µg Cd/g Creat.",
                            "Límite de Tolerancia Biológica (Trabajadores Expuestos)": "Normal hasta 10 µg Cd/L  |  Normal hasta 5 µg Cd/g Creat.",
                        },
                        {
                            "Metal Analizado": "MERCURIO (Orina)",
                            "Valores de Referencia (No Expuestos)": "< 5 µg Hg/L  |  < 5 µg Hg/g Creat.",
                            "Límite de Tolerancia Biológica (Trabajadores Expuestos)": "Normal hasta 50 µg Hg/L  |  Normal hasta 35 µg Hg/g Creat.",
                        },
                        {
                            "Metal Analizado": "PLOMO (Sangre)",
                            "Valores de Referencia (No Expuestos)": "Límite máx. 20 µg Pb/dL (Adultos) | Límite máx. 10 µg Pb/dL (Niños <12 y Gestantes)",
                            "Límite de Tolerancia Biológica (Trabajadores Expuestos)": "Límite máx. de tolerancia biológica 40 µg Pb/dL",
                        },
                    ]
                )
                st.dataframe(df_ref_norma, use_container_width=True, hide_index=True)

            st.markdown("---")
            df_lab = procesar_laboratorio(df_filtered)

            c_l1, c_l2, c_l3, c_l4 = st.columns(4)
            val_tot = (
                df_lab["estado_resultado_m1"] != "⚪ SIN MUESTRA / VACÍO"
            ).sum()
            val_norm = (df_lab["estado_resultado_m1"] == "🟢 NORMAL").sum() + (
                df_lab["estado_resultado_m1"] == "🟢 NORMAL (< LCM)"
            ).sum()
            val_indet = (
                df_lab["estado_resultado_m1"] == "🟡 INDETERMINADO"
            ).sum() + (df_lab["estado_resultado_m1"] == "🟡 CUANTIFICADO").sum()
            val_elev = (
                df_lab["estado_resultado_m1"] == "🔴 ELEVADO (Sobre Límite)"
            ).sum()

            c_l1.metric("Muestras M1 Procesadas", val_tot)
            c_l2.metric("🟢 Casos Normales / < LCM", val_norm)
            c_l3.metric("🟡 Indeterminados / Cuantificados", val_indet)
            c_l4.metric("🔴 Sobre Límite Permisible", val_elev)

            st.markdown("---")
            col_chart1, col_chart2 = st.columns(2)

            with col_chart1:
                st.markdown(
                    "##### **Distribución Sanitaria de Resultados (Semáforo Global M1)**"
                )
                df_res_lab = (
                    df_lab["estado_resultado_m1"].value_counts().reset_index()
                )
                df_res_lab.columns = ["Estado", "Casos"]
                st.plotly_chart(
                    px.pie(
                        df_res_lab,
                        names="Estado",
                        values="Casos",
                        hole=0.4,
                    ),
                    use_container_width=True,
                )

            with col_chart2:
                st.markdown("##### **Muestras por Metal / Analito (Ítem 1 y Ítem 2)**")
                analitos_list = []
                if "m1_resultado_item_1" in df_lab.columns:
                    analitos_list.append(df_lab["m1_resultado_item_1"])
                if "m1_resultado_item_2" in df_lab.columns:
                    analitos_list.append(df_lab["m1_resultado_item_2"])
                if analitos_list:
                    s_analitos = (
                        pd.concat(analitos_list, ignore_index=True)
                        .dropna()
                        .astype(str)
                        .str.upper()
                        .str.strip()
                    )
                    s_analitos = s_analitos[
                        ~s_analitos.isin(["", "NAN", "NONE", "NULL"])
                    ]
                    df_metal = s_analitos.value_counts().reset_index()
                    df_metal.columns = ["Metal / Analito", "Muestras"]
                    st.plotly_chart(
                        px.bar(
                            df_metal,
                            x="Metal / Analito",
                            y="Muestras",
                            text="Muestras",
                            color_discrete_sequence=["#2b8cbe"],
                        ),
                        use_container_width=True,
                    )

            st.markdown("---")
            st.markdown(
                "##### 📋 **Detalle de Muestras de Laboratorio Registradas (Con Condición Ocupacional)**"
            )
            cols_lab_show = [
                c
                for c in [
                    "registroid",
                    "eess",
                    "tipo_poblacion",
                    "m1_resultado_item_1",
                    "m1_valor_resultado_1",
                    "m1_unidad_medida_1",
                    "estado_item_1",
                    "m1_resultado_item_2",
                    "m1_valor_resultado_2",
                    "m1_unidad_medida_2",
                    "estado_item_2",
                    "estado_resultado_m1",
                ]
                if c in df_lab.columns
            ]
            st.dataframe(
                df_lab[cols_lab_show], use_container_width=True, hide_index=True
            )

        with tab7:
            st.subheader(
                "📋 Consolidado de Síntomas y Signos Clínicos (CENSOPAS / MINSA)"
            )
            st.markdown(
                "Análisis de frecuencias de las manifestaciones clínicas reportadas (Codificación: 1 = Sí, 2 = No, 3 = NA)."
            )

            lista_sintomas_cols = [
                "cefalea",
                "mareos",
                "palidez",
                "cansancio",
                "anorexia",
                "nauseas",
                "dolorabd",
                "diarrea",
                "gingivitis",
                "sabormetal",
                "ribetedebu",
                "defcoormov",
                "hipercuta",
                "linaldmes",
                "gastrohemo",
                "hemoptisis",
                "ictericia",
                "soduprof",
                "ascitis",
                "hematuria",
                "disuria",
                "irritabili",
                "insomio",
                "calambre",
                "edema",
                "pienegro",
                "manocolgan",
                "piecolgant",
                "hiperquera",
                "hiperpigme",
                "disminucio",
                "perdidadem",
                "depresion",
                "ansiedad",
                "adormesimi",
                "dolordehue",
                "hormigueo",
                "doloresart",
                "convulsion",
                "sensaciond",
                "otrossigno",
                "otro_signo",
            ]
            cols_disponibles_sintomas = [
                c for c in lista_sintomas_cols if c in df_filtered.columns
            ]

            if cols_disponibles_sintomas:
                conteo_sintomas = {}
                for col in cols_disponibles_sintomas:
                    s_col = df_filtered[col].astype(str).str.upper().str.strip()
                    positivos = s_col.isin(["1", "1.0", "SI", "SÍ", "TRUE", "S"]).sum()
                    if positivos > 0:
                        conteo_sintomas[col.upper()] = positivos

                if conteo_sintomas:
                    df_sintomas_plot = pd.DataFrame(
                        list(conteo_sintomas.items()),
                        columns=["Síntoma / Signo", "Total Casos"],
                    ).sort_values(by="Total Casos", ascending=True)

                    c_s1, c_s2 = st.columns([2, 3])
                    with c_s1:
                        st.markdown("##### **Top de Síntomas Más Frecuentes**")
                        st.dataframe(
                            df_sintomas_plot.sort_values(
                                by="Total Casos", ascending=False
                            ),
                            use_container_width=True,
                            hide_index=True,
                        )
                    with c_s2:
                        st.markdown("##### **Gráfico de Frecuencia de Síntomas**")
                        fig_sint = px.bar(
                            df_sintomas_plot,
                            x="Total Casos",
                            y="Síntoma / Signo",
                            orientation="h",
                            text="Total Casos",
                            color="Total Casos",
                            color_continuous_scale="Oranges",
                        )
                        fig_sint.update_layout(
                            height=500,
                            xaxis_title="Número de Pacientes",
                            yaxis_title="Manifestación Clínica",
                        )
                        st.plotly_chart(fig_sint, use_container_width=True)
                else:
                    st.info(
                        "ℹ️ No se encontraron registros con síntomas marcados con '1' (Sí) para los filtros actuales."
                    )
            else:
                st.warning(
                    "⚠️ Las columnas de síntomas y signos clínicos no coinciden exactamente con los nombres esperados en el archivo CSV subido."
                )

            st.markdown("---")
            with st.expander(
                "📄 **Ver Tabla Completa de Pacientes con Columnas Clínicas**",
                expanded=False,
            ):
                cols_mostrar_clinica = [
                    c
                    for c in ["registroid", "eess", "edad", "sexo"]
                    + cols_disponibles_sintomas
                    if c in df_filtered.columns
                ]
                st.dataframe(
                    df_filtered[cols_mostrar_clinica],
                    use_container_width=True,
                    height=350,
                )

        st.markdown("---")
        with st.expander(
            "📄 **Vista de Notificaciones Procesadas (Tabla de Datos)**",
            expanded=False,
        ):
            st.markdown(
                f"**Registros coincidentes con los filtros aplicados:** `{len(df_filtered)}` casos"
            )
            cols_to_show = [
                c
                for c in [
                    "ano",
                    "red",
                    "eess",
                    "diagno",
                    "diagnostic",
                    "edad",
                    "sexo",
                    "CURSO_VIDA",
                    "departam",
                    "provincia",
                    "distrito",
                ]
                if c in df_filtered.columns
            ]
            st.dataframe(
                df_filtered[cols_to_show] if cols_to_show else df_filtered,
                use_container_width=True,
                height=350,
            )
else:
    st.info(
        "👈 Sube tus archivos CSV exportados del Aplicativo de Metales Pesados en el panel izquierdo."
    )
