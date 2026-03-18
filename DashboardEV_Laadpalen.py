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

# Optioneel:
# Voeg een GeoJSON met Nederlandse provincies toe voor een exacte provinciekaart.
# Verwachte bestandsnaam:
# nl_provinces.geojson
# De file moet een provincienaam bevatten in een property zoals:
# "name", "provincie", "province", "statnaam" of "naam"
NL_PROVINCES_GEOJSON_PATH = os.path.join(BASE_DIR, "nl_provinces.geojson")

# =========================
# API INSTELLINGEN
# =========================
API_KEY = "b947a33a-1124-4c7d-a0e6-5ef2e8e51c0a"
OCM_URL = "https://api.openchargemap.io/v3/poi"

OCM_PARAMS = {
    "output": "json",
    "countrycode": "NL",
    "maxresults": 1000,
    "compact": False,
    "verbose": False,
    "key": API_KEY
}

HEADERS = {
    "User-Agent": "KoenEVPressureDashboard/5.0"
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

# Simpele bounding boxes als fallback om ALLE laadlocaties alsnog
# toe te wijzen aan een van de 12 provincies.
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

    # Extra veiligheidsfilter zodat alleen Nederland in beeld blijft
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

    # Eerst provincie op naam
    df["Provincie_final"] = df["Provincie"].where(df["Provincie"].isin(OFFICIELE_PROVINCIES))

    # Daarna ontbrekende provincies opvullen met coordinaten
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

geojson_data = laad_geojson_bestand()
geojson_naamveld = vind_geojson_naamveld(geojson_data)

# =========================
# TABS
# =========================
tab1, tab2, tab3, tab4 = st.tabs([
    "Infrastructuur",
    "Laadgedrag",
    "Auto's",
    "Drukanalyse"
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