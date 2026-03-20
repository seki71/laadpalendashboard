import os
import json
import requests
import pandas as pd
import streamlit as st
import folium
import plotly.express as px
import numpy as np

from folium.plugins import FastMarkerCluster, HeatMap
from streamlit_folium import st_folium

# =========================
# PAGINA-INSTELLINGEN
# =========================
st.set_page_config(page_title="Dashboard Elektrisch Vervoer", layout="wide")
st.title("Dashboard Elektrisch Vervoer")
st.subheader("Waar is de grootste druk op laadpalen in Nederland?")

# =========================
# BESTANDSPADEN
# =========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

LAADPAAL_CSV_PATH = os.path.join(BASE_DIR, "laadpaaldata.csv")
CHARGING_PKL_PATH = os.path.join(BASE_DIR, "Charging_data.pkl")
CARS_PKL_PATH = os.path.join(BASE_DIR, "cars.pkl")
EV_PERCENTAGE_CSV_PATH = os.path.join(BASE_DIR, "table_EV%.csv")

# Optionele GeoJSON-bestanden
NL_PROVINCES_GEOJSON_PATH = os.path.join(BASE_DIR, "nl_provinces.geojson")
NL_GEMEENTEN_GEOJSON_PATH = os.path.join(BASE_DIR, "nl_gemeenten.geojson")

# =========================
# API INSTELLINGEN
# =========================
API_KEY = "b947a33a-1124-4c7d-a0e6-5ef2e8e51c0a"
OCM_URL = "https://api.openchargemap.io/v3/poi"

OCM_PARAMS = {
    "output": "json",
    "countrycode": "NL",
    "maxresults": 5000,
    "compact": False,
    "verbose": False,
    "key": API_KEY
}

HEADERS = {
    "User-Agent": "KoenEVPressureDashboard/8.0"
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

NAAM_CORRECTIES = {
    "s gravenhage": "den haag",
    "'s gravenhage": "den haag",
    "the hague": "den haag",
    "s hertogenbosch": "den bosch",
    "'s hertogenbosch": "den bosch",
    "haarlemmermeer": "haarlemmermeer",
    "beekdaelen": "beekdaelen",
    "leeuwarden": "leeuwarden",
    "fryslan": "friesland",
    "fryslân": "friesland"
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

def laad_geojson_bestand(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def vind_geojson_naamveld(geojson_data, mogelijke_velden):
    if not geojson_data:
        return None

    features = geojson_data.get("features", [])
    if not features:
        return None

    properties = features[0].get("properties", {})
    for veld in mogelijke_velden:
        if veld in properties:
            return veld

    return None

def laad_provincie_geojson_bestand():
    return laad_geojson_bestand(NL_PROVINCES_GEOJSON_PATH)

def laad_gemeente_geojson_bestand():
    return laad_geojson_bestand(NL_GEMEENTEN_GEOJSON_PATH)

def vind_provincie_naamveld(geojson_data):
    mogelijke_velden = ["name", "provincie", "province", "statnaam", "naam", "PROVINCE", "NAME"]
    return vind_geojson_naamveld(geojson_data, mogelijke_velden)

def vind_gemeente_naamveld(geojson_data):
    mogelijke_velden = ["name", "naam", "gemeente", "gemeentenaam", "GM_NAAM", "statnaam", "NAME"]
    return vind_geojson_naamveld(geojson_data, mogelijke_velden)

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

def normaliseer_naam(naam):
    if pd.isna(naam):
        return None
    naam = str(naam).strip().lower()
    naam = naam.replace("-", " ")
    naam = naam.replace("'", "")
    naam = " ".join(naam.split())
    return NAAM_CORRECTIES.get(naam, naam)

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

    df = df[df[gemeente_col].notna()].copy()
    df = df[df[gemeente_col].astype(str).str.strip() != ""].copy()
    df["Gemeentenaam"] = df["Gemeentenaam"].astype(str).str.strip()
    df["Gemeente_norm"] = df["Gemeentenaam"].apply(normaliseer_naam)

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
except Exception:
    df_ev_percent = None

geojson_data = laad_provincie_geojson_bestand()
geojson_naamveld = vind_provincie_naamveld(geojson_data)

gemeente_geojson_data = laad_gemeente_geojson_bestand()
gemeente_geojson_naamveld = vind_gemeente_naamveld(gemeente_geojson_data)

# =========================
# TABS
# =========================

tab1, tab2, tab3 = st.tabs([
    "Nederlandse kaart",
    "Laadgedrag",
    "Drukanalyse",
])

# =========================
# TAB 1 INFRASTRUCTUUR
# =========================


with tab1:
    st.subheader("Laadpalen in Nederland")

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
# TAB 3 DRUKANALYSE
# =========================
with tab3:
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

# =========================
# TAB 3 EV VS LAADPALEN
# =========================



    if df_ev_percent is None:
        st.info("table_EV%.csv kon niet worden geladen.")
    else:
        ev_col = "% autobezitters met stekkerauto (%)"

        # Samenvatting laadpaaldata per plaats
        df_vergelijk = df_ocm.copy()
        df_vergelijk = df_vergelijk[df_vergelijk["AddressInfo.Town"].notna()].copy()
        df_vergelijk["AddressInfo.Town"] = df_vergelijk["AddressInfo.Town"].astype(str).str.strip()
        df_vergelijk = df_vergelijk[df_vergelijk["AddressInfo.Town"] != ""]
        df_vergelijk["Plaats_norm"] = df_vergelijk["AddressInfo.Town"].apply(normaliseer_naam)

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
            left_on="Gemeente_norm",
            right_on="Plaats_norm",
            how="left"
        )

        df_match = df_merge.dropna(subset=["Aantal_laadpunten"]).copy()

        if not df_match.empty:
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
        else:
            df_match["Spanningsscore"] = pd.Series(dtype=float)
            df_match["Laadpunten_per_EV_pct"] = pd.Series(dtype=float)





        st.subheader("Kaart: EV-aandeel per gemeente")

        if gemeente_geojson_data is not None and gemeente_geojson_naamveld is not None:
            df_kaart = df_ev_percent.copy()
            df_kaart["Gemeente_geojson_koppeling"] = df_kaart["Gemeentenaam"].apply(normaliseer_naam)

            for feature in gemeente_geojson_data["features"]:
                props = feature.get("properties", {})
                originele_naam = props.get(gemeente_geojson_naamveld)
                props["gemeente_koppeling"] = normaliseer_naam(originele_naam) if originele_naam else None

            m_ev_choro = maak_basiskaart()

            choropleth = folium.Choropleth(
                geo_data=gemeente_geojson_data,
                data=df_kaart,
                columns=["Gemeente_geojson_koppeling", ev_col],
                key_on="feature.properties.gemeente_koppeling",
                fill_color="YlGnBu",
                fill_opacity=0.75,
                line_opacity=0.35,
                nan_fill_color="lightgray",
                nan_fill_opacity=0.4,
                legend_name="Aandeel autobezitters met stekkerauto (%)"
            ).add_to(m_ev_choro)

            ev_lookup = dict(zip(df_kaart["Gemeente_geojson_koppeling"], df_kaart[ev_col]))

            folium.GeoJson(
                gemeente_geojson_data,
                name="Gemeenten",
                style_function=lambda _: {
                    "fillColor": "#00000000",
                    "color": "#555555",
                    "weight": 0.5
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=[gemeente_geojson_naamveld, "gemeente_koppeling"],
                    aliases=["Gemeente:", "Koppeling:"],
                    labels=True,
                    sticky=False
                ),
                highlight_function=lambda _: {
                    "weight": 2,
                    "color": "#222222"
                }
            ).add_to(m_ev_choro)

            st_folium(m_ev_choro, height=720, width=None, returned_objects=[])

            st.caption("De kaartkleur is gebaseerd op het EV-aandeel per gemeente.")
        else:
            st.info("Voor deze kaart heb je een bestand 'nl_gemeenten.geojson' nodig in dezelfde map als je Python-bestand.")
    with tab3:
        st.subheader("Scatterplot: laadpalen vs EV-aandeel")

    scatter_df = df_match[
        ["Gemeentenaam", ev_col, "Aantal_laadpunten", "Aantal_laadlocaties", "Spanningsscore"]
    ].dropna().copy()

    if not scatter_df.empty and len(scatter_df) >= 3:
        fig = px.scatter(
            scatter_df,
            x="Aantal_laadpunten",
            y=ev_col,
            hover_name="Gemeentenaam",
            hover_data={
                "Aantal_laadpunten": True,
                "Aantal_laadlocaties": True,
                "Spanningsscore": ':.3f'
            },
            title="Aantal laadpalen tegenover aandeel elektrische auto's"
        )

        # Regressielijn
        x = scatter_df["Aantal_laadpunten"].values
        y = scatter_df[ev_col].values

        slope, intercept = np.polyfit(x, y, 1)
        x_line = np.linspace(x.min(), x.max(), 100)
        y_line = slope * x_line + intercept

        fig.add_scatter(
            x=x_line,
            y=y_line,
            mode="lines",
            name="Regressielijn"
        )

        # Correlatie en statistiek
        r = np.corrcoef(x, y)[0, 1]
        r_squared = r ** 2

        n = len(x)
        if abs(r) < 1:
            t_stat = r * np.sqrt((n - 2) / (1 - r**2))
            p_value = 2 * (1 - 0.5 * (1 + __import__("math").erf(abs(t_stat) / np.sqrt(2))))
        else:
            p_value = 0.0

        fig.update_layout(
            xaxis_title="Aantal laadpalen",
            yaxis_title="Aandeel elektrische auto's (%)",
            height=600
        )

        st.plotly_chart(fig, use_container_width=True)

        st.markdown("### Regressie-analyse")
        st.write(f"**Correlatie (r):** {r:.3f}")
        st.write(f"**R²:** {r_squared:.3f}")
        st.write(f"**p-waarde (benaderd):** {p_value:.5f}")

        if p_value < 0.05:
            st.success("Er is een statistisch significante relatie.")
        else:
            st.warning("Er is geen statistisch significante relatie.")

        if r > 0:
            st.write("Positieve relatie: meer laadpalen hangt samen met een hoger EV-aandeel.")
        else:
            st.write("Negatieve relatie: meer laadpalen hangt samen met een lager EV-aandeel.")
    else:
        st.info("Onvoldoende data om een scatterplot met regressielijn te maken.")