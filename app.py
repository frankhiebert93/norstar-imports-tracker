import datetime

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium
from supabase import create_client

# ==========================================
# 1. PAGE CONFIG & DATABASE CONNECTION
# ==========================================
st.set_page_config(page_title="Norstar Imports Tracker", layout="wide")

@st.cache_resource
def init_connection():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_connection()

st.title("🚢 Norstar Product Tracking Dashboard")

# --- INJECT CUSTOM CSS FOR VISIBLE INPUT BORDERS ---
st.markdown("""
    <style>
    /* Put a solid dark gray border around all text, number, and date input blanks */
    div[data-baseweb="input"] {
        border: 2px solid #707070 !important;
        border-radius: 5px !important;
        background-color: #ffffff !important;
    }
    
    /* Put a solid dark gray border around all dropdown menus (selectboxes) */
    div[data-baseweb="select"] > div {
        border: 2px solid #707070 !important;
        border-radius: 5px !important;
        background-color: #ffffff !important;
    }
    
    /* Ensure the text typed inside is dark and easy to read */
    input {
        color: #000000 !important;
    }
    </style>
""", unsafe_allow_html=True)
st.divider() # Just adds a nice clean line under the title

STATUS_COORDS = {
    "Factory (Shanghai)": [31.2304, 121.4737],
    "Factory (Guangzhou)": [23.1291, 113.2644],
    "Origin Port (Ningbo)": [29.8683, 121.5439],
    "In Transit (Ocean)": [20.0000, -150.0000],
    "Customs (Manzanillo)": [19.0535, -104.3161],
    "Delivered (Cuauhtémoc)": [28.4046, -106.8656]
}

# ==========================================
# 2. FETCH MASTER DATA & INIT SESSION STATE
# ==========================================
vendors_res = supabase.table("vendors").select("*").execute()
vendor_data = vendors_res.data if vendors_res.data else []
vendor_list = [v['vendor_name'] for v in vendor_data]

products_res = supabase.table("products").select("*").execute()
product_data = products_res.data if products_res.data else []

if 'draft_container' not in st.session_state:
    st.session_state.draft_container = []

# ==========================================
# 3. NAVIGATION TABS
# ==========================================
tab_dash, tab_build, tab_add, tab_manage = st.tabs([
    "🌍 Live Dashboard", 
    "🏗️ Container Builder", 
    "📦 Quick Add", 
    "🏢 Manage Data"
])

# ==========================================
# TAB 1: LIVE DASHBOARD
# ==========================================
with tab_dash:
    response = supabase.table("shipments").select("*").execute()
    df = pd.DataFrame(response.data)

    if not df.empty:
        col1, col2, col3 = st.columns(3)
        active_count = df[df['status'] != "Delivered (Cuauhtémoc)"]['po_number'].nunique()
        ocean_count = df[df['status'] == "In Transit (Ocean)"]['po_number'].nunique()
        customs_count = df[df['status'] == "Customs (Manzanillo)"]['po_number'].nunique()
        
        col1.metric("Active Containers (POs)", active_count)
        col2.metric("In Transit (Ocean)", ocean_count)
        col3.metric("At Customs", customs_count)

        st.divider()

        # DUAL CAPACITY TRACKER
        st.subheader("⚖️ Container Capacity Tracker")
        if 'total_weight_kg' in df.columns and 'total_volume_cu_ft' in df.columns:
            containers = df.groupby(['po_number', 'max_capacity_kg', 'max_volume_cu_ft'])[['total_weight_kg', 'total_volume_cu_ft']].sum().reset_index()
            cols = st.columns(3)
            for idx, row in containers.iterrows():
                with cols[idx % 3]:
                    st.markdown(f"**PO / Container: {row['po_number']}**")
                    curr_w = float(row['total_weight_kg'])
                    max_w = float(row['max_capacity_kg'])
                    curr_v = float(row['total_volume_cu_ft'])
                    max_v = float(row['max_volume_cu_ft'])
                    
                    st.caption(f"**Weight:** {curr_w:,.0f} / {max_w:,.0f} kg")
                    st.progress(min(curr_w / max_w if max_w > 0 else 0, 1.0))
                    
                    st.caption(f"**Space:** {curr_v:,.0f} / {max_v:,.0f} cu ft")
                    st.progress(min(curr_v / max_v if max_v > 0 else 0, 1.0))
                    st.write("") 
        else:
            st.info("Missing dimensions or weight in database.")

        st.divider()

        # --- NEW: LANDED COST & TIMELINE ANALYSIS ---
        st.subheader("💰 Financials & Lead Time Analysis")
        if 'container_freight_usd' in df.columns and 'eta' in df.columns:
            unique_pos = df['po_number'].unique()
            for po in unique_pos:
                po_df = df[df['po_number'] == po]
                freight_cost = float(po_df['container_freight_usd'].iloc[0]) if not pd.isna(po_df['container_freight_usd'].iloc[0]) else 0
                total_po_weight = po_df['total_weight_kg'].sum()
                eta_str = po_df['eta'].iloc[0]
                status = po_df['status'].iloc[0]
                
                # Timeline Logic
                timeline_status = "Unknown"
                if eta_str:
                    eta_date = datetime.datetime.strptime(str(eta_str), "%Y-%m-%d").date()
                    today = datetime.date.today()
                    days_diff = (eta_date - today).days
                    
                    if "Delivered" in str(status):
                        timeline_status = "✅ Arrived"
                    elif days_diff < 0:
                        timeline_status = f"🚨 LATE by {abs(days_diff)} days"
                    else:
                        timeline_status = f"⏳ ETA in {days_diff} days ({eta_date})"

                with st.expander(f"📦 Details for {po} | Status: {status} | {timeline_status}"):
                    st.write(f"**Total Container Freight Cost:** ${freight_cost:,.2f}")
                    
                    # Calculate Landed Cost per item
                    calc_data = []
                    for _, row in po_df.iterrows():
                        qty = float(row['quantity'])
                        weight = float(row['total_weight_kg'])
                        prod_name = row['product']
                        
                        # Fetch base price from product data
                        prod_info = next((p for p in product_data if p['product_name'] == prod_name), {})
                        base_price = float(prod_info.get('price_usd') or 0)
                        
                        # Freight allocation by weight percentage
                        weight_pct = weight / total_po_weight if total_po_weight > 0 else 0
                        allocated_freight = freight_cost * weight_pct
                        freight_per_unit = allocated_freight / qty if qty > 0 else 0
                        landed_cost = base_price + freight_per_unit
                        
                        calc_data.append({
                            "Product": prod_name,
                            "Qty": qty,
                            "Base Price (ea)": f"${base_price:,.2f}",
                            "Freight Share (ea)": f"${freight_per_unit:,.2f}",
                            "TRUE LANDED COST (ea)": f"${landed_cost:,.2f}"
                        })
                    
                    st.table(pd.DataFrame(calc_data))
        else:
            st.info("Missing freight or timeline columns in database.")

        st.divider()

        st.subheader("Global Shipment View")
        m = folium.Map(location=[25.0, -110.0], zoom_start=3, tiles="CartoDB positron") 
        map_df = df.drop_duplicates(subset=['po_number'])
        
        for index, row in map_df.iterrows():
            current_status = row['status']
            if current_status in STATUS_COORDS:
                coords = STATUS_COORDS[current_status]
                pin_color = "green" if "Delivered" in current_status else "blue" if "Ocean" in current_status else "red"
                folium.Marker(
                    location=coords,
                    popup=f"<b>PO: {row['po_number']}</b>",
                    tooltip=f"{current_status}",
                    icon=folium.Icon(color=pin_color, icon="info-sign")
                ).add_to(m)

        st_folium(m, width=1200, height=450, returned_objects=[])

        st.divider()

        st.subheader("Update Shipment Status")
        display_df = df[['id', 'po_number', 'provider', 'product', 'quantity', 'status']].copy()
        edited_df = st.data_editor(
            display_df,
            column_config={
                "id": None, 
                "po_number": st.column_config.TextColumn("PO Number", disabled=True),
                "provider": st.column_config.TextColumn("Provider", disabled=True),
                "product": st.column_config.TextColumn("Product", disabled=True),
                "quantity": st.column_config.NumberColumn("Qty", disabled=True),
                "status": st.column_config.SelectboxColumn("Current Status", options=list(STATUS_COORDS.keys()), required=True)
            },
            use_container_width=True, hide_index=True, key="data_editor"
        )

        if st.button("Apply Changes", type="primary"):
            changes_made = False
            with st.spinner("Updating..."):
                for index, row in edited_df.iterrows():
                    if df.loc[index, 'status'] != row['status']:
                        supabase.table("shipments").update({"status": row['status']}).eq("id", row['id']).execute()
                        changes_made = True
            if changes_made:
                st.success("Updated! Refreshing...")
                st.rerun()
    else:
        st.info("No shipments active. Build a container or use Quick Add.")

# ==========================================
# TAB 2: CONTAINER BUILDER
# ==========================================
with tab_build:
    st.subheader("🏗️ Build & Fill a Consolidated Container")
    
    col_po, col_cap_w, col_cap_v = st.columns([2, 1, 1])
    with col_po:
        builder_po = st.text_input("Master PO / Container Number", key="builder_po")
    with col_cap_w:
        builder_cap_w = st.number_input("Max Weight (kg)", value=28000, key="builder_cap_w")
    with col_cap_v:
        builder_cap_v = st.number_input("Max Space (cu ft)", value=2690, key="builder_cap_v")

    # NEW: Freight & Timeline Inputs
    col_fr, col_etd, col_eta = st.columns(3)
    with col_fr:
        builder_freight = st.number_input("Est. Container Freight Cost (USD)", value=8500.00, step=100.0)
    with col_etd:
        builder_etd = st.date_input("Estimated Departure (ETD)")
    with col_eta:
        builder_eta = st.date_input("Estimated Arrival (ETA)", value=datetime.date.today() + datetime.timedelta(days=45))

    st.divider()
    build_col1, build_col2 = st.columns([1, 1.5])

    with build_col1:
        st.markdown("#### 1. Add Pallets/Items")
        if not vendor_list:
            st.warning("⚠️ Add a Vendor in 'Manage Data' first.")
        else:
            b_vendor = st.selectbox("Select Vendor", vendor_list, key="b_vendor")
            filtered_prods = [p for p in product_data if p['vendor_name'] == b_vendor]
            prod_names = [p['product_name'] for p in filtered_prods] if filtered_prods else ["No products found"]
            
            b_product = st.selectbox("Select Product", prod_names, key="b_product")
            b_qty = st.number_input("Quantity", min_value=1, value=1, key="b_qty")
            
            if st.button("➕ Stage Item in Container"):
                if b_product != "No products found":
                    prod = next((p for p in filtered_prods if p['product_name'] == b_product), {})
                    weight = prod.get('weight_kg') or 0
                    l_in = prod.get('length_in') or 0
                    w_in = prod.get('width_in') or 0
                    h_in = prod.get('height_in') or 0
                    price = prod.get('price_usd') or 0
                    
                    unit_cu_ft = (l_in * w_in * h_in) / 1728
                    
                    st.session_state.draft_container.append({
                        "provider": b_vendor,
                        "product": b_product,
                        "quantity": b_qty,
                        "total_weight": weight * b_qty,
                        "total_volume": unit_cu_ft * b_qty,
                        "base_price": price
                    })
                    st.rerun()

    with build_col2:
        st.markdown("#### 2. Container Overview")
        if not st.session_state.draft_container:
            st.info("Container is empty. Add items from the left.")
        else:
            draft_df = pd.DataFrame(st.session_state.draft_container)
            curr_weight = draft_df['total_weight'].sum()
            curr_vol = draft_df['total_volume'].sum()
            
            pc_w, pc_v = st.columns(2)
            with pc_w:
                st.caption(f"**Weight:** {curr_weight:,.0f} / {builder_cap_w:,.0f} kg")
                st.progress(min(curr_weight / builder_cap_w if builder_cap_w > 0 else 0, 1.0))
            with pc_v:
                st.caption(f"**Space:** {curr_vol:,.1f} / {builder_cap_v:,.0f} cu ft")
                st.progress(min(curr_vol / builder_cap_v if builder_cap_v > 0 else 0, 1.0))
            
            st.dataframe(draft_df[['provider', 'product', 'quantity', 'total_weight']], use_container_width=True, hide_index=True)
            
            col_ship, col_clear = st.columns(2)
            with col_ship:
                if st.button("🚀 Finalize & Ship Container", type="primary", use_container_width=True):
                    if not builder_po:
                        st.error("Enter a Master PO / Container Number first!")
                    else:
                        with st.spinner("Locking in container..."):
                            for item in st.session_state.draft_container:
                                new_data = {
                                    "po_number": builder_po,
                                    "provider": item['provider'],
                                    "product": item['product'],
                                    "quantity": item['quantity'],
                                    "total_weight_kg": item['total_weight'],
                                    "total_volume_cu_ft": item['total_volume'],
                                    "max_capacity_kg": builder_cap_w,
                                    "max_volume_cu_ft": builder_cap_v,
                                    "container_freight_usd": builder_freight,
                                    "etd": str(builder_etd),
                                    "eta": str(builder_eta),
                                    "status": "Factory (Guangzhou)" 
                                }
                                supabase.table("shipments").insert(new_data).execute()
                            
                            st.session_state.draft_container = [] 
                            st.success(f"Container {builder_po} locked in!")
                            st.rerun()
            with col_clear:
                if st.button("🗑️ Clear Draft", use_container_width=True):
                    st.session_state.draft_container = []
                    st.rerun()

# ==========================================
# TAB 3: QUICK ADD
# ==========================================
with tab_add:
    st.subheader("📦 Quick Add to Existing PO")
    if not vendor_list:
        st.warning("⚠️ Add a Vendor first.")
    else:
        with st.form("add_shipment_form", clear_on_submit=True):
            new_po = st.text_input("PO / Container Number")
            selected_vendor = st.selectbox("Select Vendor", vendor_list, key="qa_vendor")
            filtered_products = [p for p in product_data if p['vendor_name'] == selected_vendor]
            prod_names = [p['product_name'] for p in filtered_products] if filtered_products else ["No products found"]
            selected_product_name = st.selectbox("Select Product", prod_names, key="qa_prod")
            
            qty = st.number_input("Quantity", min_value=1, value=1, key="qa_qty")
            qa_freight = st.number_input("Container Freight Cost (USD)", value=8500.0)
            
            col_d1, col_d2 = st.columns(2)
            with col_d1:
                qa_etd = st.date_input("ETD", key="qa_etd")
            with col_d2:
                qa_eta = st.date_input("ETA", key="qa_eta")
                
            initial_status = st.selectbox("Initial Status", list(STATUS_COORDS.keys()))
            
            if st.form_submit_button("Add to Database"):
                if new_po and selected_product_name != "No products found":
                    prod = next((p for p in filtered_products if p['product_name'] == selected_product_name), {})
                    weight = prod.get('weight_kg') or 0
                    l_in = prod.get('length_in') or 0
                    w_in = prod.get('width_in') or 0
                    h_in = prod.get('height_in') or 0
                    unit_cu_ft = (l_in * w_in * h_in) / 1728
                    
                    new_data = {
                        "po_number": new_po,
                        "provider": selected_vendor,
                        "product": selected_product_name,
                        "quantity": qty,
                        "total_weight_kg": weight * qty,
                        "total_volume_cu_ft": unit_cu_ft * qty,
                        "max_capacity_kg": 28000,
                        "max_volume_cu_ft": 2690,
                        "container_freight_usd": qa_freight,
                        "etd": str(qa_etd),
                        "eta": str(qa_eta),
                        "status": initial_status
                    }
                    supabase.table("shipments").insert(new_data).execute()
                    st.success(f"Added {qty}x {selected_product_name} to PO {new_po}.")
                    st.rerun()

# ==========================================
# TAB 4: MANAGE VENDORS & PRODUCTS
# ==========================================
with tab_manage:
    st.subheader("🏢 Database Management")
    manage_vendors, manage_products = st.tabs(["🏭 Manage Vendors", "📦 Manage Products"])
    
    with manage_vendors:
        col_v_add, col_v_edit = st.columns([1, 2])
        with col_v_add:
            st.markdown("#### Add New Vendor")
            with st.form("add_vendor_form", clear_on_submit=True):
                new_vendor_name = st.text_input("Vendor Name")
                if st.form_submit_button("Save Vendor") and new_vendor_name:
                    supabase.table("vendors").insert({"vendor_name": new_vendor_name}).execute()
                    st.success("Added Vendor")
                    st.rerun()
                    
        with col_v_edit:
            st.markdown("#### Edit Existing Vendors")
            if vendor_data:
                v_df = pd.DataFrame(vendor_data)
                edited_v_df = st.data_editor(
                    v_df,
                    column_config={"id": None, "vendor_name": st.column_config.TextColumn("Vendor Name", required=True)},
                    use_container_width=True, hide_index=True, key="edit_vendors"
                )
                if st.button("💾 Save Vendor Edits", type="primary"):
                    for index, row in edited_v_df.iterrows():
                        if v_df.loc[index, 'vendor_name'] != row['vendor_name']:
                            supabase.table("vendors").update({"vendor_name": row['vendor_name']}).eq("id", row['id']).execute()
                    st.success("Vendors updated successfully!")
                    st.rerun()

    with manage_products:
        col_p_add, col_p_edit = st.columns([1, 2.5])
        with col_p_add:
            st.markdown("#### Add New Product")
            if not vendor_list:
                st.warning("Add a vendor first.")
            else:
                with st.form("add_product_form", clear_on_submit=True):
                    new_product_name = st.text_input("Product Name")
                    assign_to_vendor = st.selectbox("Assign to Vendor", vendor_list)
                    
                    st.markdown("**Financials & Weight**")
                    new_price = st.number_input("Base Price (USD)", min_value=0.0, step=1.0)
                    new_weight = st.number_input("Weight (kg)", min_value=0.0, step=0.1)
                    
                    st.markdown("**Dimensions (Inches)**")
                    l_in = st.number_input("Length", min_value=0.0)
                    w_in = st.number_input("Width", min_value=0.0)
                    h_in = st.number_input("Height", min_value=0.0)
                    
                    if st.form_submit_button("Save Product") and new_product_name:
                        supabase.table("products").insert({
                            "product_name": new_product_name, 
                            "vendor_name": assign_to_vendor,
                            "price_usd": new_price,
                            "weight_kg": new_weight,
                            "length_in": l_in,
                            "width_in": w_in,
                            "height_in": h_in
                        }).execute()
                        st.success(f"Added: {new_product_name}")
                        st.rerun()
                        
        with col_p_edit:
            st.markdown("#### Edit Existing Products")
            if product_data:
                p_df = pd.DataFrame(product_data)
                edited_p_df = st.data_editor(
                    p_df,
                    column_config={
                        "id": None, 
                        "product_name": st.column_config.TextColumn("Product", required=True),
                        "vendor_name": st.column_config.SelectboxColumn("Vendor", options=vendor_list, required=True),
                        "price_usd": st.column_config.NumberColumn("Price ($)", min_value=0.0),
                        "weight_kg": st.column_config.NumberColumn("Weight (kg)", min_value=0.0),
                        "length_in": st.column_config.NumberColumn("L (in)", min_value=0.0),
                        "width_in": st.column_config.NumberColumn("W (in)", min_value=0.0),
                        "height_in": st.column_config.NumberColumn("H (in)", min_value=0.0)
                    },
                    use_container_width=True, hide_index=True, key="edit_products"
                )
                
                if st.button("💾 Save Product Edits", type="primary"):
                    for index, row in edited_p_df.iterrows():
                        orig_row = p_df.iloc[index]
                        if any(orig_row.get(col) != row.get(col) for col in ['product_name', 'vendor_name', 'price_usd', 'weight_kg', 'length_in', 'width_in', 'height_in']):
                            supabase.table("products").update({
                                "product_name": row['product_name'],
                                "vendor_name": row['vendor_name'],
                                "price_usd": row.get('price_usd', 0),
                                "weight_kg": row.get('weight_kg', 0),
                                "length_in": row.get('length_in', 0),
                                "width_in": row.get('width_in', 0),
                                "height_in": row.get('height_in', 0)
                            }).eq("id", row['id']).execute()
                    st.success("Products updated successfully!")
                    st.rerun()