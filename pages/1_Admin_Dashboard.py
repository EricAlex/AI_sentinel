# pages/1_Admin_Dashboard.py

import os
import streamlit as st
import pandas as pd
import requests
import json

# --- FastAPI Backend URL ---
FASTAPI_URL = os.getenv("FASTAPI_URL", "http://fastapi_app:8000")

# --- Re-use call_api from app.py ---
# This assumes app.py is run as the main script and its functions are available
# In a multi-page app, Streamlit re-runs the main app.py on page navigation,
# so st.session_state and functions defined there are generally accessible.
# However, for explicit clarity and to avoid potential issues with Streamlit's execution model,
# it's better to import or redefine the necessary utility functions.
# For simplicity in this context, we'll assume call_api is accessible via st.session_state or a global import if app.py is always the entry.
# A more robust solution might involve a shared utility module.

# For now, let's assume call_api is available in st.session_state or imported from app.py
# If app.py is the main entry, its functions are generally available.
# To be safe, we can re-define a simplified version or ensure it's imported.

# Simplified call_api for this page, assuming access_token is in session_state
def call_api_admin(method, endpoint, json_data=None, data=None, params=None, headers=None, retry=True):
    if headers is None:
        headers = {}
    
    # Add Authorization header if access_token exists
    if st.session_state.get("access_token"):
        headers["Authorization"] = f"Bearer {st.session_state.access_token}"

    try:
        response = requests.request(method, f"{FASTAPI_URL}{endpoint}", json=json_data, data=data, params=params, headers=headers)
        
        # Simplified retry logic for admin page - full retry handled in app.py if needed
        if response.status_code == 401 and retry:
            st.error("Session expired. Please log in again.")
            st.session_state.logged_in = False
            st.session_state.access_token = None
            st.session_state.current_user = None
            st.cache_data.clear()
            st.rerun()
        return response.json(), response.status_code
    except requests.exceptions.RequestException as e:
        st.error(f"API call to {endpoint} failed: {e}")
        return {"detail": str(e)}, 500

# --- API Calls for LLM Configuration ---
def get_llm_config_api():
    data, status_code = call_api_admin("get", "/llm_config/")
    if status_code == 200:
        return data
    return None

def create_update_llm_config_api(llm_config_data):
    return call_api_admin("post", "/llm_config/", json_data=llm_config_data)

# --- API Calls for Source Management ---
def get_sources_api():
    data, status_code = call_api_admin("get", "/sources/")
    if status_code == 200:
        return data
    return []

def add_source_api(source_data):
    return call_api_admin("post", "/sources/", json_data=source_data)

def update_source_api(source_id, source_data):
    return call_api_admin("put", f"/sources/{source_id}", json_data=source_data)

def delete_source_api(source_id):
    _, status_code = call_api_admin("delete", f"/sources/{source_id}")
    return status_code

# --- Page Configuration and Authentication ---
st.set_page_config(page_title="System Dashboard", layout="wide", page_icon="⚙️")
st.title("⚙️ System Health & Governance")

# Retrieve current user from session state (set by app.py)
current_user = st.session_state.get('current_user')
access_token = st.session_state.get('access_token')

if not current_user or not access_token:
    st.error("You must be logged in to access the Admin Dashboard.")
    st.stop()

if not current_user['is_admin']:
    st.error("You must be a tenant administrator to access this page.")
    st.stop()

st.success(f"Access Granted. Welcome, Admin {current_user['username']}.")

# --- Tabbed Interface for Organization ---
tab1, tab2, tab3, tab4, tab5 = st.tabs(["📊 Health", "🚩 Flag Review", "🤖 Parser Healing", "📜 Source Management", "🧠 LLM Configuration"])

# --- Health Dashboard Tab ---
with tab1:
    st.header("Live System Status")
    
    if st.button("Refresh Stats"):
        st.rerun()

    # Health checks still directly query the services for now
    # In a more complex setup, these might also go through the FastAPI backend
    from health import get_celery_stats, get_db_status, get_redis_status, get_system_usage
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
    # This still directly accesses the DB, could be moved to FastAPI if needed
    from database import SessionLocal, CorrectionFlag, ProgressItem
    db = SessionLocal()
    try:
        # Query for pending flags and join with the related progress item to get its title
        pending_flags = db.query(CorrectionFlag, ProgressItem).join(
            ProgressItem, CorrectionFlag.item_id == ProgressItem.id
        ).filter(
            CorrectionFlag.tenant_id == current_user['tenant_id'],
            CorrectionFlag.status == 'pending'
        ).order_by(CorrectionFlag.created_at.desc()).all()

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
    # This still directly accesses the DB, could be moved to FastAPI if needed
    from database import SessionLocal, ParserProposal, Source
    from sourcerer import attempt_heal_parser # Import the task
    db = SessionLocal()
    try:
        pending_proposals = db.query(ParserProposal).join(Source).filter(
            ParserProposal.tenant_id == current_user['tenant_id'],
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
                            # The apply_parser_fix task is now obsolete, the healing directly applies
                            # We can re-trigger the healing process if needed, or just mark as approved
                            # For now, we'll just mark it as approved and rely on the healing process to have applied it.
                            proposal_to_update = db.query(CorrectionFlag).get(proposal.id)
                            proposal_to_update.status = 'approved'
                            db.commit()
                            st.success(f"Proposal for {source.name} marked as approved. The fix should have been applied during healing.")
                            st.rerun()
                    with b_col2:
                        if st.button("❌ Reject Fix", key=f"reject_{proposal.id}", type="primary", use_container_width=True):
                            proposal_to_update = db.query(CorrectionFlag).get(proposal.id)
                            proposal_to_update.status = 'rejected'
                            db.commit()
                            st.rerun()
    finally:
        db.close()

# --- Source Management Tab ---
with tab4:
    st.header("Manage Ingestion Sources")

    # --- Section 1: Add a New Source ---
    st.subheader("Add New Source")
    with st.form("new_source_form", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            new_name = st.text_input("Source Name", placeholder="e.g., My Favorite AI Blog")
        with col2:
            new_url = st.text_input("Source URL", placeholder="https://example.com/blog")
        with col3:
            # PARSER_MAP is no longer directly used here, but we can list common types
            parser_types = ['blog', 'news', 'arxiv', 'other']
            new_type = st.selectbox("Parser Type", options=parser_types, help="Select the general type of content.")
        
        add_button = st.form_submit_button("Add Source")
        if add_button:
            if new_name and new_url and new_type:
                source_data = {
                    "name": new_name,
                    "url": new_url,
                    "source_type": new_type,
                    "is_active": True, # Default to active
                    "is_shared": False # Default to not shared for tenant-added sources
                }
                response_data, status_code = add_source_api(source_data)
                if status_code == 200:
                    st.success(f"Source '{new_name}' added successfully!")
                    st.rerun()
                else:
                    st.error(f"Failed to add source: {response_data.get('detail', 'Unknown error')}")
            else:
                st.error("Please fill in all fields.")

    st.divider()

    # --- Section 2: Edit Existing Sources ---
    st.subheader("Edit Existing Sources")
    
    sources_data = get_sources_api()
    if not sources_data:
        st.info("No sources found for your tenant. Add one using the form above.")
    else:
        with st.form("edit_sources_form"):
            source_list = [
                {"ID": s['id'], "Name": s['name'], "URL": s['url'], "Parser Type": s['source_type'], "Is Active": s['is_active'], "Is Shared": s['is_shared']}
                for s in sources_data
            ]
            df_sources = pd.DataFrame(source_list)
            
            edited_df = st.data_editor(
                df_sources,
                column_config={
                    "ID": st.column_config.NumberColumn("ID", disabled=True),
                    "Is Active": st.column_config.CheckboxColumn("Active?", default=True),
                    "Is Shared": st.column_config.CheckboxColumn("Shared?", disabled=True), # Shared sources cannot be changed by tenant
                    "Parser Type": st.column_config.SelectboxColumn("Parser", options=['blog', 'news', 'arxiv', 'other']),
                },
                use_container_width=True,
                hide_index=True,
                num_rows="dynamic",
                key="source_editor"
            )
            
            save_button = st.form_submit_button("Save Changes to All Sources")

            if save_button:
                original_data_map = {item["ID"]: item for item in source_list}
                edited_data_map = {item["ID"]: item for item in edited_df.to_dict('records')}
                
                changes_made = False
                
                # Check for updated or modified rows
                for source_id, edited_row in edited_data_map.items():
                    # Only allow updates if the source is not shared or if it's a system admin
                    if not edited_row['Is Shared'] or current_user['tenant_id'] == "system_shared_sources":
                        if source_id not in original_data_map or original_data_map[source_id] != edited_row:
                            changes_made = True
                            update_data = {
                                'name': edited_row['Name'],
                                'url': edited_row['URL'],
                                'source_type': edited_row['Parser Type'],
                                'is_active': edited_row['Is Active']
                            }
                            response_data, status_code = update_source_api(source_id, update_data)
                            if status_code != 200:
                                st.error(f"Failed to update source {edited_row['Name']}: {response_data.get('detail', 'Unknown error')}")
                    else:
                        st.warning(f"Cannot modify shared source: {edited_row['Name']}")

                # Check for deleted rows
                for source_id in original_data_map:
                    if source_id not in edited_data_map:
                        # Only allow deletion if the source is not shared
                        if not original_data_map[source_id]['Is Shared']:
                            changes_made = True
                            status_code = delete_source_api(source_id)
                            if status_code != 204:
                                st.error(f"Failed to delete source ID {source_id}.")
                        else:
                            st.warning(f"Cannot delete shared source: {original_data_map[source_id]['Name']}")
                
                if changes_made:
                    st.success("All changes saved successfully!")
                    st.rerun()
                else:
                    st.info("No changes were detected to save.")

# --- LLM Configuration Tab ---
with tab5:
    st.header("LLM Configuration")
    st.info("Configure the Large Language Model settings for your tenant.")

    llm_config = get_llm_config_api()

    with st.form("llm_config_form"):
        st.subheader("LLM Provider Settings")
        
        # Default values for the form
        default_provider = llm_config['llm_provider'] if llm_config else "google"
        default_model = llm_config['llm_model_name'] if llm_config else "gemini-2.5-flash"
        # API key is never returned by the API, so it will always be empty here
        default_api_key = ""
        default_base_url = llm_config['base_url'] if llm_config else ""
        default_custom_settings = str(llm_config['custom_settings']) if llm_config and llm_config['custom_settings'] else "{}"

        llm_provider = st.selectbox("LLM Provider", options=["google", "openai", "huggingface"], index=["google", "openai", "huggingface"].index(default_provider) if default_provider in ["google", "openai", "huggingface"] else 0)
        llm_model_name = st.text_input("LLM Model Name", value=default_model)
        api_key = st.text_input("API Key", type="password", value=default_api_key, help="Enter your API key. It will not be displayed after saving.")
        base_url = st.text_input("Base URL (Optional)", value=default_base_url, help="For custom API endpoints, e.g., for self-hosted models.")
        custom_settings_str = st.text_area("Custom Settings (JSON, Optional)", value=default_custom_settings, help="Enter a JSON string for provider-specific settings.")

        submitted = st.form_submit_button("Save LLM Configuration")

        if submitted:
            try:
                custom_settings = json.loads(custom_settings_str) if custom_settings_str else {}
            except json.JSONDecodeError:
                st.error("Invalid JSON for Custom Settings. Please enter a valid JSON string.")
                st.stop()

            llm_config_data = {
                "llm_provider": llm_provider,
                "llm_model_name": llm_model_name,
                "api_key": api_key,
                "base_url": base_url,
                "custom_settings": custom_settings
            }
            response_data, status_code = create_update_llm_config_api(llm_config_data)
            if status_code == 200:
                st.success("LLM Configuration saved successfully!")
                st.rerun()
            else:
                st.error(f"Failed to save LLM Configuration: {response_data.get('detail', 'Unknown error')}")
