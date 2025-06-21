# pages/1_Admin_Dashboard.py

import os
import streamlit as st
import pandas as pd
from database import (SessionLocal, CorrectionFlag, ProgressItem, ParserProposal, Source,
                     get_all_sources, add_new_source, update_source, delete_source)
from health import get_celery_stats, get_db_status, get_redis_status, get_system_usage
from sourcerer import apply_parser_fix
from parsers import PARSER_MAP
from dotenv import load_dotenv

load_dotenv()

# --- Page Configuration and Authentication ---
st.set_page_config(page_title="System Dashboard", layout="wide", page_icon="⚙️")
st.title("⚙️ System Health & Governance")

# Simple password protection for the admin page
password = st.text_input("Enter Admin Password", type="password")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")

if password != ADMIN_PASSWORD:
    st.error("Incorrect password. Access denied.")
    st.stop()

st.success("Access Granted. Welcome, Admin.")

# --- Tabbed Interface for Organization ---
tab1, tab2, tab3, tab4 = st.tabs(["📊 Health", "🚩 Flag Review", "🤖 Parser Healing", "📜 Source Management"])

# --- Health Dashboard Tab ---
with tab1:
    st.header("Live System Status")
    
    if st.button("Refresh Stats"):
        st.rerun()

    st.subheader("Core Infrastructure")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("PostgreSQL DB", get_db_status())
    with col2:
        st.metric("Redis Broker", get_redis_status())
    with col3:
        celery_stats = get_celery_stats()
        st.metric("Celery System Status", celery_stats.get('status', 'Unknown'))
        st.caption(celery_stats.get('message', ''))

    st.subheader("Background Processing Stats")
    stat_col1, stat_col2, stat_col3 = st.columns(3)
    with stat_col1:
        st.metric("Active Workers", celery_stats.get('active_workers', 'N/A'))
    with stat_col2:
        st.metric("Tasks in Progress", celery_stats.get('tasks_in_progress', 'N/A'))
    with stat_col3:
        st.metric("Total Tasks Processed", celery_stats.get('total_tasks_processed', 'N/A'))
    
    st.subheader("Host System Usage")
    usage = get_system_usage()
    s1, s2 = st.columns(2)
    s1.metric("CPU Usage", f"{usage.get('cpu_percent', 0)}%")
    s2.metric("Memory Usage", f"{usage.get('memory_percent', 0)}%")


# --- Flag Review Tab ---
with tab2:
    st.header("Content Governance: Pending Flags")
    db = SessionLocal()
    try:
        # Query for pending flags and join with the related progress item to get its title
        pending_flags = db.query(CorrectionFlag, ProgressItem).join(
            ProgressItem, CorrectionFlag.item_id == ProgressItem.id
        ).filter(CorrectionFlag.status == 'pending').order_by(CorrectionFlag.created_at.desc()).all()

        if not pending_flags:
            st.success("No pending flags to review. All content is clear!")
        else:
            st.info(f"You have {len(pending_flags)} items to review.")
            for flag, item in pending_flags:
                with st.container(border=True):
                    st.subheader(f"Flag for: *{item.title}*")
                    st.write(f"**Reason:** {flag.reason}")
                    if flag.user_comment:
                        st.write(f"**User Comment:** {flag.user_comment}")
                    st.caption(f"Flagged on: {flag.created_at.strftime('%Y-%m-%d %H:%M')} UTC")

                    b_col1, b_col2 = st.columns(2)
                    with b_col1:
                        if st.button("Mark as Resolved", key=f"resolve_{flag.id}", use_container_width=True):
                            flag_to_update = db.query(CorrectionFlag).get(flag.id)
                            flag_to_update.status = 'resolved'
                            db.commit()
                            st.rerun()
                    with b_col2:
                        if st.button("Delete Flag", key=f"delete_{flag.id}", type="primary", use_container_width=True):
                            flag_to_delete = db.query(CorrectionFlag).get(flag.id)
                            db.delete(flag_to_delete)
                            db.commit()
                            st.rerun()
    finally:
        db.close()

# --- Parser Healing Tab ---
with tab3:
    st.header("AI-Generated Parser Fixes")
    db = SessionLocal()
    try:
        pending_proposals = db.query(ParserProposal).join(Source).filter(
            ParserProposal.status == 'pending_review'
        ).all()

        if not pending_proposals:
            st.success("No pending parser proposals to review. All parsers are healthy or have no proposed fixes yet.")
        else:
            st.info(f"You have {len(pending_proposals)} parser fixes to review.")
            for proposal in pending_proposals:
                source = db.query(Source).get(proposal.source_id)
                with st.container(border=True):
                    st.subheader(f"Proposed Fix for: `{source.name}`")
                    st.caption(f"Proposed on: {proposal.created_at.strftime('%Y-%m-%d %H:%M')} UTC")

                    st.markdown("##### AI-Generated Python Code:")
                    st.code(proposal.proposed_code, language='python')
                    
                    st.markdown("##### Validation Sample (what the new code found):")
                    st.json(proposal.validation_output_sample, expanded=False)

                    b_col1, b_col2 = st.columns(2)
                    with b_col1:
                        if st.button("✅ Approve & Apply Fix", key=f"approve_{proposal.id}", use_container_width=True):
                            # Trigger a background task to apply the fix
                            apply_parser_fix.delay(proposal.id)
                            st.success(f"Approval task sent for {source.name}. The fix will be applied in the background. Please restart the celery_worker and celery_beat services to activate the new parser.")
                            st.rerun()
                    with b_col2:
                        if st.button("❌ Reject Fix", key=f"reject_{proposal.id}", type="primary", use_container_width=True):
                            proposal_to_update = db.query(ParserProposal).get(proposal.id)
                            proposal_to_update.status = 'rejected'
                            db.commit()
                            st.rerun()
    finally:
        db.close()

# --- Source Management Tab ---
with tab4:
    st.header("Manage Ingestion Sources")

    # --- Section 1: Add a New Source (This form is already correct) ---
    st.subheader("Add New Source")
    with st.form("new_source_form", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            new_name = st.text_input("Source Name", placeholder="e.g., My Favorite AI Blog")
        with col2:
            new_url = st.text_input("Source URL", placeholder="https://example.com/blog")
        with col3:
            parser_types = list(PARSER_MAP.keys()) + ['other', 'arxiv']
            new_type = st.selectbox("Parser Type", options=parser_types, help="Select the parser that matches the site's layout.")
        
        add_button = st.form_submit_button("Add Source")
        if add_button:
            if new_name and new_url and new_type:
                add_new_source(name=new_name, url=new_url, source_type=new_type)
                st.success(f"Source '{new_name}' added successfully! It will be scraped on the next cycle.")
                st.rerun()
            else:
                st.error("Please fill in all fields.")

    st.divider()

    # --- Section 2: Edit Existing Sources ---
    st.subheader("Edit Existing Sources")
    
    sources_data = get_all_sources()
    if not sources_data:
        st.info("No sources found in the database. Add one using the form above.")
    else:
        # --- NEW: Wrap the editor and save button in a form ---
        with st.form("edit_sources_form"):
            source_list = [
                {"ID": s.id, "Name": s.name, "URL": s.url, "Parser Type": s.source_type, "Is Active": s.is_active}
                for s in sources_data
            ]
            df_sources = pd.DataFrame(source_list)
            
            # The data editor itself goes inside the form
            edited_df = st.data_editor(
                df_sources,
                column_config={
                    "ID": st.column_config.NumberColumn("ID", disabled=True),
                    "Is Active": st.column_config.CheckboxColumn("Active?", default=True),
                    "Parser Type": st.column_config.SelectboxColumn("Parser", options=list(PARSER_MAP.keys()) + ['other', 'arxiv']),
                },
                use_container_width=True,
                hide_index=True,
                num_rows="dynamic",
                key="source_editor"
            )
            
            # The crucial submit button for this form
            save_button = st.form_submit_button("Save Changes to All Sources")

            if save_button:
                # This logic now only runs when the form is submitted
                original_data_map = {item["ID"]: item for item in source_list}
                edited_data_map = {item["ID"]: item for item in edited_df.to_dict('records')}
                
                changes_made = False
                
                # Check for updated or modified rows
                for source_id, edited_row in edited_data_map.items():
                    if source_id not in original_data_map or original_data_map[source_id] != edited_row:
                        changes_made = True
                        update_data = {
                            'name': edited_row['Name'],
                            'url': edited_row['URL'],
                            'source_type': edited_row['Parser Type'],
                            'is_active': edited_row['Is Active']
                        }
                        update_source(source_id, update_data)

                # Check for deleted rows
                for source_id in original_data_map:
                    if source_id not in edited_data_map:
                        changes_made = True
                        delete_source(source_id)
                
                if changes_made:
                    st.success("All changes saved successfully!")
                    st.rerun()
                else:
                    st.info("No changes were detected to save.")
