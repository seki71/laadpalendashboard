import streamlit as st
import requests
import pandas as pd
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
import os

# =========================
# PAGINA-INSTELLINGEN
# =========================
st.set_page_config(page_title="EV Dashboard", layout="wide")

st.title("Dashboard Elektrisch Vervoer")
st.subheader("OpenChargeMap, laadpaalgebruik en auto's in Nederland")

# =========================
# BESTANDSPADEN
# =========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

LAADPAAL_CSV_PATH = os.path.join(BASE_DIR, "laadpaaldata.csv")
CHARGING_PKL_PATH = os.path.join(BASE_DIR, "Charging_data.pkl")
CARS_PKL_PATH = os.path.join(BASE_DIR, "cars.pkl")

# =========================
# API INSTELLINGEN
# =========================
API_KEY = "b947a33a-1124-4c7d-a0e6-5ef2e8e51c0a"

url = "https://api.openchargemap.io/v3/poi"

params = {
    "output": "json",
    "countrycode": "NL",
    "maxresults": 500,
    "compact": True,
    "verbose": False,
    "key": API_KEY
}

headers = {
    "User-Agent": "KoenEVDashboard/1.0"
}

# =========================
# FUNCTIES
# =========================
def schoon_provincie_naam(waarde):
    if pd.isna(waarde):
        return None

    waarde = str(waarde).strip()

    mapping = {
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
        "Noord-Brabant": "Noord-Brabant",

        "LB": "Limburg",
        "Limburg": "Limburg",

        "OV": "Overijssel",
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

    return mapping.get(waarde, waarde)


@st.cache_data
def laad_openchargemap_data():
    response = requests.get(url, params=params, headers=headers, timeout=30)

    if response.status_code != 200:
        return None, f"Fout bij API-aanroep: {response.status_code}"

    data = response.json()
    df = pd.json_normalize(data)

    kolommen = [
        "ID",
        "AddressInfo.Title",
        "AddressInfo.Town",
        "AddressInfo.StateOrProvince",
        "AddressInfo.Latitude",
        "AddressInfo.Longitude",
        "NumberOfPoints",
        "UsageTypeID",
        "StatusTypeID"
    ]

    bestaande_kolommen = [col for col in kolommen if col in df.columns]
    df = df[bestaande_kolommen].copy()
    df = df.dropna(subset=["AddressInfo.Latitude", "AddressInfo.Longitude"])

    df["Provincie"] = df["AddressInfo.StateOrProvince"].apply(schoon_provincie_naam)

    officiele_provincies = [
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

    df = df[df["Provincie"].isin(officiele_provincies)]

    return df, None


@st.cache_data
def laad_laadpaal_csv():
    df = pd.read_csv(LAADPAAL_CSV_PATH)

    if "Started" in df.columns:
        df["Started"] = pd.to_datetime(df["Started"], errors="coerce")
    if "Ended" in df.columns:
        df["Ended"] = pd.to_datetime(df["Ended"], errors="coerce")

    for kolom in ["TotalEnergy", "ConnectedTime", "ChargeTime", "MaxPower"]:
        if kolom in df.columns:
            df[kolom] = pd.to_numeric(df[kolom], errors="coerce")

    if "TotalEnergy" in df.columns:
        df["TotalEnergy_kWh"] = df["TotalEnergy"] / 1000

    if "Started" in df.columns:
        df["Start_datum"] = df["Started"].dt.date
        df["Start_uur"] = df["Started"].dt.hour

    if "ConnectedTime" in df.columns and "ChargeTime" in df.columns:
        df["Niet_laden_maar_bezet"] = df["ConnectedTime"] - df["ChargeTime"]

    return df


@st.cache_data
def laad_charging_pkl():
    df = pd.read_pickle(CHARGING_PKL_PATH)

    if "start_time" in df.columns:
        df["start_time"] = pd.to_datetime(df["start_time"], errors="coerce")
        df["start_datum"] = df["start_time"].dt.date
        df["start_uur"] = df["start_time"].dt.hour

    numerieke_kolommen = [
        "charging_duration",
        "max_charging_power [kW]",
        "energy_delivered [kWh]",
        "N_phases"
    ]

    for kolom in numerieke_kolommen:
        if kolom in df.columns:
            df[kolom] = pd.to_numeric(df[kolom], errors="coerce")

    return df


@st.cache_data
def laad_cars_pkl():
    df = pd.read_pickle(CARS_PKL_PATH)

    datum_kolommen = [
        "datum_tenaamstelling_dt",
        "datum_eerste_toelating_dt",
        "vervaldatum_apk_dt"
    ]

    for kolom in datum_kolommen:
        if kolom in df.columns:
            df[kolom] = pd.to_datetime(df[kolom], errors="coerce")

    if "datum_tenaamstelling_dt" in df.columns:
        df["jaar_tenaamstelling"] = df["datum_tenaamstelling_dt"].dt.year

    if "merk" in df.columns:
        df["merk"] = df["merk"].astype(str).str.strip()

    if "handelsbenaming" in df.columns:
        df["handelsbenaming"] = df["handelsbenaming"].astype(str).str.strip()

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

# =========================
# TABS
# =========================
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "OpenChargeMap",
    "Laadpaaldata CSV",
    "Charging_data.pkl",
    "Auto's dataset",
    "Gecombineerd overzicht"
])

# =========================
# TAB 1 OPENCHARGEMAP
# =========================
with tab1:
    st.subheader("Laadpalen in Nederland")

    col1, col2, col3 = st.columns(3)
    col1.metric("Aantal laadlocaties", len(df_ocm))
    col2.metric("Totaal laadpunten", int(df_ocm["NumberOfPoints"].fillna(0).sum()))
    col3.metric("Aantal plaatsen", int(df_ocm["AddressInfo.Town"].nunique()))

    provincie_keuze = st.selectbox(
        "Kies provincie",
        ["Alle provincies"] + sorted(df_ocm["Provincie"].dropna().unique()),
        key="prov_filter_ocm"
    )

    df_ocm_filtered = df_ocm.copy()
    if provincie_keuze != "Alle provincies":
        df_ocm_filtered = df_ocm_filtered[df_ocm_filtered["Provincie"] == provincie_keuze]

    st.write(f"Aantal resultaten: **{len(df_ocm_filtered)}**")

    m = folium.Map(location=[52.2, 5.3], zoom_start=7)
    marker_cluster = MarkerCluster().add_to(m)

    for _, row in df_ocm_filtered.iterrows():
        lat = row["AddressInfo.Latitude"]
        lon = row["AddressInfo.Longitude"]
        title = row.get("AddressInfo.Title", "Onbekende laadpaal")
        town = row.get("AddressInfo.Town", "Onbekende plaats")
        province = row.get("Provincie", "Onbekende provincie")
        points = row.get("NumberOfPoints", "Onbekend")

        popup_text = f"""
        <b>{title}</b><br>
        Plaats: {town}<br>
        Provincie: {province}<br>
        Aantal laadpunten: {points}
        """

        folium.Marker(
            location=[lat, lon],
            popup=folium.Popup(popup_text, max_width=300),
            tooltip=title
        ).add_to(marker_cluster)

    st_folium(m, width=1400, height=550)

    st.subheader("Aantal laadlocaties per provincie")
    laadpalen_per_provincie = df_ocm.groupby("Provincie").size().sort_values(ascending=False)
    st.bar_chart(laadpalen_per_provincie)

    toon_kolommen_ocm = [
        "AddressInfo.Title",
        "AddressInfo.Town",
        "Provincie",
        "NumberOfPoints",
        "AddressInfo.Latitude",
        "AddressInfo.Longitude"
    ]
    st.dataframe(df_ocm_filtered[toon_kolommen_ocm], width="stretch")

# =========================
# TAB 2 LAADPAALDATA CSV
# =========================
with tab2:
    st.subheader("Laadpaalgebruik uit laadpaaldata.csv")

    if df_laad_csv is None:
        st.info("laadpaaldata.csv kon niet worden geladen.")
    else:
        col1, col2, col3 = st.columns(3)

        col1.metric("Aantal sessies", len(df_laad_csv))

        if "TotalEnergy_kWh" in df_laad_csv.columns:
            col2.metric("Totale energie (kWh)", round(df_laad_csv["TotalEnergy_kWh"].sum(), 1))
        else:
            col2.metric("Totale energie (kWh)", "Onbekend")

        if "MaxPower" in df_laad_csv.columns:
            col3.metric("Gem. max power", round(df_laad_csv["MaxPower"].mean(), 1))
        else:
            col3.metric("Gem. max power", "Onbekend")

        if "Start_uur" in df_laad_csv.columns:
            st.subheader("Startsessies per uur")
            sessies_per_uur = df_laad_csv["Start_uur"].value_counts().sort_index()
            st.bar_chart(sessies_per_uur)

        if "TotalEnergy_kWh" in df_laad_csv.columns:
            st.subheader("Gemiddelde energie per sessie")
            st.write(round(df_laad_csv["TotalEnergy_kWh"].mean(), 2), "kWh")

        if "ConnectedTime" in df_laad_csv.columns and "ChargeTime" in df_laad_csv.columns:
            st.subheader("Verbonden tijd vs laadtijd")
            vergelijking = df_laad_csv[["ConnectedTime", "ChargeTime"]].dropna().head(200)
            st.line_chart(vergelijking)

        st.subheader("Voorbeeld van de laadpaaldata")
        st.dataframe(df_laad_csv.head(50), width="stretch")

# =========================
# TAB 3 CHARGING DATA PKL
# =========================
with tab3:
    st.subheader("Charging_data.pkl")

    if df_charging is None:
        st.info("Charging_data.pkl kon niet worden geladen.")
    else:
        col1, col2, col3 = st.columns(3)

        col1.metric("Aantal records", len(df_charging))

        if "energy_delivered [kWh]" in df_charging.columns:
            col2.metric(
                "Totale energie (kWh)",
                round(df_charging["energy_delivered [kWh]"].sum(), 1)
            )
        else:
            col2.metric("Totale energie (kWh)", "Onbekend")

        if "max_charging_power [kW]" in df_charging.columns:
            col3.metric(
                "Gem. max charging power",
                round(df_charging["max_charging_power [kW]"].mean(), 2)
            )
        else:
            col3.metric("Gem. max charging power", "Onbekend")

        if "start_uur" in df_charging.columns:
            st.subheader("Startsessies per uur")
            charging_per_uur = df_charging["start_uur"].value_counts().sort_index()
            st.bar_chart(charging_per_uur)

        if "energy_delivered [kWh]" in df_charging.columns:
            st.subheader("Top 100 energiesessies")
            st.bar_chart(df_charging["energy_delivered [kWh]"].dropna().head(100))

        st.subheader("Voorbeeld van Charging_data.pkl")
        st.dataframe(df_charging.head(50), width="stretch")

# =========================
# TAB 4 AUTO'S DATASET
# =========================
with tab4:
    st.subheader("Auto's dataset uit cars.pkl")

    if df_cars is None:
        st.info("cars.pkl kon niet worden geladen.")
    else:
        col1, col2, col3 = st.columns(3)

        col1.metric("Aantal auto's", len(df_cars))

        if "merk" in df_cars.columns:
            col2.metric("Aantal merken", int(df_cars["merk"].nunique()))
        else:
            col2.metric("Aantal merken", "Onbekend")

        if "handelsbenaming" in df_cars.columns:
            col3.metric("Aantal modellen", int(df_cars["handelsbenaming"].nunique()))
        else:
            col3.metric("Aantal modellen", "Onbekend")

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

        st.subheader("Voorbeeld van cars.pkl")
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
            st.dataframe(df_cars[relevante_kolommen].head(50), width="stretch")
        else:
            st.dataframe(df_cars.head(50), width="stretch")

# =========================
# TAB 5 GECOMBINEERD OVERZICHT
# =========================
with tab5:
    st.subheader("Gecombineerd overzicht van de datasets")

    col1, col2, col3 = st.columns(3)

    col1.metric("Laadlocaties OCM", len(df_ocm))
    col2.metric("Sessies laadpaaldata.csv", len(df_laad_csv) if df_laad_csv is not None else 0)
    col3.metric("Auto's in cars.pkl", len(df_cars) if df_cars is not None else 0)

    st.markdown("### Eerste interpretatie")
    st.write(
        """
        Dit dashboard combineert:
        - geografische laadpaallocaties uit OpenChargeMap,
        - gebruiksdata van laadsessies,
        - en een dataset met auto's.

        Hiermee kun je straks analyseren:
        - waar laadpalen zich bevinden,
        - hoe intensief laadpalen gebruikt worden,
        - en hoe de voertuigdata zich ontwikkelt.
        """
    )

    st.markdown("### Provincies in OpenChargeMap")
    st.write(sorted(df_ocm["Provincie"].dropna().unique()))

    if df_laad_csv is not None and "TotalEnergy_kWh" in df_laad_csv.columns:
        st.markdown("### Kerncijfer laadpaaldata.csv")
        st.write(
            f"Gemiddeld energieverbruik per sessie: **{round(df_laad_csv['TotalEnergy_kWh'].mean(), 2)} kWh**"
        )

    if df_charging is not None and "energy_delivered [kWh]" in df_charging.columns:
        st.markdown("### Kerncijfer Charging_data.pkl")
        st.write(
            f"Gemiddelde geleverde energie per record: **{round(df_charging['energy_delivered [kWh]'].mean(), 2)} kWh**"
        )

    if df_cars is not None and "merk" in df_cars.columns:
        st.markdown("### Meest voorkomende merk in cars.pkl")
        meest_voorkomende_merk = df_cars["merk"].value_counts().idxmax()
        aantal = df_cars["merk"].value_counts().max()
        st.write(f"**{meest_voorkomende_merk}** komt het vaakst voor met **{aantal}** registraties.")