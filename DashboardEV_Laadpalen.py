import os
import json
import requests
import pandas as pd
import streamlit as st
import folium

from folium.plugins import FastMarkerCluster, HeatMap
from streamlit_folium import st_folium

# =========================
# PAGINA-INSTELLINGEN
# =========================
st.set_page_config(page_title="Dashboard Elektrisch Vervoer", layout="wide")
st.title("Dashboard Elektrisch Vervoer")
st.subheader("Analyse van laadinfrastructuur, gebruik en voertuigen in Nederland")

# =========================
# BESTANDSPADEN
# =========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

LAADPAAL_CSV_PATH = os.path.join(BASE_DIR, "laadpaaldata.csv")
CHARGING_PKL_PATH = os.path.join(BASE_DIR, "Charging_data.pkl")
CARS_PKL_PATH = os.path.join(BASE_DIR, "cars.pkl")
EV_PERCENTAGE_CSV_PATH = os.path.join(BASE_DIR, "table_EV%.csv")

# Optioneel GeoJSON
NL_PROVINCES_GEOJSON_PATH = os.path.join(BASE_DIR, "nl_provinces.geojson")

# =========================
# API INSTELLINGEN
# =========================
API_KEY = "b947a33a-1124-4c7d-a0e6-5ef2e8e51c0a"
OCM_URL = "https://api.openchargemap.io/v3/poi"

OCM_PARAMS = {
    "output": "json",
    "countrycode": "NL",
    "maxresults": 10000,
    "compact": False,
    "verbose": False,
    "key": API_KEY
}

HEADERS = {
    "User-Agent": "KoenEVPressureDashboard/6.0"
}

# =========================
# CONSTANTEN
# =========================
OFFICIELE_PROVINCIES = [
    "Drenthe",
    "Flevoland",
    "Friesland",
    "Gelderland",
    "Groningen",
    "Limburg",
    "Noord-Brabant",
    "Noord-Holland",
    "Overijssel",
    "Utrecht",
    "Zeeland",
    "Zuid-Holland"
]

PROVINCIE_MAPPING = {
    "NH": "Noord-Holland",
    "Noord Holland": "Noord-Holland",
    "North Holland": "Noord-Holland",
    "Noord-Holland": "Noord-Holland",

    "ZH": "Zuid-Holland",
    "Zuid Holland": "Zuid-Holland",
    "South Holland": "Zuid-Holland",
    "Zuid-Holland": "Zuid-Holland",

    "NB": "Noord-Brabant",
    "Noord Brabant": "Noord-Brabant",
    "North Brabant": "Noord-Brabant",
    "Noord-Brabant": "Noord-Brabant",

    "LB": "Limburg",
    "Limburg": "Limburg",

    "OV": "Overijssel",
    "Overĳssel": "Overijssel",
    "Overijssel": "Overijssel",

    "FL": "Flevoland",
    "Flevoland": "Flevoland",

    "FR": "Friesland",
    "Fryslân": "Friesland",
    "Friesland": "Friesland",

    "GR": "Groningen",
    "Groningen": "Groningen",

    "DR": "Drenthe",
    "Drenthe": "Drenthe",

    "UT": "Utrecht",
    "Utrecht": "Utrecht",

    "GE": "Gelderland",
    "Gelderland": "Gelderland",

    "ZE": "Zeeland",
    "Zeeland": "Zeeland"
}

PROVINCIE_COORDINATEN = {
    "Noord-Holland": (52.25, 53.25, 4.45, 5.55),
    "Zuid-Holland": (51.70, 52.35, 3.85, 5.05),
    "Utrecht": (51.90, 52.35, 4.85, 5.65),
    "Flevoland": (52.30, 53.10, 5.00, 5.90),
    "Gelderland": (51.75, 52.75, 5.30, 6.70),
    "Noord-Brabant": (51.20, 51.95, 4.00, 5.90),
    "Limburg": (50.70, 51.35, 5.50, 6.25),
    "Overijssel": (52.15, 53.05, 5.75, 6.90),
    "Drenthe": (52.65, 53.30, 6.20, 7.10),
    "Groningen": (53.00, 53.60, 6.20, 7.30),
    "Friesland": (52.80, 53.50, 5.10, 6.35),
    "Zeeland": (51.20, 51.75, 3.25, 4.35),
}

# =========================
# HULPFUNCTIES
# =========================
def schoon_provincie_naam(waarde):
    if pd.isna(waarde):
        return None
    waarde = str(waarde).strip()
    return PROVINCIE_MAPPING.get(waarde, waarde)

def veilige_datetime(df, kolommen):
    for kolom in kolommen:
        if kolom in df.columns:
            df[kolom] = pd.to_datetime(df[kolom], errors="coerce")
    return df

def veilige_numeric(df, kolommen):
    for kolom in kolommen:
        if kolom in df.columns:
            df[kolom] = pd.to_numeric(df[kolom], errors="coerce")
    return df

def get_max_power_kw(connections):
    if not isinstance(connections, list):
        return 0.0

    vermogens = []
    for conn in connections:
        if isinstance(conn, dict):
            power = conn.get("PowerKW")
            if power is not None:
                try:
                    vermogens.append(float(power))
                except Exception:
                    pass

    return max(vermogens) if vermogens else 0.0

def bepaal_provincie_op_coordinaten(lat, lon):
    if pd.isna(lat) or pd.isna(lon):
        return None

    for provincie, (lat_min, lat_max, lon_min, lon_max) in PROVINCIE_COORDINATEN.items():
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            return provincie

    return None

def veilige_ratio(teller, noemer):
    if noemer is None or pd.isna(noemer) or noemer == 0:
        return None
    return teller / noemer

def laad_geojson_bestand():
    if not os.path.exists(NL_PROVINCES_GEOJSON_PATH):
        return None

    try:
        with open(NL_PROVINCES_GEOJSON_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def vind_geojson_naamveld(geojson_data):
    if not geojson_data:
        return None

    features = geojson_data.get("features", [])
    if not features:
        return None

    properties = features[0].get("properties", {})
    mogelijke_velden = ["name", "provincie", "province", "statnaam", "naam", "PROVINCE", "NAME"]

    for veld in mogelijke_velden:
        if veld in properties:
            return veld

    return None

def maak_basiskaart():
    m = folium.Map(
        location=[52.15, 5.30],
        zoom_start=7.2,
        tiles="CartoDB positron",
        control_scale=True,
        zoom_control=True,
        prefer_canvas=True,
        min_zoom=6,
        max_zoom=12
    )
    m.fit_bounds([[50.7, 3.1], [53.7, 7.3]])
    return m

def voeg_geojson_grens_toe(kaart, geojson_data):
    if geojson_data is None:
        return

    try:
        folium.GeoJson(
            geojson_data,
            name="Provincies",
            style_function=lambda _: {
                "fillColor": "#00000000",
                "color": "#333333",
                "weight": 1.2
            }
        ).add_to(kaart)
    except Exception:
        pass

def normaliseer_plaatsnaam(naam):
    if pd.isna(naam):
        return None
    naam = str(naam).strip().lower()
    naam = naam.replace("-", " ")
    naam = " ".join(naam.split())
    return naam

def schaal_0_1(series):
    s = pd.to_numeric(series, errors="coerce")
    if s.isna().all():
        return pd.Series([0] * len(series), index=series.index)
    s = s.fillna(0)
    if s.max() == s.min():
        return pd.Series([0] * len(series), index=series.index)
    return (s - s.min()) / (s.max() - s.min())

def minmax_omgekeerd(series):
    s = pd.to_numeric(series, errors="coerce").fillna(0)
    if s.max() == s.min():
        return pd.Series([0] * len(s), index=s.index)
    return 1 - ((s - s.min()) / (s.max() - s.min()))

# =========================
# DATA LADEN
# =========================
@st.cache_data(ttl=3600, show_spinner=False)
def laad_openchargemap_data():
    try:
        response = requests.get(OCM_URL, params=OCM_PARAMS, headers=HEADERS, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        return None, f"Fout bij API-aanroep: {e}"

    data = response.json()
    df = pd.json_normalize(data)

    gewenste_kolommen = [
        "ID",
        "AddressInfo.Title",
        "AddressInfo.Town",
        "AddressInfo.StateOrProvince",
        "AddressInfo.Latitude",
        "AddressInfo.Longitude",
        "AddressInfo.CountryID",
        "NumberOfPoints",
        "UsageTypeID",
        "StatusTypeID",
        "Connections"
    ]

    bestaande_kolommen = [col for col in gewenste_kolommen if col in df.columns]
    df = df[bestaande_kolommen].copy()

    if "AddressInfo.Latitude" not in df.columns or "AddressInfo.Longitude" not in df.columns:
        return None, "Latitude of Longitude ontbreken in de OpenChargeMap-data."

    df = df.dropna(subset=["AddressInfo.Latitude", "AddressInfo.Longitude"]).copy()

    df = df[
        df["AddressInfo.Latitude"].between(50.7, 53.7) &
        df["AddressInfo.Longitude"].between(3.1, 7.3)
    ].copy()

    if "NumberOfPoints" in df.columns:
        df["NumberOfPoints"] = pd.to_numeric(df["NumberOfPoints"], errors="coerce").fillna(0)
    else:
        df["NumberOfPoints"] = 0

    if "AddressInfo.StateOrProvince" in df.columns:
        df["Provincie_raw"] = df["AddressInfo.StateOrProvince"].astype(str).str.strip()
        df["Provincie"] = df["AddressInfo.StateOrProvince"].apply(schoon_provincie_naam)
    else:
        df["Provincie_raw"] = None
        df["Provincie"] = None

    df["Provincie_final"] = df["Provincie"].where(df["Provincie"].isin(OFFICIELE_PROVINCIES))

    df["Provincie_final"] = df.apply(
        lambda row: row["Provincie_final"]
        if pd.notna(row["Provincie_final"])
        else bepaal_provincie_op_coordinaten(row["AddressInfo.Latitude"], row["AddressInfo.Longitude"]),
        axis=1
    )

    if "Connections" in df.columns:
        df["MaxPowerKW"] = df["Connections"].apply(get_max_power_kw)
        df["Snellader"] = df["MaxPowerKW"] >= 50
    else:
        df["MaxPowerKW"] = 0.0
        df["Snellader"] = False

    return df, None

@st.cache_data(ttl=3600, show_spinner=False)
def laad_laadpaal_csv():
    df = pd.read_csv(LAADPAAL_CSV_PATH)

    df = veilige_datetime(df, ["Started", "Ended"])
    df = veilige_numeric(df, ["TotalEnergy", "ConnectedTime", "ChargeTime", "MaxPower"])

    if "TotalEnergy" in df.columns:
        df["TotalEnergy_kWh"] = df["TotalEnergy"] / 1000

    if "Started" in df.columns:
        df["Start_datum"] = df["Started"].dt.date
        df["Start_uur"] = df["Started"].dt.hour
        df["Weekdag"] = df["Started"].dt.day_name()

    if "ConnectedTime" in df.columns and "ChargeTime" in df.columns:
        df["Niet_laden_maar_bezet"] = df["ConnectedTime"] - df["ChargeTime"]

    return df

@st.cache_data(ttl=3600, show_spinner=False)
def laad_charging_pkl():
    df = pd.read_pickle(CHARGING_PKL_PATH)

    if "start_time" in df.columns:
        df["start_time"] = pd.to_datetime(df["start_time"], errors="coerce")
        df["start_datum"] = df["start_time"].dt.date
        df["start_uur"] = df["start_time"].dt.hour
        df["Weekdag"] = df["start_time"].dt.day_name()

    numerieke_kolommen = [
        "charging_duration",
        "max_charging_power [kW]",
        "energy_delivered [kWh]",
        "N_phases"
    ]
    df = veilige_numeric(df, numerieke_kolommen)

    return df

@st.cache_data(ttl=3600, show_spinner=False)
def laad_cars_pkl():
    df = pd.read_pickle(CARS_PKL_PATH)

    datum_kolommen = [
        "datum_tenaamstelling_dt",
        "datum_eerste_toelating_dt",
        "vervaldatum_apk_dt"
    ]
    df = veilige_datetime(df, datum_kolommen)

    if "datum_tenaamstelling_dt" in df.columns:
        df["jaar_tenaamstelling"] = df["datum_tenaamstelling_dt"].dt.year

    if "merk" in df.columns:
        df["merk"] = df["merk"].astype(str).str.strip()

    if "handelsbenaming" in df.columns:
        df["handelsbenaming"] = df["handelsbenaming"].astype(str).str.strip()

    return df

@st.cache_data(ttl=3600, show_spinner=False)
def laad_ev_percentage_csv():
    df = pd.read_csv(EV_PERCENTAGE_CSV_PATH)
    df.columns = [col.strip() for col in df.columns]

    gemeente_col = "Gemeentenaam"
    ev_col = "% autobezitters met stekkerauto (%)"

    if gemeente_col not in df.columns or ev_col not in df.columns:
        raise ValueError("Kolommen 'Gemeentenaam' en '% autobezitters met stekkerauto (%)' zijn niet gevonden.")

    df = df[[gemeente_col, ev_col]].copy()

    df[ev_col] = (
        df[ev_col]
        .astype(str)
        .str.replace("%", "", regex=False)
        .str.replace(",", ".", regex=False)
        .str.strip()
    )
    df[ev_col] = pd.to_numeric(df[ev_col], errors="coerce")

    df["Plaats_norm"] = df[gemeente_col].apply(normaliseer_plaatsnaam)

    return df

# =========================
# DATA INLADEN
# =========================
df_ocm, error = laad_openchargemap_data()

if error:
    st.error(error)
    st.stop()

try:
    df_laad_csv = laad_laadpaal_csv()
except Exception as e:
    df_laad_csv = None
    st.warning(f"Kon laadpaaldata.csv niet laden: {e}")

try:
    df_charging = laad_charging_pkl()
except Exception as e:
    df_charging = None
    st.warning(f"Kon Charging_data.pkl niet laden: {e}")

try:
    df_cars = laad_cars_pkl()
except Exception as e:
    df_cars = None
    st.warning(f"Kon cars.pkl niet laden: {e}")

try:
    df_ev_percent = laad_ev_percentage_csv()
except Exception as e:
    df_ev_percent = None
    st.warning(f"Kon table_EV%.csv niet laden: {e}")

geojson_data = laad_geojson_bestand()
geojson_naamveld = vind_geojson_naamveld(geojson_data)

# =========================
# TABS
# =========================
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "Infrastructuur",
    "Laadgedrag",
    "Auto's",
    "Drukanalyse",
    "EV vs Laadpalen"
])

# =========================
# TAB 1 INFRASTRUCTUUR
# =========================
with tab1:
    st.subheader("Laadinfrastructuur in Nederland")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Laadlocaties", len(df_ocm))
    col2.metric("Totaal laadpunten", int(df_ocm["NumberOfPoints"].fillna(0).sum()))
    col3.metric("Snelladers", int(df_ocm["Snellader"].sum()))
    col4.metric("Provincies toegewezen", int(df_ocm["Provincie_final"].nunique()))

    provincie_keuze = st.selectbox(
        "Kies provincie",
        ["Alle provincies"] + OFFICIELE_PROVINCIES,
        key="prov_filter_ocm"
    )

    df_ocm_filtered = df_ocm.copy()
    if provincie_keuze != "Alle provincies":
        df_ocm_filtered = df_ocm_filtered[df_ocm_filtered["Provincie_final"] == provincie_keuze]

    st.write(f"Aantal resultaten op kaart: **{len(df_ocm_filtered)}**")

    kaart_df = df_ocm_filtered[
        [
            "AddressInfo.Latitude",
            "AddressInfo.Longitude",
            "AddressInfo.Title",
            "AddressInfo.Town",
            "Provincie_final",
            "NumberOfPoints",
            "MaxPowerKW",
            "Snellader"
        ]
    ].dropna(subset=["AddressInfo.Latitude", "AddressInfo.Longitude"]).copy()

    kaart_type = st.radio(
        "Kaartweergave",
        ["Laadlocaties", "Heatmap laadlocaties"],
        horizontal=True
    )

    m = maak_basiskaart()
    voeg_geojson_grens_toe(m, geojson_data)

    if kaart_type == "Laadlocaties":
        marker_data = []
        for _, row in kaart_df.iterrows():
            popup_text = (
                f"<b>{row.get('AddressInfo.Title', 'Onbekende laadlocatie')}</b><br>"
                f"Plaats: {row.get('AddressInfo.Town', 'Onbekend')}<br>"
                f"Provincie: {row.get('Provincie_final', 'Onbekend')}<br>"
                f"Aantal laadpunten: {row.get('NumberOfPoints', 'Onbekend')}<br>"
                f"Max power (kW): {round(row.get('MaxPowerKW', 0), 1)}<br>"
                f"Snellader: {'Ja' if row.get('Snellader', False) else 'Nee'}"
            )
            marker_data.append([
                row["AddressInfo.Latitude"],
                row["AddressInfo.Longitude"],
                popup_text
            ])

        FastMarkerCluster(marker_data).add_to(m)
    else:
        heat_data = kaart_df[["AddressInfo.Latitude", "AddressInfo.Longitude"]].values.tolist()
        HeatMap(heat_data, radius=12, blur=18, min_opacity=0.35).add_to(m)

    st_folium(m, height=760, width=None, returned_objects=[])

    st.subheader("Laadlocaties per provincie")
    laadlocaties_per_provincie = (
        df_ocm.groupby("Provincie_final")
        .size()
        .reindex(OFFICIELE_PROVINCIES, fill_value=0)
    )
    st.bar_chart(laadlocaties_per_provincie)

    st.subheader("Laadpunten per provincie")
    laadpunten_per_provincie = (
        df_ocm.groupby("Provincie_final")["NumberOfPoints"]
        .sum()
        .reindex(OFFICIELE_PROVINCIES, fill_value=0)
    )
    st.bar_chart(laadpunten_per_provincie)

    st.subheader("Voorbeeld van infrastructuurdata")
    toon_kolommen_ocm = [
        "AddressInfo.Title",
        "AddressInfo.Town",
        "Provincie_final",
        "NumberOfPoints",
        "MaxPowerKW",
        "Snellader"
    ]
    st.dataframe(df_ocm_filtered[toon_kolommen_ocm].head(100), width="stretch")

# =========================
# TAB 2 LAADGEDRAG
# =========================
with tab2:
    st.subheader("Laadgedrag en gebruik")

    if df_laad_csv is None:
        st.info("laadpaaldata.csv kon niet worden geladen.")
    else:
        col1, col2, col3, col4 = st.columns(4)

        col1.metric("Aantal sessies", len(df_laad_csv))
        col2.metric(
            "Totale energie (kWh)",
            round(df_laad_csv["TotalEnergy_kWh"].sum(), 1)
            if "TotalEnergy_kWh" in df_laad_csv.columns else "Onbekend"
        )
        col3.metric(
            "Gem. max power",
            round(df_laad_csv["MaxPower"].mean(), 1)
            if "MaxPower" in df_laad_csv.columns else "Onbekend"
        )
        col4.metric(
            "Gem. energie per sessie",
            round(df_laad_csv["TotalEnergy_kWh"].mean(), 2)
            if "TotalEnergy_kWh" in df_laad_csv.columns else "Onbekend"
        )

        if "Start_uur" in df_laad_csv.columns:
            st.subheader("Startsessies per uur")
            sessies_per_uur = df_laad_csv["Start_uur"].value_counts().sort_index()
            st.bar_chart(sessies_per_uur)

        if "ConnectedTime" in df_laad_csv.columns and "ChargeTime" in df_laad_csv.columns:
            st.subheader("Verbonden tijd versus laadtijd")
            vergelijking = df_laad_csv[["ConnectedTime", "ChargeTime"]].dropna().head(500)
            st.line_chart(vergelijking)

            gem_bezet_zonder_laden = df_laad_csv["Niet_laden_maar_bezet"].dropna().mean()
            st.subheader("Niet laden maar wel bezet")
            st.write(f"Gemiddeld: **{round(gem_bezet_zonder_laden, 2)}**")

        st.subheader("Voorbeeld van laadpaaldata")
        st.dataframe(df_laad_csv.head(100), width="stretch")

    if df_charging is not None:
        st.subheader("Aanvullende laaddata")

        col1, col2, col3 = st.columns(3)
        col1.metric("Charging records", len(df_charging))
        col2.metric(
            "Totale energie (kWh)",
            round(df_charging["energy_delivered [kWh]"].sum(), 1)
            if "energy_delivered [kWh]" in df_charging.columns else "Onbekend"
        )
        col3.metric(
            "Gem. max charging power (kW)",
            round(df_charging["max_charging_power [kW]"].mean(), 2)
            if "max_charging_power [kW]" in df_charging.columns else "Onbekend"
        )

        if "start_uur" in df_charging.columns:
            st.subheader("Startmomenten per uur")
            charging_per_uur = df_charging["start_uur"].value_counts().sort_index()
            st.bar_chart(charging_per_uur)

# =========================
# TAB 3 AUTO'S
# =========================
with tab3:
    st.subheader("Auto's dataset")

    if df_cars is None:
        st.info("cars.pkl kon niet worden geladen.")
    else:
        col1, col2, col3 = st.columns(3)

        col1.metric("Aantal auto's", len(df_cars))
        col2.metric("Aantal merken", int(df_cars["merk"].nunique()) if "merk" in df_cars.columns else 0)
        col3.metric("Aantal modellen", int(df_cars["handelsbenaming"].nunique()) if "handelsbenaming" in df_cars.columns else 0)

        if "merk" in df_cars.columns:
            st.subheader("Top 10 merken")
            top_merken = df_cars["merk"].value_counts().head(10)
            st.bar_chart(top_merken)

        if "handelsbenaming" in df_cars.columns:
            st.subheader("Top 10 modellen")
            top_modellen = df_cars["handelsbenaming"].value_counts().head(10)
            st.bar_chart(top_modellen)

        if "jaar_tenaamstelling" in df_cars.columns:
            st.subheader("Registraties per jaar")
            registraties_per_jaar = df_cars["jaar_tenaamstelling"].value_counts().sort_index()
            st.line_chart(registraties_per_jaar)

        st.subheader("Voorbeeld van auto-data")
        relevante_kolommen = [
            col for col in [
                "kenteken",
                "merk",
                "handelsbenaming",
                "datum_tenaamstelling",
                "datum_tenaamstelling_dt",
                "jaar_tenaamstelling"
            ] if col in df_cars.columns
        ]
        if relevante_kolommen:
            st.dataframe(df_cars[relevante_kolommen].head(100), width="stretch")
        else:
            st.dataframe(df_cars.head(100), width="stretch")

# =========================
# TAB 4 DRUKANALYSE
# =========================
with tab4:
    st.subheader("Drukanalyse")

    laadpunten_per_provincie = (
        df_ocm.groupby("Provincie_final")["NumberOfPoints"]
        .sum()
        .reindex(OFFICIELE_PROVINCIES, fill_value=0)
    )

    laadlocaties_per_provincie = (
        df_ocm.groupby("Provincie_final")
        .size()
        .reindex(OFFICIELE_PROVINCIES, fill_value=0)
    )

    st.markdown(
        """
        Deze analyse laat de infrastructuurdruk per provincie zien op basis van het aantal laadpunten en laadlocaties.
        Voor een volledig zuivere regionale vraag-aanbodanalyse is ook regionale voertuigverdeling nodig.
        """
    )

    df_druk = pd.DataFrame({
        "Aantal_laadlocaties": laadlocaties_per_provincie,
        "Aantal_laadpunten": laadpunten_per_provincie
    })

    max_laadpunten = df_druk["Aantal_laadpunten"].max()
    max_laadlocaties = df_druk["Aantal_laadlocaties"].max()

    df_druk["Relatieve_druk_proxy_punten"] = df_druk["Aantal_laadpunten"].apply(
        lambda x: veilige_ratio(max_laadpunten, x)
    )
    df_druk["Relatieve_druk_proxy_locaties"] = df_druk["Aantal_laadlocaties"].apply(
        lambda x: veilige_ratio(max_laadlocaties, x)
    )

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Aantal laadpunten per provincie")
        st.bar_chart(df_druk["Aantal_laadpunten"])

    with col2:
        st.subheader("Relatieve drukproxy per provincie")
        st.bar_chart(df_druk["Relatieve_druk_proxy_punten"].fillna(0))

    if not df_druk["Relatieve_druk_proxy_punten"].dropna().empty:
        hoogste_druk = df_druk["Relatieve_druk_proxy_punten"].idxmax()
        st.write(f"Provincie met hoogste relatieve drukproxy: **{hoogste_druk}**")

    st.subheader("Laaddruk-proxy per plaats")

    df_plaats = df_ocm.copy()
    df_plaats = df_plaats[df_plaats["AddressInfo.Town"].notna()].copy()
    df_plaats["AddressInfo.Town"] = df_plaats["AddressInfo.Town"].astype(str).str.strip()
    df_plaats = df_plaats[df_plaats["AddressInfo.Town"] != ""]

    plaats_stats = (
        df_plaats.groupby(["AddressInfo.Town", "Provincie_final"], dropna=False)
        .agg(
            Aantal_laadlocaties=("ID", "count"),
            Aantal_laadpunten=("NumberOfPoints", "sum"),
            Aantal_snelladers=("Snellader", "sum"),
            Gem_max_vermogen_kw=("MaxPowerKW", "mean"),
            Gem_lat=("AddressInfo.Latitude", "mean"),
            Gem_lon=("AddressInfo.Longitude", "mean")
        )
        .reset_index()
    )

    plaats_stats["Aandeel_snelladers"] = (
        plaats_stats["Aantal_snelladers"] / plaats_stats["Aantal_laadlocaties"]
    ).fillna(0)

    plaats_stats["Score_schaarste_punten"] = minmax_omgekeerd(plaats_stats["Aantal_laadpunten"])
    plaats_stats["Score_schaarste_locaties"] = minmax_omgekeerd(plaats_stats["Aantal_laadlocaties"])
    plaats_stats["Score_schaarste_snelladers"] = minmax_omgekeerd(plaats_stats["Aandeel_snelladers"])

    plaats_stats["Laaddruk_proxy"] = (
        0.5 * plaats_stats["Score_schaarste_punten"] +
        0.3 * plaats_stats["Score_schaarste_locaties"] +
        0.2 * plaats_stats["Score_schaarste_snelladers"]
    )

    plaats_stats = plaats_stats.sort_values("Laaddruk_proxy", ascending=False)

    if not plaats_stats.empty:
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Plek met hoogste druk-proxy", plaats_stats.iloc[0]["AddressInfo.Town"])
        with col2:
            st.metric("Score", round(plaats_stats.iloc[0]["Laaddruk_proxy"], 3))

    st.subheader("Top 10 plekken met hoogste laaddruk-proxy")
    top10_plaatsen = plaats_stats.head(10).set_index("AddressInfo.Town")["Laaddruk_proxy"]
    st.bar_chart(top10_plaatsen)

    st.subheader("Tabel: laaddruk per plaats")
    st.dataframe(
        plaats_stats[
            [
                "AddressInfo.Town",
                "Provincie_final",
                "Aantal_laadlocaties",
                "Aantal_laadpunten",
                "Aantal_snelladers",
                "Aandeel_snelladers",
                "Gem_max_vermogen_kw",
                "Laaddruk_proxy"
            ]
        ].head(50),
        width="stretch"
    )

    if geojson_data is not None and geojson_naamveld is not None:
        st.subheader("Drukkaart per provincie")

        df_choro = df_druk.reset_index().rename(columns={"index": "Provincie_final"})
        df_choro["Provincie_geojson"] = df_choro["Provincie_final"]

        m_druk = maak_basiskaart()

        try:
            folium.Choropleth(
                geo_data=geojson_data,
                data=df_choro,
                columns=["Provincie_geojson", "Relatieve_druk_proxy_punten"],
                key_on=f"feature.properties.{geojson_naamveld}",
                fill_color="YlOrRd",
                fill_opacity=0.7,
                line_opacity=0.3,
                nan_fill_color="lightgray",
                legend_name="Relatieve drukproxy"
            ).add_to(m_druk)

            voeg_geojson_grens_toe(m_druk, geojson_data)
            st_folium(m_druk, height=650, width=None, returned_objects=[])
        except Exception:
            st.info("De provinciekaart kon niet exact worden getekend met het huidige GeoJSON-bestand.")
    else:
        st.info("Voor een exacte provincie-drukkaart kun je een bestand 'nl_provinces.geojson' toevoegen.")

    st.subheader("Tabel drukanalyse")
    st.dataframe(df_druk, width="stretch")

# =========================
# TAB 5 EV VS LAADPALEN
# =========================
with tab5:
    st.subheader("Vergelijking: EV-aandeel vs laadpalen")

    if df_ev_percent is None:
        st.info("table_EV%.csv kon niet worden geladen.")
    else:
        df_vergelijk = df_ocm.copy()
        df_vergelijk = df_vergelijk[df_vergelijk["AddressInfo.Town"].notna()].copy()
        df_vergelijk["AddressInfo.Town"] = df_vergelijk["AddressInfo.Town"].astype(str).str.strip()
        df_vergelijk = df_vergelijk[df_vergelijk["AddressInfo.Town"] != ""]
        df_vergelijk["Plaats_norm"] = df_vergelijk["AddressInfo.Town"].apply(normaliseer_plaatsnaam)

        plaats_laad = (
            df_vergelijk.groupby(["Plaats_norm", "AddressInfo.Town", "Provincie_final"], dropna=False)
            .agg(
                Aantal_laadlocaties=("ID", "count"),
                Aantal_laadpunten=("NumberOfPoints", "sum"),
                Aantal_snelladers=("Snellader", "sum"),
                Gem_lat=("AddressInfo.Latitude", "mean"),
                Gem_lon=("AddressInfo.Longitude", "mean"),
                Gem_max_vermogen_kw=("MaxPowerKW", "mean")
            )
            .reset_index()
        )

        df_merge = df_ev_percent.merge(
            plaats_laad,
            on="Plaats_norm",
            how="left"
        )

        df_match = df_merge.dropna(subset=["Gem_lat", "Gem_lon"]).copy()

        ev_col = "% autobezitters met stekkerauto (%)"

        if df_match.empty:
            st.warning("Er zijn geen matches gevonden tussen gemeentenaam en plaatsnaam in OpenChargeMap.")
        else:
            df_match["EV_index"] = schaal_0_1(df_match[ev_col])
            df_match["Laadpunten_index"] = schaal_0_1(df_match["Aantal_laadpunten"])
            df_match["Laadlocaties_index"] = schaal_0_1(df_match["Aantal_laadlocaties"])

            df_match["Spanningsscore"] = df_match["EV_index"] - df_match["Laadpunten_index"]

            df_match["Laadpunten_per_EV_pct"] = df_match.apply(
                lambda row: row["Aantal_laadpunten"] / row[ev_col]
                if pd.notna(row["Aantal_laadpunten"]) and pd.notna(row[ev_col]) and row[ev_col] != 0
                else None,
                axis=1
            )

            col1, col2, col3 = st.columns(3)
            col1.metric("Gemeenten in EV-bestand", len(df_ev_percent))
            col2.metric("Matches met laadpaaldata", len(df_match))
            col3.metric("Niet gematcht", len(df_ev_percent) - len(df_match))

            st.markdown("""
            **Uitleg vergelijking**
            - **EV-aandeel** = percentage autobezitters met stekkerauto
            - **Laadpunten** = totaal aantal laadpunten uit OpenChargeMap
            - **Spanningsscore** = relatief hoog EV-aandeel minus relatief veel laadpunten
            → een **hogere score** betekent: relatief meer EV's dan laadpunten
            """)

            kaart_optie = st.radio(
                "Toon op kaart",
                ["EV-aandeel", "Laadpunten", "Spanningsscore"],
                horizontal=True
            )

            m_ev = maak_basiskaart()
            voeg_geojson_grens_toe(m_ev, geojson_data)

            for _, row in df_match.iterrows():
                plaatsnaam = row.get("Gemeentenaam", "Onbekend")
                laadpunten = row.get("Aantal_laadpunten", 0)
                laadlocaties = row.get("Aantal_laadlocaties", 0)
                ev_pct = row.get(ev_col, 0)
                spanningsscore = row.get("Spanningsscore", 0)

                if kaart_optie == "EV-aandeel":
                    waarde = ev_pct
                    radius = 5 + (float(ev_pct) * 2 if pd.notna(ev_pct) else 0)
                elif kaart_optie == "Laadpunten":
                    waarde = laadpunten
                    radius = 5 + min(float(laadpunten), 100) * 0.25 if pd.notna(laadpunten) else 5
                else:
                    waarde = spanningsscore
                    radius = 6 + abs(float(spanningsscore)) * 15 if pd.notna(spanningsscore) else 6

                popup = (
                    f"<b>{plaatsnaam}</b><br>"
                    f"EV-aandeel: {round(ev_pct, 2)}%<br>"
                    f"Laadpunten: {int(laadpunten) if pd.notna(laadpunten) else 0}<br>"
                    f"Laadlocaties: {int(laadlocaties) if pd.notna(laadlocaties) else 0}<br>"
                    f"Snelladers: {int(row.get('Aantal_snelladers', 0)) if pd.notna(row.get('Aantal_snelladers', 0)) else 0}<br>"
                    f"Provincie: {row.get('Provincie_final', 'Onbekend')}<br>"
                    f"Spanningsscore: {round(spanningsscore, 3)}"
                )

                folium.CircleMarker(
                    location=[row["Gem_lat"], row["Gem_lon"]],
                    radius=radius,
                    popup=popup,
                    tooltip=f"{plaatsnaam}: {round(waarde, 2) if pd.notna(waarde) else 0}",
                    fill=True,
                    fill_opacity=0.7,
                    color="#333333",
                    weight=1
                ).add_to(m_ev)

            st_folium(m_ev, height=720, width=None, returned_objects=[])

            st.subheader("Top 15 gemeenten met hoogste EV-aandeel")
            top_ev = df_match.sort_values(ev_col, ascending=False)[
                ["Gemeentenaam", ev_col, "Aantal_laadpunten", "Spanningsscore"]
            ].head(15)
            st.dataframe(top_ev, width="stretch")

            st.subheader("Top 15 gemeenten met meeste laadpunten")
            top_laad = df_match.sort_values("Aantal_laadpunten", ascending=False)[
                ["Gemeentenaam", ev_col, "Aantal_laadpunten", "Spanningsscore"]
            ].head(15)
            st.dataframe(top_laad, width="stretch")

            st.subheader("Top 15 gemeenten met hoogste relatieve spanning")
            top_spanning = df_match.sort_values("Spanningsscore", ascending=False)[
                ["Gemeentenaam", ev_col, "Aantal_laadpunten", "Aantal_laadlocaties", "Spanningsscore"]
            ].head(15)
            st.dataframe(top_spanning, width="stretch")

            st.subheader("Complete vergelijkingstabel")
            st.dataframe(
                df_match[
                    [
                        "Gemeentenaam",
                        ev_col,
                        "AddressInfo.Town",
                        "Provincie_final",
                        "Aantal_laadpunten",
                        "Aantal_laadlocaties",
                        "Aantal_snelladers",
                        "Gem_max_vermogen_kw",
                        "Laadpunten_per_EV_pct",
                        "Spanningsscore"
                    ]
                ].sort_values("Spanningsscore", ascending=False),
                width="stretch"
            )