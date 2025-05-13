# MindGames Inventory Intelligence (Streamlit)
# Dual Mode: CSV Upload or NetSuite API (Fallback Ready)

import streamlit as st
import pandas as pd
import sqlite3
from pathlib import Path
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from pytrends.request import TrendReq
from pytrends.exceptions import TooManyRequestsError
import time

# --- PAGE SETUP ---
st.set_page_config(page_title="MindGames Inventory Dashboard", layout="wide", page_icon="🧠")
st.markdown("""
    <style>
        .block-container {padding: 2rem 1rem; max-width: 1400px; margin: auto;}
        h1, h2, h3 {color: #1E293B; font-family: 'Segoe UI', sans-serif;}
        .metric-box {background: linear-gradient(to right, #6366F1, #3B82F6); color: white;
                    padding: 1rem; border-radius: 12px; text-align: center;
                    box-shadow: 0 4px 14px rgba(0,0,0,0.1);}
        .section {margin-top: 2rem; margin-bottom: 1rem; border-bottom: 2px solid #E5E7EB; padding-bottom: 0.5rem;}
    </style>
""", unsafe_allow_html=True)

# --- SIDEBAR ---
st.sidebar.header("Upload Files or Filter")
inventory_file = st.sidebar.file_uploader("Upload Inventory CSV (item_name, price, cost_price, units_left, units_sold, reorder_point, category, supplier, location)", type="csv", key="inv_csv")
sales_file = st.sidebar.file_uploader("Upload Sales CSV (item_name, Date, Units_Sold, location)", type="csv", key="sales_csv")
sku_file = st.sidebar.file_uploader("Optional: Upload SKU List (CSV one column)", type="csv")
trend_keyword = st.sidebar.text_input("Google Trends Keyword", value="Magic Cards")
region_scope = st.sidebar.radio("Region", ["All", "CA", "US"], index=0)
forecast_days = st.sidebar.selectbox("Forecast Period (Days)", [30, 60, 90], index=0)

# Placeholder for NetSuite API (future-ready)
st.sidebar.markdown("---")
st.sidebar.text_input("NetSuite Token", value="", type="password", disabled=True)
st.sidebar.text_input("NetSuite Endpoint", value="https://example.suitetalk.api.netsuite.com", disabled=True)

sku_list = []
if sku_file:
    try:
        sku_df = pd.read_csv(sku_file, header=None)
        sku_list = sku_df[0].astype(str).tolist()
    except Exception as e:
        st.error(f"SKU file error: {e}")

# --- LOAD INVENTORY DATA ---
@st.cache_data(ttl=300)
def load_inventory():
    try:
        if inventory_file:
            df = pd.read_csv(inventory_file)
            expected_cols = {"item_name", "price", "cost_price", "units_left", "units_sold", "reorder_point", "category", "supplier", "location"}
            if not expected_cols.issubset(df.columns):
                missing = expected_cols - set(df.columns)
                raise ValueError(f"Missing columns in inventory file: {', '.join(missing)}")
        else:
            conn = sqlite3.connect("inventory.db")
            df = pd.read_sql_query("SELECT * FROM inventory", conn)
        return df
    except Exception as e:
        st.error(f"Inventory loading error: {e}")
        return pd.DataFrame(columns=[
            "item_name", "price", "cost_price", "units_left", "units_sold", "reorder_point", 
            "category", "supplier", "location"])

df = load_inventory()

# --- FILTERING ---
categories = df["category"].dropna().unique().tolist()
suppliers = df["supplier"].dropna().unique().tolist()
locations = df["location"].dropna().unique().tolist()
selected_categories = st.sidebar.multiselect("Filter by Category", categories)
selected_suppliers = st.sidebar.multiselect("Filter by Supplier", suppliers)
selected_locations = st.sidebar.multiselect("Filter by Location", locations)

@st.cache_data(ttl=300)
def filter_data(df):
    if region_scope == "CA":
        df = df[df["location"].str.contains("CA") | (df["location"] == "Main Warehouse")]
    elif region_scope == "US":
        df = df[df["location"].str.contains("US")]
    if selected_categories:
        df = df[df["category"].isin(selected_categories)]
    if selected_suppliers:
        df = df[df["supplier"].isin(selected_suppliers)]
    if selected_locations:
        df = df[df["location"].isin(selected_locations)]
    if sku_list:
        df = df[df["item_name"].astype(str).isin(sku_list)]
    return df

filtered_df = filter_data(df)

# --- KPIs ---
filtered_df["margin_%"] = ((filtered_df["price"] - filtered_df["cost_price"]) / filtered_df["price"] * 100).round(2)
filtered_df["stock_value"] = (filtered_df["cost_price"] * filtered_df["units_left"]).round(2)
filtered_df["inventory_turnover"] = (filtered_df["units_sold"] / (filtered_df["units_sold"] + filtered_df["units_left"] + 1e-9)).round(2)

# --- DISPLAY ---
st.title("🧠 MindGames Inventory Dashboard")
col1, col2, col3 = st.columns(3)
col1.markdown(f"<div class='metric-box'><h3>${filtered_df['stock_value'].sum():,.2f}</h3><p>Total Stock Value</p></div>", unsafe_allow_html=True)
col2.markdown(f"<div class='metric-box'><h3>{filtered_df['margin_%'].mean():.2f}%</h3><p>Avg Margin</p></div>", unsafe_allow_html=True)
col3.markdown(f"<div class='metric-box'><h3>{filtered_df['inventory_turnover'].mean():.2f}</h3><p>Inventory Turnover</p></div>", unsafe_allow_html=True)

st.markdown("<div class='section'><h2>📃 Inventory</h2></div>", unsafe_allow_html=True)
st.dataframe(filtered_df, use_container_width=True)

# --- LOW STOCK ---
low_stock = filtered_df[filtered_df["units_left"] < filtered_df["reorder_point"]]
if not low_stock.empty:
    st.warning("Items below reorder point:")
    st.dataframe(low_stock[["item_name", "location", "units_left", "reorder_point"]])

# --- GOOGLE TRENDS ---
@st.cache_data(ttl=86400)
def fetch_google_trends(keyword, timeframe='today 3-m', retries=3):
    pytrends = TrendReq(hl='en-US', tz=360)
    for i in range(retries):
        try:
            pytrends.build_payload([keyword], timeframe=timeframe)
            data = pytrends.interest_over_time()
            return data.reset_index()[['date', keyword]].rename(columns={'date': 'Date', keyword: 'Google_Trend'})
        except TooManyRequestsError:
            time.sleep(5 * (i + 1))
    return pd.DataFrame()

trend_data = fetch_google_trends(trend_keyword)
if not trend_data.empty:
    st.line_chart(trend_data.set_index("Date"))

# --- SALES FORECASTING ---
if sales_file:
    try:
        sales_data = pd.read_csv(sales_file, parse_dates=["Date"])
        sales_data = sales_data.sort_values(["item_name", "Date"])
        st.markdown("<div class='section'><h2>📊 Forecasting & Demand Planning</h2></div>", unsafe_allow_html=True)

        forecast_rows = []
        for sku in sales_data["item_name"].unique():
            for location in sales_data["location"].unique():
                df_item = sales_data[(sales_data["item_name"] == sku) & (sales_data["location"] == location)]
                ts = df_item.set_index("Date")["Units_Sold"].resample("D").sum().fillna(0)
                if len(ts) >= 30:
                    model = ExponentialSmoothing(ts, trend="add", seasonal=None).fit()
                    forecast = model.forecast(forecast_days)
                    forecast_rows.append({
                        "item_name": sku,
                        "location": location,
                        f"forecast_next_{forecast_days}": forecast.sum().round(0)
                    })

        if forecast_rows:
            forecast_df = pd.DataFrame(forecast_rows)
            st.dataframe(forecast_df, use_container_width=True)
    except Exception as e:
        st.error(f"Sales forecast error: {e}")

# --- FOOTER ---
st.caption("Made for MindGames — CSV now, NetSuite soon. All features switch dynamically based on data source.")
