import os
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import geopandas as gpd
import folium
from streamlit_folium import st_folium

st.set_page_config(
    page_title="Vigilancia Metales Pesados - DIRESA Áncash 2026",
    page_icon="🧪",
    layout="wide",
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PATH_IPRESS = os.path.join(BASE_DIR, "CODIGOS IPRESS DIRESA ANCASH 2026.csv")
PATH_PROVINCIAS = os.path.join(BASE_DIR, "peru_provincial_simple.geojson")
PATH_UBIGEOS = os.path.join(BASE_DIR, "UBIGEOS.xlsx")

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
        except Exception:
            pass
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


def procesar_notificaciones(uploaded_file):
    ipress_dict = get_ipress_dictionary()
    df = pd.read_csv(
        uploaded_file,
        sep=None,
        engine="python",
        encoding="utf-8-sig",
        on_bad_lines="skip",
    )
    df.columns = [str(c).replace("\ufeff", "").lower().strip() for c in df.columns]

    # Descartar de inmediato columnas con datos personales identificables
    cols_a_eliminar = [
        c for c in df.columns if c in PII_COLUMNS or any(k in c for k in ["dni", "nombre", "apellido", "direccion", "telefono"])
    ]
    if cols_a_eliminar:
        df = df.drop(columns=cols_a_eliminar)

    diag_col = next(
        (c for c in ["diagno", "diagnostic", "cie10"] if c in df.columns), None
    )
    if diag_col:
        def get_diag_label(row):
            code = str(row.get(diag_col, "")).upper().strip()
            desc = str(row.get("diagnostic", "")).upper().strip()
            for c_code, label in CIE_MAP.items():
                if c_code in code or c_code in desc:
                    return label
            return f"{code} - {desc}" if desc else f"Metal Pesado ({code})"

        df["DIAGNOSTICO_LABEL"] = df.apply(get_diag_label, axis=1)
    else:
        df["DIAGNOSTICO_LABEL"] = "Sin Diagnóstico"

    if "eess" in df.columns and df["eess"].notna().any():
        df["EESS_NOMBRE"] = df["eess"].astype(str).str.upper().str.strip()
    elif "cod_eess" in df.columns:
        cods = df["cod_eess"].astype(str).str.upper().str.strip()
        df["EESS_NOMBRE"] = cods.map(ipress_dict).fillna(cods)
    else:
        df["EESS_NOMBRE"] = "Establecimiento Desconocido"

    if "red" in df.columns and df["red"].notna().any():
        df["RED_NOMBRE"] = df["red"].astype(str).str.upper().str.strip()
    elif "cod_red" in df.columns:
        red_num = pd.to_numeric(df["cod_red"], errors="coerce")
        df["RED_NOMBRE"] = red_num.map(RED_MAP).fillna(df["cod_red"].astype(str))
    else:
        df["RED_NOMBRE"] = "Sin Red Registrada"

    df["EDAD_NUM"] = (
        pd.to_numeric(df["edad"], errors="coerce").fillna(0) if "edad" in df else 0
    )

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

    df["CURSO_VIDA"] = df["EDAD_NUM"].apply(get_curso_vida)
    df["SEXO"] = (
        df["sexo"].astype(str).str.upper().str.strip() if "sexo" in df else "M"
    )
    df["SEXO_LABEL"] = df["SEXO"].map({"M": "Masculino", "F": "Femenino"}).fillna("M")

    df["tipo_poblacion"] = df.apply(
        lambda r: (
            "👷 Trab. Expuesto"
            if es_trabajador_expuesto(r)
            else "🏡 No Expuesto (Población General)"
        ),
        axis=1,
    )
    df["estado_item_1"] = df.apply(
        lambda r: evaluar_analito_individual(
            r.get("m1_resultado_item_1"),
            r.get("m1_valor_resultado_1"),
            r.get("m1_unidad_medida_1"),
            r,
        ),
        axis=1,
    )
    df["estado_item_2"] = df.apply(
        lambda r: evaluar_analito_individual(
            r.get("m1_resultado_item_2"),
            r.get("m1_valor_resultado_2"),
            r.get("m1_unidad_medida_2"),
            r,
        ),
        axis=1,
    )
    df["estado_resultado_m1"] = df.apply(
        lambda r: combinar_estados(r["estado_item_1"], r["estado_item_2"]), axis=1
    )
    return df, cols_a_eliminar


st.title("🧪 Sistema de Vigilancia Epidemiológica - Metales Pesados (DIRESA Áncash)")
st.caption("Procesamiento seguro en memoria: los datos personales identificables se descartan automáticamente al cargar el archivo.")

uploaded_file = st.file_uploader(
    "📂 Sube el archivo CSV de notificaciones de vigilancia",
    type=["csv"],
)

if uploaded_file is not None:
    df, eliminadas = procesar_notificaciones(uploaded_file)
    if eliminadas:
        st.info(f"🔒 Seguridad activa: se descartaron {len(eliminadas)} columna(s) identificable(s) en memoria.")

    # Filtros laterales
    st.sidebar.header("Filtros")
    redes_disp = sorted(df["RED_NOMBRE"].dropna().unique().tolist())
    sel_redes = st.sidebar.multiselect("Red de Salud", redes_disp, default=redes_disp)
    df_filt = df[df["RED_NOMBRE"].isin(sel_redes)] if sel_redes else df

    # Métricas principales
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Notificaciones", len(df_filt))
    c2.metric("🔴 Lab. Elevado", int((df_filt["estado_resultado_m1"] == "🔴 ELEVADO (Sobre Límite)").sum()))
    c3.metric("🟢 Lab. Normal", int((df_filt["estado_resultado_m1"] == "🟢 NORMAL").sum()))
    c4.metric("👷 Trab. Expuestos", int((df_filt["tipo_poblacion"] == "👷 Trab. Expuesto").sum()))

    col_izq, col_der = st.columns(2)
    with col_izq:
        st.subheader("Diagnósticos CIE-10")
        diag_counts = df_filt["DIAGNOSTICO_LABEL"].value_counts().reset_index()
        diag_counts.columns = ["Diagnóstico", "Casos"]
        fig_diag = px.bar(diag_counts, x="Casos", y="Diagnóstico", orientation="h", text="Casos")
        fig_diag.update_layout(yaxis={"categoryorder": "total ascending"}, height=380)
        st.plotly_chart(fig_diag, use_container_width=True)

    with col_der:
        st.subheader("Casos por Red de Salud")
        red_counts = df_filt["RED_NOMBRE"].value_counts().reset_index()
        red_counts.columns = ["Red de Salud", "Casos"]
        fig_red = px.bar(red_counts, x="Casos", y="Red de Salud", orientation="h", text="Casos")
        fig_red.update_layout(yaxis={"categoryorder": "total ascending"}, height=380)
        st.plotly_chart(fig_red, use_container_width=True)

    col_lab, col_cv = st.columns(2)
    with col_lab:
        st.subheader("Semáforo de Laboratorio (M1)")
        lab_counts = df_filt["estado_resultado_m1"].value_counts().reset_index()
        lab_counts.columns = ["Estado", "Casos"]
        fig_lab = px.pie(lab_counts, names="Estado", values="Casos", hole=0.4)
        st.plotly_chart(fig_lab, use_container_width=True)

    with col_cv:
        st.subheader("Distribución por Curso de Vida y Sexo")
        cv_counts = df_filt.groupby(["CURSO_VIDA", "SEXO_LABEL"]).size().reset_index(name="Casos")
        fig_cv = px.bar(cv_counts, x="CURSO_VIDA", y="Casos", color="SEXO_LABEL", barmode="group")
        st.plotly_chart(fig_cv, use_container_width=True)

    # Mapa Provincial de Áncash
    if os.path.exists(PATH_PROVINCIAS) and "provincia" in df_filt.columns:
        st.subheader("🗺️ Distribución Provincial en Áncash")
        df_ancash = df_filt[df_filt["departam"].astype(str).str.upper().str.strip() == "ANCASH"].copy() if "departam" in df_filt.columns else df_filt.copy()
        df_ancash["provincia_norm"] = df_ancash["provincia"].astype(str).str.upper().str.strip()
        cases_prov = df_ancash["provincia_norm"].value_counts().reset_index()
        cases_prov.columns = ["NOMBPROV", "numero_casos"]

        provinces_gdf = gpd.read_file(PATH_PROVINCIAS)
        ancash_gdf = provinces_gdf[provinces_gdf["FIRST_NOMB"] == "ANCASH"].merge(
            cases_prov, on="NOMBPROV", how="left"
        )
        ancash_gdf["numero_casos"] = ancash_gdf["numero_casos"].fillna(0).astype(int)

        centro = [
            ancash_gdf.geometry.unary_union.centroid.y,
            ancash_gdf.geometry.unary_union.centroid.x,
        ]
        mapa = folium.Map(location=centro, zoom_start=8)
        folium.Choropleth(
            geo_data=ancash_gdf,
            data=ancash_gdf,
            columns=["NOMBPROV", "numero_casos"],
            key_on="feature.properties.NOMBPROV",
            fill_color="YlOrRd",
            fill_opacity=0.7,
            line_opacity=0.3,
            legend_name="Casos Reportados",
        ).add_to(mapa)
        st_folium(mapa, width=900, height=500)

    # Descarga de tabla anonimizada procesada
    csv_out = df_filt.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "⬇️ Descargar base anonimizada procesada (CSV)",
        data=csv_out,
        file_name="vigilancia_metales_procesado_anonimo.csv",
        mime="text/csv",
    )
else:
    st.info("Sube un archivo CSV arriba para visualizar los indicadores, el semáforo de laboratorio y el mapa provincial.")
