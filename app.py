import datetime
import smtplib
from email.mime.text import MIMEText

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium
from supabase import create_client

# ==========================================
# 1. PAGE CONFIG & CUSTOM CSS
# ==========================================
st.set_page_config(page_title="Norstar Imports Tracker", layout="wide")

st.markdown("""
    <style>
    div[data-baseweb="input"] { border: 2px solid #707070 !important; border-radius: 5px !important; background-color: #ffffff !important; }
    div[data-baseweb="select"] > div { border: 2px solid #707070 !important; border-radius: 5px !important; background-color: #ffffff !important; }
    input { color: #000000 !important; }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 2. AUTHENTICATION (LOGIN WALL)
# ==========================================
if "role" not in st.session_state:
    st.session_state.role = None

if st.session_state.role is None:
    st.title("🚢 Norstar Logistics Portal")
    st.divider()
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.subheader("🔒 Secure Login")
        with st.form("login_form"):
            username = st.text_input("Username (admin or viewer)").lower().strip()
            password = st.text_input("Password", type="password")
            
            if st.form_submit_button("Log In", type="primary", use_container_width=True):
                if username == "admin" and password == st.secrets["ADMIN_PASS"]:
                    st.session_state.role = "Admin"
                    st.rerun()
                elif username == "viewer" and password == st.secrets["VIEWER_PASS"]:
                    st.session_state.role = "Viewer"
                    st.rerun()
                else:
                    st.error("Incorrect username or password.")
    st.stop()

# Logout Button in Sidebar
with st.sidebar:
    st.write(f"Logged in as: **{st.session_state.role}**")
    if st.button("Logout"):
        st.session_state.role = None
        st.rerun()

# ==========================================
# 3. DATABASE CONNECTION & HELPER FUNCTIONS
# ==========================================
@st.cache_resource
def init_connection():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

supabase = init_connection()

def send_status_alert(po_number, new_status):
    try:
        sender = st.secrets["SENDER_EMAIL"]
        pwd = st.secrets["SENDER_PASS"]
        receiver = st.secrets["RECEIVER_EMAIL"]
        msg = MIMEText(f"Hello,\n\nThe status for Container/PO {po_number} has been updated to: {new_status}.\n\nPlease check the Norstar Tracker Portal for details.")
        msg['Subject'] = f"🚨 Logistics Alert: PO {po_number} is now {new_status}"
        msg['From'] = sender
        msg['To'] = receiver
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender, pwd)
            server.send_message(msg)
    except Exception as e:
        st.error(f"Could not send email alert. Error: {e}")

STATUS_COORDS = {
    "Factory (Shanghai)": [31.2304, 121.4737],
    "Factory (Guangzhou)": [23.1291, 113.2644],
    "Origin Port (Ningbo)": [29.8683, 121.5439],
    "In Transit (Ocean)": [20.0000, -150.0000],
    "Customs (Manzanillo)": [19.0535, -104.3161],
    "Delivered (Cuauhtémoc)": [28.4046, -106.8656]
}

vendors_res = supabase.table("vendors").select("*").execute()
vendor_data = vendors_res.data if vendors_res.data else []
vendor_list = [v['vendor_name'] for v in vendor_data]

products_res = supabase.table("products").select("*").execute()
product_data = products_res.data if products_res.data else []

if 'draft_container' not in st.session_state:
    st.session_state.draft_container = []

st.title("🚢 Norstar Product Tracking Dashboard")

# ==========================================
# 4. ROLE-BASED NAVIGATION
# ==========================================
if st.session_state.role == "Admin":
    tabs = st.tabs(["🌍 Live Dashboard", "🏗️ Container Builder", "📦 Quick Add", "🏢 Manage Data"])
    tab_dash, tab_build, tab_add, tab_manage = tabs
else:
    tabs = st.tabs(["🌍 Live Dashboard"])
    tab_dash = tabs[0]
    tab_build = tab_add = tab_manage = None

# ==========================================
# TAB 1: LIVE DASHBOARD
# ==========================================
with tab_dash:
    response = supabase.table("shipments").select("*").execute()
    df = pd.DataFrame(response.data)

    if not df.empty:
        col1, col2, col3 = st.columns(3)
        col1.metric("Active Containers", df[df['status'] != "Delivered (Cuauhtémoc)"]['po_number'].nunique())
        col2.metric("In Transit (Ocean)", df[df['status'] == "In Transit (Ocean)"]['po_number'].nunique())
        col3.metric("At Customs", df[df['status'] == "Customs (Manzanillo)"]['po_number'].nunique())
        st.divider()

        st.subheader("⚖️ Container Capacity Tracker")
        if 'total_weight_kg' in df.columns and 'total_volume_cu_ft' in df.columns:
            containers = df.groupby(['po_number', 'max_capacity_kg', 'max_volume_cu_ft'])[['total_weight_kg', 'total_volume_cu_ft']].sum().reset_index()
            cols = st.columns(3)
            for idx, row in containers.iterrows():
                with cols[idx % 3]:
                    st.markdown(f"**PO / Container: {row['po_number']}**")
                    curr_w, max_w = float(row['total_weight_kg']), float(row['max_capacity_kg'])
                    curr_v, max_v = float(row['total_volume_cu_ft']), float(row['max_volume_cu_ft'])
                    
                    st.caption(f"**Weight:** {curr_w:,.0f} / {max_w:,.0f} kg")
                    st.progress(min(curr_w / max_w if max_w > 0 else 0, 1.0))
                    st.caption(f"**Space:** {curr_v:,.0f} / {max_v:,.0f} cu ft")
                    st.progress(min(curr_v / max_v if max_v > 0 else 0, 1.0))
                    st.write("") 

        if st.session_state.role == "Admin":
            st.divider()
            st.subheader("💰 Financials & Lead Time Analysis")
            if 'container_freight_usd' in df.columns and 'eta' in df.columns:
                unique_pos = df['po_number'].unique()
                for po in unique_pos:
                    po_df = df[df['po_number'] == po]
                    freight_cost = float(po_df['container_freight_usd'].iloc[0]) if not pd.isna(po_df['container_freight_usd'].iloc[0]) else 0
                    total_po_weight = po_df['total_weight_kg'].sum()
                    eta_str = po_df['eta'].iloc[0]
                    status = po_df['status'].iloc[0]
                    
                    timeline_status = "Unknown"
                    if eta_str:
                        eta_date = datetime.datetime.strptime(str(eta_str), "%Y-%m-%d").date()
                        days_diff = (eta_date - datetime.date.today()).days
                        if "Delivered" in str(status): timeline_status = "✅ Arrived"
                        elif days_diff < 0: timeline_status = f"🚨 LATE by {abs(days_diff)} days"
                        else: timeline_status = f"⏳ ETA in {days_diff} days"

                    with st.expander(f"📦 Details for {po} | Status: {status} | {timeline_status}"):
                        st.write(f"**Container Freight:** ${freight_cost:,.2f}")
                        calc_data = []
                        for _, row in po_df.iterrows():
                            total_parts = row.get('total_parts')
                            if pd.isna(total_parts): total_parts = row['quantity']
                            
                            qty_units = float(row['quantity'])
                            weight = float(row['total_weight_kg'])
                            prod_name = row['product']
                            
                            base_price = float(next((p.get('price_usd') or 0 for p in product_data if p['product_name'] == prod_name), 0))
                            
                            freight_per_part = (freight_cost * (weight / total_po_weight)) / float(total_parts) if total_po_weight > 0 and float(total_parts) > 0 else 0
                            
                            calc_data.append({
                                "Product": prod_name, "Shipping Qty": qty_units, "Total Parts": total_parts,
                                "Base Price (ea)": f"${base_price:,.2f}", "Freight Share (ea)": f"${freight_per_part:,.2f}", 
                                "TRUE LANDED COST (ea)": f"${base_price + freight_per_part:,.2f}"
                            })
                        st.table(pd.DataFrame(calc_data))

        st.divider()
        st.subheader("Global Shipment View")
        m = folium.Map(location=[25.0, -110.0], zoom_start=3, tiles="CartoDB positron") 
        for index, row in df.drop_duplicates(subset=['po_number']).iterrows():
            if row['status'] in STATUS_COORDS:
                pin_color = "green" if "Delivered" in row['status'] else "blue" if "Ocean" in row['status'] else "red"
                folium.Marker(location=STATUS_COORDS[row['status']], popup=f"<b>PO: {row['po_number']}</b>", tooltip=f"{row['status']}", icon=folium.Icon(color=pin_color, icon="info-sign")).add_to(m)
        st_folium(m, width=1200, height=450, returned_objects=[])

        st.divider()
        st.subheader("Update Shipment Status")
        display_cols = ['id', 'po_number', 'provider', 'product', 'quantity']
        if 'total_parts' in df.columns: display_cols.append('total_parts')
        display_cols.append('status')
        
        edited_df = st.data_editor(
            df[display_cols].copy(),
            column_config={
                "id": None, "po_number": st.column_config.TextColumn("PO Number", disabled=True),
                "provider": st.column_config.TextColumn("Provider", disabled=True),
                "product": st.column_config.TextColumn("Product", disabled=True),
                "quantity": st.column_config.NumberColumn("Shipping Units", disabled=True),
                "total_parts": st.column_config.NumberColumn("Total Parts", disabled=True),
                "status": st.column_config.SelectboxColumn("Current Status", options=list(STATUS_COORDS.keys()), required=True)
            },
            use_container_width=True, hide_index=True, key="data_editor"
        )

        if st.button("Apply Changes & Send Alerts", type="primary"):
            changes = False
            with st.spinner("Updating database and dispatching alerts..."):
                for index, row in edited_df.iterrows():
                    if df.loc[index, 'status'] != row['status']:
                        new_stat = row['status']
                        supabase.table("shipments").update({"status": new_stat}).eq("id", row['id']).execute()
                        changes = True
                        if "Manzanillo" in new_stat or "Cuauhtémoc" in new_stat:
                            send_status_alert(row['po_number'], new_stat)
            if changes:
                st.success("Updated! Refreshing...")
                st.rerun()
    else:
        st.info("No shipments active.")

# ==========================================
# ADMIN-ONLY TABS 
# ==========================================
if tab_build:
    with tab_build:
        st.subheader("🏗️ Build & Fill a Consolidated Container")
        col_po, col_cap_w, col_cap_v = st.columns([2, 1, 1])
        builder_po = col_po.text_input("Master PO", key="builder_po")
        builder_cap_w = col_cap_w.number_input("Max Weight (kg)", value=28000)
        builder_cap_v = col_cap_v.number_input("Max Space (cu ft)", value=2690)

        col_fr, col_etd, col_eta = st.columns(3)
        builder_freight = col_fr.number_input("Est. Freight Cost (USD)", value=8500.0)
        builder_etd = col_etd.date_input("ETD")
        builder_eta = col_eta.date_input("ETA", value=datetime.date.today() + datetime.timedelta(days=45))

        st.divider()
        build_col1, build_col2 = st.columns([1, 1.8])
        with build_col1:
            if vendor_list:
                b_vendor = st.selectbox("Select Vendor", vendor_list, key="b_vendor")
                filtered_prods = [p for p in product_data if p['vendor_name'] == b_vendor]
                b_product = st.selectbox("Select Product", [p['product_name'] for p in filtered_prods] if filtered_prods else ["None"], key="b_product")
                
                selected_prod_info = next((p for p in filtered_prods if p['product_name'] == b_product), {})
                u_type = selected_prod_info.get('unit_type', 'Unit')
                parts_per = float(selected_prod_info.get('parts_per_unit', 1))
                
                st.info(f"Shipping Unit: **{u_type}** | Contains: **{parts_per:,.0f} Parts**")
                
                b_qty = st.number_input(f"Quantity of {u_type}s to Load", min_value=1, value=1, key="b_qty")
                
                if st.button("➕ Stage Item"):
                    unit_cu_ft = ((selected_prod_info.get('length_in') or 0) * (selected_prod_info.get('width_in') or 0) * (selected_prod_info.get('height_in') or 0)) / 1728
                    st.session_state.draft_container.append({
                        "provider": b_vendor, 
                        "product": b_product, 
                        "quantity": b_qty, 
                        "total_parts": b_qty * parts_per,
                        "unit_type": u_type,
                        "total_weight": (selected_prod_info.get('weight_kg') or 0) * b_qty, 
                        "total_volume": unit_cu_ft * b_qty,
                        "base_price": selected_prod_info.get('price_usd') or 0
                    })
                    st.rerun()
            else: st.warning("Add a Vendor first.")

        with build_col2:
            st.markdown("#### 2. Container Overview")
            if not st.session_state.draft_container:
                st.info("Container is empty. Add items from the left.")
            else:
                draft_df = pd.DataFrame(st.session_state.draft_container)
                curr_w, curr_v = draft_df['total_weight'].sum(), draft_df['total_volume'].sum()
                curr_parts = draft_df['total_parts'].sum()
                
                # --- NEW: Parts Counter & Progress Bars ---
                c_p, c_w, c_v = st.columns([1, 1.5, 1.5])
                with c_p:
                    st.metric("Total Parts", f"{curr_parts:,.0f}")
                with c_w:
                    st.caption(f"**Weight:** {curr_w:,.0f} / {builder_cap_w:,.0f} kg")
                    st.progress(min(curr_w / builder_cap_w if builder_cap_w > 0 else 0, 1.0))
                with c_v:
                    st.caption(f"**Space:** {curr_v:,.1f} / {builder_cap_v:,.0f} cu ft")
                    st.progress(min(curr_v / builder_cap_v if builder_cap_v > 0 else 0, 1.0))
                
                st.markdown("**Staged Items Breakdown**")
                
                # --- NEW: Calculate Itemized Percentages ---
                draft_df['wt_pct'] = (draft_df['total_weight'] / builder_cap_w) * 100 if builder_cap_w > 0 else 0
                draft_df['vol_pct'] = (draft_df['total_volume'] / builder_cap_v) * 100 if builder_cap_v > 0 else 0

                edited_draft = st.data_editor(
                    draft_df[['provider', 'product', 'quantity', 'unit_type', 'total_parts', 'wt_pct', 'vol_pct']],
                    column_config={
                        "provider": st.column_config.TextColumn("Provider", disabled=True),
                        "product": st.column_config.TextColumn("Product", disabled=True),
                        "quantity": st.column_config.NumberColumn("Qty", min_value=1),
                        "unit_type": st.column_config.TextColumn("Type", disabled=True),
                        "total_parts": st.column_config.NumberColumn("Parts", disabled=True),
                        "wt_pct": st.column_config.NumberColumn("Weight %", format="%.1f%%", disabled=True),
                        "vol_pct": st.column_config.NumberColumn("Space %", format="%.1f%%", disabled=True)
                    },
                    use_container_width=True, hide_index=True, num_rows="dynamic", key="draft_editor"
                )
                
                if st.button("🔄 Update Draft Math", use_container_width=True):
                    new_draft = []
                    for _, row in edited_draft.iterrows():
                        prod = next((p for p in product_data if p['product_name'] == row['product']), {})
                        unit_wt = prod.get('weight_kg') or 0
                        parts_per = float(prod.get('parts_per_unit', 1))
                        unit_vol = ((prod.get('length_in') or 0) * (prod.get('width_in') or 0) * (prod.get('height_in') or 0)) / 1728
                        new_draft.append({
                            "provider": row['provider'], "product": row['product'], "quantity": row['quantity'],
                            "total_parts": row['quantity'] * parts_per, "unit_type": row['unit_type'],
                            "total_weight": unit_wt * row['quantity'], "total_volume": unit_vol * row['quantity'],
                            "base_price": prod.get('price_usd') or 0
                        })
                    st.session_state.draft_container = new_draft
                    st.rerun()

                col_ship, col_clear = st.columns(2)
                with col_ship:
                    if st.button("🚀 Finalize & Ship", type="primary", use_container_width=True):
                        if not builder_po:
                            st.error("Enter a Master PO first!")
                        else:
                            for item in st.session_state.draft_container:
                                supabase.table("shipments").insert({
                                    "po_number": builder_po, "provider": item['provider'], "product": item['product'], 
                                    "quantity": item['quantity'], "total_parts": item['total_parts'],
                                    "total_weight_kg": item['total_weight'], "total_volume_cu_ft": item['total_volume'],
                                    "max_capacity_kg": builder_cap_w, "max_volume_cu_ft": builder_cap_v,
                                    "container_freight_usd": builder_freight, "etd": str(builder_etd), "eta": str(builder_eta),
                                    "status": "Factory (Guangzhou)" 
                                }).execute()
                            st.session_state.draft_container = [] 
                            st.rerun()
                with col_clear:
                    if st.button("🗑️ Clear Draft", use_container_width=True):
                        st.session_state.draft_container = []
                        st.rerun()

if tab_add:
    with tab_add:
        st.subheader("📦 Quick Add to Existing PO")
        if vendor_list:
            with st.form("add_shipment_form", clear_on_submit=True):
                new_po = st.text_input("PO / Container Number")
                selected_vendor = st.selectbox("Select Vendor", vendor_list)
                filtered = [p for p in product_data if p['vendor_name'] == selected_vendor]
                selected_product = st.selectbox("Select Product", [p['product_name'] for p in filtered] if filtered else ["None"])
                
                qty = st.number_input("Quantity of Shipping Units (Pallets/Pieces)", min_value=1, value=1)
                
                if st.form_submit_button("Add to Database") and new_po and selected_product != "None":
                    prod = next((p for p in filtered if p['product_name'] == selected_product), {})
                    unit_cu_ft = ((prod.get('length_in') or 0) * (prod.get('width_in') or 0) * (prod.get('height_in') or 0)) / 1728
                    parts_per = float(prod.get('parts_per_unit', 1))
                    
                    supabase.table("shipments").insert({
                        "po_number": new_po, "provider": selected_vendor, "product": selected_product, 
                        "quantity": qty, "total_parts": qty * parts_per,
                        "total_weight_kg": (prod.get('weight_kg') or 0) * qty, "total_volume_cu_ft": unit_cu_ft * qty,
                        "max_capacity_kg": 28000, "max_volume_cu_ft": 2690, "container_freight_usd": 8500,
                        "etd": str(datetime.date.today()), "eta": str(datetime.date.today() + datetime.timedelta(days=45)),
                        "status": "Factory (Guangzhou)"
                    }).execute()
                    st.rerun()

if tab_manage:
    with tab_manage:
        st.subheader("🏢 Database Management")
        manage_vendors, manage_products = st.tabs(["🏭 Vendors", "📦 Products"])
        
        with manage_vendors:
            with st.form("add_vendor_form"):
                new_v = st.text_input("New Vendor Name")
                if st.form_submit_button("Add") and new_v:
                    supabase.table("vendors").insert({"vendor_name": new_v}).execute()
                    st.rerun()
            
            if vendor_data:
                v_df = st.data_editor(pd.DataFrame(vendor_data), column_config={"id": None}, use_container_width=True, hide_index=True, num_rows="dynamic")
                if st.button("Save Vendors", type="primary"):
                    for i, r in v_df.iterrows():
                        if i < len(vendor_data):
                            if pd.DataFrame(vendor_data).loc[i, 'vendor_name'] != r['vendor_name']:
                                supabase.table("vendors").update({"vendor_name": r['vendor_name']}).eq("id", r['id']).execute()
                        else:
                            supabase.table("vendors").insert({"vendor_name": r['vendor_name']}).execute()
                    st.rerun()

        with manage_products:
            with st.form("add_prod_form"):
                new_p = st.text_input("Product Name")
                v_assign = st.selectbox("Vendor", vendor_list)
                
                st.markdown("**Shipping Unit Configuration**")
                col_u1, col_u2 = st.columns(2)
                u_type = col_u1.selectbox("Unit Type", ["Pallet", "Piece", "Crate", "Bundle"])
                p_per = col_u2.number_input("How many parts in this unit?", min_value=1, value=1)
                
                st.markdown("**Financials & Weight (Per Shipping Unit)**")
                price = st.number_input("Base Price per PART ($)", min_value=0.0)
                wt = st.number_input("Weight per UNIT (kg)", min_value=0.0)
                
                st.markdown("**Dimensions (Inches per UNIT)**")
                l_in, w_in, h_in = st.columns(3)
                len_in = l_in.number_input("L (in)", min_value=0.0)
                wid_in = w_in.number_input("W (in)", min_value=0.0)
                ht_in = h_in.number_input("H (in)", min_value=0.0)
                
                if st.form_submit_button("Add") and new_p:
                    supabase.table("products").insert({
                        "product_name": new_p, "vendor_name": v_assign, "price_usd": price, 
                        "unit_type": u_type, "parts_per_unit": p_per,
                        "weight_kg": wt, "length_in": len_in, "width_in": wid_in, "height_in": ht_in
                    }).execute()
                    st.rerun()
                    
            if product_data:
                p_df = st.data_editor(
                    pd.DataFrame(product_data), 
                    column_config={
                        "id": None, "vendor_name": st.column_config.SelectboxColumn(options=vendor_list),
                        "unit_type": st.column_config.SelectboxColumn(options=["Pallet", "Piece", "Crate", "Bundle"]),
                        "parts_per_unit": st.column_config.NumberColumn("Parts/Unit", min_value=1)
                    }, 
                    use_container_width=True, hide_index=True, num_rows="dynamic"
                )
                if st.button("Save Products", type="primary"):
                    for i, r in p_df.iterrows():
                        if i < len(product_data):
                            orig = pd.DataFrame(product_data).iloc[i]
                            cols_to_check = ['product_name', 'vendor_name', 'price_usd', 'unit_type', 'parts_per_unit', 'weight_kg', 'length_in', 'width_in', 'height_in']
                            if any(orig.get(c) != r.get(c) for c in cols_to_check):
                                supabase.table("products").update({c: r.get(c, 0) if c != 'unit_type' else r.get(c, 'Piece') for c in cols_to_check}).eq("id", r['id']).execute()
                        else:
                            supabase.table("products").insert({c: r.get(c, 0) if c != 'unit_type' else r.get(c, 'Piece') for c in ['product_name', 'vendor_name', 'price_usd', 'unit_type', 'parts_per_unit', 'weight_kg', 'length_in', 'width_in', 'height_in']}).execute()
                    st.rerun()
