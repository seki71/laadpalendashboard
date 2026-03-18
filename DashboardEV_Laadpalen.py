import streamlit as st
import requests
import pandas as pd
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
import os

# =========================
# PAGINA
# =========================
st.set_page_config(page_title="EV Dashboard", layout="wide")

st.title("⚡ Dashboard Elektrisch Vervoer")
st.subheader("Analyse van laaddruk in Nederland")

# =========================
# API (GEWOON HARD CODE VOOR NU)
# =========================
API_KEY = "b947a33a-1124-4c7d-a0e6-5ef2e8e51c0a"

OCM_URL = "https://api.openchargemap.io/v3/poi"

PARAMS = {
    "output": "json",
    "countrycode": "NL",
    "maxresults": 1000,
    "compact": False,
    "verbose": True,
    "key": API_KEY
}

HEADERS = {"User-Agent": "KoenEVPressureDashboard/2.0"}

# =========================
# PADEN
# =========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

LAADPAAL_CSV_PATH = os.path.join(BASE_DIR, "laadpaaldata.csv")
CHARGING_PKL_PATH = os.path.join(BASE_DIR, "Charging_data.pkl")
CARS_PKL_PATH = os.path.join(BASE_DIR, "cars.pkl")

# =========================
# PROVINCIE FIX
# =========================
def clean_province(x):
    if pd.isna(x):
        return None
    x = str(x).strip()

    mapping = {
        "NH": "Noord-Holland",
        "ZH": "Zuid-Holland",
        "NB": "Noord-Brabant",
        "FL": "Flevoland",
        "UT": "Utrecht"
    }

    return mapping.get(x, x)

# =========================
# OPENCHARGEMAP
# =========================
@st.cache_data(ttl=3600)
def load_ocm():
    response = requests.get(OCM_URL, params=PARAMS, headers=HEADERS)
    data = response.json()

    df = pd.json_normalize(data)

    df = df[[
        "AddressInfo.Title",
        "AddressInfo.Town",
        "AddressInfo.StateOrProvince",
        "AddressInfo.Latitude",
        "AddressInfo.Longitude",
        "NumberOfPoints",
        "Connections"
    ]]

    df = df.dropna(subset=["AddressInfo.Latitude", "AddressInfo.Longitude"])

    df["Provincie"] = df["AddressInfo.StateOrProvince"].apply(clean_province)

    # 🔌 POWER (snelladers)
    def get_power(connections):
        try:
            return max([c.get("PowerKW", 0) for c in connections])
        except:
            return 0

    df["MaxPowerKW"] = df["Connections"].apply(get_power)

    df["Snellader"] = df["MaxPowerKW"] > 50

    return df

# =========================
# LAADPAALDATA
# =========================
@st.cache_data
def load_laad_csv():
    df = pd.read_csv(LAADPAAL_CSV_PATH)

    df["Started"] = pd.to_datetime(df["Started"], errors="coerce")
    df["Start_uur"] = df["Started"].dt.hour

    df["TotalEnergy_kWh"] = df["TotalEnergy"] / 1000

    df["Niet_laden"] = df["ConnectedTime"] - df["ChargeTime"]

    return df

# =========================
# CARS
# =========================
@st.cache_data
def load_cars():
    df = pd.read_pickle(CARS_PKL_PATH)

    df["datum_tenaamstelling_dt"] = pd.to_datetime(
        df["datum_tenaamstelling_dt"], errors="coerce"
    )
    df["jaar"] = df["datum_tenaamstelling_dt"].dt.year

    return df

# =========================
# DATA INLADEN
# =========================
df_ocm = load_ocm()
df_laad = load_laad_csv()
df_cars = load_cars()

# =========================
# TABS
# =========================
tab1, tab2, tab3, tab4 = st.tabs([
    "🗺️ Infrastructuur",
    "🔌 Gebruik",
    "🚗 Auto's",
    "🔥 Druk analyse"
])

# =========================
# TAB 1
# =========================
with tab1:
    st.subheader("Laadpalen in Nederland")

    col1, col2 = st.columns(2)

    col1.metric("Laadlocaties", len(df_ocm))
    col2.metric("Snelladers", int(df_ocm["Snellader"].sum()))

    m = folium.Map(location=[52.2, 5.3], zoom_start=7)
    cluster = MarkerCluster().add_to(m)

    for _, row in df_ocm.iterrows():
        folium.Marker(
            [row["AddressInfo.Latitude"], row["AddressInfo.Longitude"]],
            tooltip=row["AddressInfo.Title"]
        ).add_to(cluster)

    st_folium(m, height=500)

    st.subheader("Laadpalen per provincie")
    st.bar_chart(df_ocm["Provincie"].value_counts())

# =========================
# TAB 2
# =========================
with tab2:
    st.subheader("Gebruik laadpalen")

    st.metric("Aantal sessies", len(df_laad))

    st.subheader("Piekuren")
    st.bar_chart(df_laad["Start_uur"].value_counts().sort_index())

    st.subheader("Inefficiënt gebruik")
    st.write("Gemiddeld niet-laden:", round(df_laad["Niet_laden"].mean(), 2))

# =========================
# TAB 3
# =========================
with tab3:
    st.subheader("Elektrische auto's")

    st.metric("Aantal auto's", len(df_cars))

    st.subheader("Groei per jaar")
    st.line_chart(df_cars["jaar"].value_counts().sort_index())

# =========================
# TAB 4 (BELANGRIJKSTE)
# =========================
with tab4:
    st.subheader("🔥 Druk op laadpalen")

    laadpalen = df_ocm.groupby("Provincie")["NumberOfPoints"].sum()

    # proxy: auto's verdeeld over provincies
    totaal_autos = len(df_cars)

    df_pressure = laadpalen.to_frame(name="laadpunten")
    df_pressure["autos"] = totaal_autos / len(df_pressure)

    df_pressure["druk"] = df_pressure["autos"] / df_pressure["laadpunten"]

    st.subheader("Druk per provincie")
    st.bar_chart(df_pressure["druk"])

    hoogste = df_pressure["druk"].idxmax()

    st.success(f"🔥 Hoogste druk in: {hoogste}")

    st.markdown("""
    ### Interpretatie:
    - Druk = aantal auto's per laadpunt
    - Hogere waarde = meer kans op wachttijd
    """)

    st.dataframe(df_pressure)