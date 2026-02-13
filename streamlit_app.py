import streamlit as st
import pandas as pd
from decimal import Decimal
import io
import os

# --- MOCK ENV FOR LOCAL TESTING ---
# This allows running the app without Supabase credentials in .env
if "supabase_url" not in os.environ and not os.getenv("SUPABASE_URL"):
    os.environ["SUPABASE_URL"] = "https://example.supabase.co"
if "supabase_key" not in os.environ and not os.getenv("SUPABASE_KEY"):
    os.environ["SUPABASE_KEY"] = "dummy-key"
if "supabase_service_key" not in os.environ and not os.getenv("SUPABASE_SERVICE_KEY"):
    os.environ["SUPABASE_SERVICE_KEY"] = "dummy-service-key"

from app.services.ingestion import IngestionService, TrialBalanceError, HeaderDetectionError

# Page Config
st.set_page_config(
    page_title="AceCPAs GL Tester",
    page_icon="🧾",
    layout="wide",
)

st.title("🧾 AceCPAs GL Ingestion Tester")
st.markdown("""
This tool allows you to test the **Ingestion Service** logic locally without connecting to a database.
Upload **one or more** Excel files (GL) to see how the system parses headers, extracts transactions, and validates the trial balance.
""")

# Initialize Service
service = IngestionService()

# File Upload - Multiple Allowed
uploaded_files = st.file_uploader("Upload GL Files (.xlsx, .xls)", type=["xlsx", "xls"], accept_multiple_files=True)

if uploaded_files:
    st.divider()
    
    # Create tabs for each file
    tabs = st.tabs([f.name for f in uploaded_files])
    
    for i, uploaded_file in enumerate(uploaded_files):
        with tabs[i]:
            st.subheader(f"📄 {uploaded_file.name}")
            
            # Define a unique key for this file's session state
            file_key = f"data_{uploaded_file.name}_{uploaded_file.size}"
            
            if file_key not in st.session_state:
                st.session_state[file_key] = {
                    "transactions": None,
                    "stats": None,
                    "mapped_transactions": None
                }

            # 1. Processing (Only if not already processed)
            if not st.session_state[file_key]["transactions"]:
                try:
                    # Read file into bytes
                    file_bytes = uploaded_file.getvalue()
                    filename = uploaded_file.name
                    
                    with st.spinner(f"Processing {filename}..."):
                        transactions, stats = service.process_excel_file(
                            file_content=file_bytes,
                            deal_id="TEST-DEAL-ID",
                            filename=filename,
                            validate=False
                        )
                    # Store in session state
                    st.session_state[file_key]["transactions"] = transactions
                    st.session_state[file_key]["stats"] = stats
                
                except HeaderDetectionError as e:
                    st.error(f"❌ Header Detection Failed: {str(e)}")
                    st.markdown("Try ensuring your Excel file has standard header names like 'Date', 'Account', 'Amount', 'Description'.")
                    continue
                except Exception as e:
                    st.error(f"❌ Error: {str(e)}")
                    st.exception(e)
                    continue

            # Retrieve from state
            transactions = st.session_state[file_key]["transactions"]
            stats = st.session_state[file_key]["stats"]
            mapped_txs = st.session_state[file_key]["mapped_transactions"]
            
            # --- DISPLAY SECTION ---
            
            # Top Stats
            st.success("✅ File Loaded")
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Rows Read", stats['rows_read'])
            col2.metric("Rows Processed", stats['rows_processed'])
            col3.metric("Header Row", stats['header_row'])
            
            # Financial Validation
            total_debits = stats['total_debits']
            total_credits = stats['total_credits']
            imbalance = total_debits - total_credits
            is_balanced = abs(imbalance) <= Decimal('0.01')
            
            imbalance_color = "normal" if is_balanced else "inverse"
            col4.metric(
                "Net Imbalance", 
                f"${imbalance:,.2f}", 
                delta="Balanced" if is_balanced else "Check Balance",
                delta_color=imbalance_color
            )
            
            if not is_balanced:
                st.error(f"⚠️ **Trial Balance Issues Detected**. See details below.")

            st.divider()

            # APP TABS
            tab_data, tab_map, tab_dash, tab_report = st.tabs(["📋 Data & Validation", "🤖 AI Mapping", "📊 Dashboard", "📅 Reports"])
            
            # --- TAB 1: DATA & VALIDATION ---
            with tab_data:
                # Parse Errors
                if stats['parse_errors']:
                    with st.expander("⚠️ Parse Errors / Warnings", expanded=True):
                        st.dataframe(pd.DataFrame(stats['parse_errors'], columns=["Error Log"]), use_container_width=True)

                st.subheader("Raw Transactions")
                df_raw = pd.DataFrame(transactions)
                st.dataframe(df_raw, use_container_width=True)

                # Advanced Diagnostics (reused logic)
                with st.expander("🛠️ Diagnostics & Fixes"):
                    missing_std_cols = [k for k in ['date', 'amount', 'account', 'description'] if k not in stats['column_mapping']]
                    if missing_std_cols:
                        st.warning(f"Missing Columns: {', '.join(missing_std_cols)}")
                    if not is_balanced:
                         st.markdown("- Check for sign logic (Credits usually negative).\n- Check for Grand Total rows included by mistake.")

            # --- TAB 2: MAPPING ---
            with tab_map:
                st.subheader("AI Auto-Mapping")
                st.markdown("Use OpenAI to map these transactions to the **Master Chart of Accounts**.")
                
                if mapped_txs is None:
                    if st.button(f"🚀 Start AI Mapping for {uploaded_file.name}", key=f"btn_map_{i}"):
                        from app.services.local_mapper import LocalMapperService
                        mapper = LocalMapperService()
                        
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        
                        def update_progress(current, total):
                            pct = int((current / total) * 100)
                            progress_bar.progress(pct)
                            status_text.text(f"Mapping unique patterns: {current}/{total}")
                        
                        mapped_result = mapper.map_transactions(transactions, progress_callback=update_progress)
                        st.session_state[file_key]["mapped_transactions"] = mapped_result
                        st.rerun()
                else:
                    st.success("✅ Mapping Complete!")
                    
                    df_mapped = pd.DataFrame(mapped_txs)
                    
                    # Calculate stats
                    unmapped_count = len(df_mapped[df_mapped['category'] == 'Unmapped'])
                    if unmapped_count > 0:
                        st.warning(f"⚠️ {unmapped_count} transactions have Low Confidence and are marked 'Unmapped'. Please review them.")
                    
                    # Columns to edit (Added vendor for context)
                    edit_cols = ['category', 'mapped_account_name', 'confidence', 'reasoning', 'row_number', 'raw_desc', 'raw_account', 'vendor', 'amount']
                    
                    # Get Master COA options for dropdown
                    from app.services.local_mapper import LocalMapperService
                    master_account_names = [a['account_name'] for a in LocalMapperService.MASTER_COA]
                    
                    # Configure Grid
                    edited_df = st.data_editor(
                        df_mapped[edit_cols],
                        column_config={
                            "category": st.column_config.SelectboxColumn(
                                "Category",
                                options=["Unmapped", "Assets", "Liabilities", "Equity", "Revenue", "Expenses"],
                                required=True
                            ),
                            "mapped_account_name": st.column_config.SelectboxColumn(
                                "Account Name",
                                options=master_account_names,
                                required=True,
                                width="large"
                            ),
                            "confidence": st.column_config.NumberColumn(
                                "Conf.",
                                format="%.2f",
                                disabled=True
                            ),
                            "row_number": st.column_config.NumberColumn("Row", disabled=True),
                            "raw_desc": st.column_config.TextColumn("Description", disabled=True),
                            "raw_account": st.column_config.TextColumn("Raw Account", disabled=True),
                            "vendor": st.column_config.TextColumn("Vendor", disabled=True),
                            "amount": st.column_config.TextColumn("Amount", disabled=True),
                        },
                        disabled=["reasoning", "confidence", "row_number", "raw_desc", "raw_account", "vendor", "amount"],
                        use_container_width=True,
                        key=f"editor_{file_key}",
                        num_rows="fixed"
                    )
                    
                    # Update session state with edits
                    # Check if changes were made to the visible columns
                    if not df_mapped[edit_cols].equals(edited_df):
                         # Update the original full dataframe with the changes
                         # This preserves hidden columns like 'deal_id', 'source_file', etc.
                         df_mapped.update(edited_df)
                         
                         st.session_state[file_key]["mapped_transactions"] = df_mapped.to_dict('records')
                         # No need to rerun immediately as st.data_editor updates the UI state, 
                         # but for the Dashboard to update we might want to.
                         st.rerun() 
                    
                    if st.button("🔄 Re-run AI Mapping (Discard Edits)", key=f"btn_remap_{i}"):
                        st.session_state[file_key]["mapped_transactions"] = None
                        st.rerun()

            # --- TAB 3: DASHBOARD ---
            with tab_dash:
                st.subheader("📈 Financial Dashboard")
                
                if mapped_txs:
                    df_viz = pd.DataFrame(mapped_txs)
                    df_viz['amount_float'] = df_viz['amount'].astype(float)
                    
                    # KPI Cards
                    kpi1, kpi2, kpi3 = st.columns(3)
                    
                    total_spend = df_viz[df_viz['amount_float'] < 0]['amount_float'].sum() * -1
                    total_revenue = df_viz[df_viz['amount_float'] > 0]['amount_float'].sum()
                    
                    kpi1.metric("Total Inflows", f"${total_revenue:,.2f}")
                    kpi2.metric("Total Outflows", f"${total_spend:,.2f}")
                    kpi3.metric("Num Transactions", len(df_viz))
                    
                    st.divider()
                    
                    # CHARTS
                    c1, c2 = st.columns(2)
                    
                    with c1:
                        st.caption("Spend by Category (Expenses)")
                        # Filter only expenses (usually negative amount or Category=Expenses)
                        # For now, let's group by Category absolute sums
                        df_cat = df_viz.groupby('category')['amount_float'].sum().abs().reset_index()
                        st.bar_chart(df_cat, x='category', y='amount_float', color='category')
                        
                    with c2:
                        st.caption("Top 10 Vendors by Volume")
                        df_vendor = df_viz.groupby('vendor')['amount_float'].sum().abs().nlargest(10).reset_index()
                        st.bar_chart(df_vendor, x='vendor', y='amount_float') # Horizontal bar not natively simple in st.bar_chart without altair, but this works
                else:
                    st.info("⚠️ Run Mapping to see Dashboard")

            # --- TAB 4: REPORTS ---
            with tab_report:
                st.subheader("📋 Detailed Reports")
                
                if mapped_txs:
                    df_mapped = pd.DataFrame(mapped_txs)
                    
                    # Ensure amount is float for pivot
                    df_mapped['amount_float'] = df_mapped['amount'].astype(float)
                    
                    # Pivot Table
                    pivot = pd.pivot_table(
                        df_mapped, 
                        values='amount_float', 
                        index=['category', 'mapped_account_name'], 
                        aggfunc='sum'
                    ).reset_index()
                    
                    pivot['amount_float'] = pivot['amount_float'].apply(lambda x: f"${x:,.2f}")
                    
                    col_rep1, col_rep2 = st.columns([2, 1])
                    
                    with col_rep1:
                        st.dataframe(pivot, use_container_width=True)
                        
                    with col_rep2:
                        st.metric("Total Rows", len(df_mapped))
                        st.metric("Mapped Categories", pivot['category'].nunique())
                        
                        # CSV Export
                        csv = df_mapped.to_csv(index=False).encode('utf-8')
                        st.download_button(
                            label="📥 Download Mapped CSV",
                            data=csv,
                            file_name=f"mapped_{uploaded_file.name}.csv",
                            mime="text/csv"
                        )
                else:
                    st.info("⚠️ Please run AI MApping first to generate reports.")

# Sidebar info
with st.sidebar:
    st.header("ℹ️ How it works")
    st.markdown("""
    1. **Heuristic Detection**: Scans the first 50 rows for keywords (Date, Account, Amount, etc.) to find the header.
    2. **Normalization**: Maps column names to standard fields.
    3. **Parsing**: 
        - Extracts dates in multiple formats.
        - Parses amounts (handles currency symbols, negative parentheses, etc.).
        - Calculates Debits - Credits if 'Amount' column is missing.
    4. **Validation**: Checks if Total Debits matches Total Credits (Net = 0).
    5. **AI Mapping**: Uses **Batch Processing** to map transactions against a standard Chart of Accounts.
    """)
    st.markdown("---")
    st.caption("AceCPAs Local Test Tool")
