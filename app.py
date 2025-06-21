# app.py

# --- ChromaDB System Hack ---
# This block must be at the very top of the file
# to ensure the correct sqlite3 version is loaded
# before chromadb is imported.
__import__('pysqlite3')
import sys
sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')
# --- End of Hack ---

import os
import math
import re
import streamlit as st
import pandas as pd
import chromadb
from sentence_transformers import SentenceTransformer

# Import all necessary functions from our other modules
from database import (
    SessionLocal,
    get_all_progress_items,
    FollowedTerm,
    CorrectionFlag,
    add_new_source,  # Though used in admin page, good to have access
)
from ui_components import render_progress_card

# --- 1. Page Configuration ---
# This should be the very first Streamlit command in your script.
st.set_page_config(
    page_title="The AI Progress Sentinel",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- 2. Caching and Resource Loading ---
# Use @st.cache_resource for objects that should be loaded only once and shared
# across all user sessions, like models and database clients.
LOCAL_MODEL_PATH = '/app/models/all-MiniLM-L6-v2'

@st.cache_resource
def get_embedding_model():
    """Loads the Sentence Transformer model from a local path inside the container."""
    print("Loading embedding model from local path...")
    return SentenceTransformer(LOCAL_MODEL_PATH)

@st.cache_resource
def get_chroma_client():
    """Connects to the ChromaDB vector database."""
    print("Connecting to ChromaDB...")
    CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
    CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
    return chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)

# Use @st.cache_data for functions that return serializable data (like DataFrames).
# The `ttl` (time-to-live) argument automatically invalidates the cache after 60 seconds.
@st.cache_data(ttl=60)
def load_data():
    """Loads and caches the main progress data from PostgreSQL."""
    print("Loading data from PostgreSQL...")
    return get_all_progress_items()

# --- 3. Initialization ---
# Load all shared resources and data at the start.
model = get_embedding_model()
client = get_chroma_client()
progress_collection = client.get_or_create_collection(name="ai_progress")
all_data = load_data()

# Initialize session_state variables if they don't exist
if "page_number" not in st.session_state:
    st.session_state.page_number = 1
if "page_size" not in st.session_state:
    st.session_state.page_size = 10

# Define the available languages as a dictionary (Name -> Code)
LANGUAGES = {'English': 'en', '中文 (Chinese)': 'zh'}

# 1. Read the language from the URL query parameter first.
query_params = st.query_params.to_dict()
# Default to 'en' if the 'lang' param is missing or invalid.
initial_lang_code = query_params.get("lang", "en")
if initial_lang_code not in LANGUAGES.values():
    initial_lang_code = 'en'

# 2. Set the session state from the URL parameter. This runs on every script run.
st.session_state.display_language = initial_lang_code

# --- 4. Main App UI ---
st.title("🧠 The AI Progress Sentinel")
st.caption("AI-Powered Summaries & Rankings of AI Progress. Continuously Updated.")

if not all_data:
    st.warning("The database is currently empty. Please wait for the scraper and workers to populate it with data.")
    st.stop()

# Prepare the main DataFrame for filtering.
df = pd.DataFrame(all_data)
df['id'] = df['id'].astype(str)
df['published_date'] = pd.to_datetime(df['published_date'])


# --- 5. Sidebar for Controls & Personalization ---
with st.sidebar:
    st.header("Display Options")
    
    # A callback function to update the URL when the selection changes.
    def language_changed():
        selected_name = st.session_state.language_selector_key
        new_lang_code = LANGUAGES[selected_name]
        # Update both the session state AND the URL query parameter.
        st.session_state.display_language = new_lang_code
        st.query_params.lang = new_lang_code

    # Get the index for the dropdown's default value.
    current_lang_name = next((name for name, code in LANGUAGES.items() if code == st.session_state.display_language), 'English')
    lang_names = list(LANGUAGES.keys())
    current_index = lang_names.index(current_lang_name)

    st.selectbox(
        "Display Language:",
        options=lang_names,
        index=current_index,
        key="language_selector_key",
        on_change=language_changed
    )

    st.divider()
    st.header("Filters & Controls")
    if st.button("🔄 Refresh Data", use_container_width=True):
        st.cache_data.clear()
        # We preserve the language by not calling st.session_state.clear()
        # Instead, we just reset the page number.
        st.session_state.page_number = 1
        st.rerun()

    # --- Search Section ---
    st.subheader("Search")
    semantic_query = st.text_input("Search for concepts...", placeholder="e.g., alternatives to transformers")
    search_term = st.text_input("Filter results by keyword...", placeholder="e.g., mamba, sora")
    
    # --- Sorting Options ---
    sort_options = ["Importance Score", "Date"]
    # Only show "Relevance" as a sorting option if a semantic search is active.
    if semantic_query:
        sort_options.insert(0, "Relevance")
    sort_key = st.selectbox("Sort by", options=sort_options, index=0)
    
    # --- Source Filtering ---
    st.subheader("Filter by Source")
    all_sources = sorted(df['source'].unique())
    selected_sources = st.multiselect("Sources", options=all_sources, default=all_sources)

    # --- Pagination Controls ---
    st.divider()
    st.header("Paging")
    st.number_input(
        "Items per page:", 
        min_value=5, 
        max_value=50, 
        step=5,
        key="page_size" # This key directly links the widget to st.session_state.page_size
    )

    # --- Personalization Section ---
    st.divider()
    st.header("My Feed")
    db = SessionLocal()
    try:
        followed_terms = [row.term for row in db.query(FollowedTerm.term).all()]
        st.write("Following:", f"`{', '.join(followed_terms)}`" if followed_terms else "Nothing yet.")
        
        with st.form("follow_form", clear_on_submit=True):
            new_term = st.text_input("Follow a new keyword/author:")
            submitted = st.form_submit_button("Follow Term")
            if submitted and new_term:
                term_exists = db.query(FollowedTerm).filter(FollowedTerm.term == new_term.lower()).first()
                if not term_exists:
                    db.add(FollowedTerm(term=new_term.lower()))
                    db.commit()
                    st.rerun()
    finally:
        db.close()


# --- 6. Filtering and Sorting Logic ---
# This block processes the full dataset based on the sidebar controls.
results_df = df

# Apply Semantic Search first, as it's the most restrictive filter
if semantic_query:
    with st.spinner("Searching for semantically similar items..."):
        query_embedding = model.encode(semantic_query).tolist()
        results = progress_collection.query(query_embeddings=[query_embedding], n_results=50) # Get top 50 relevant
        relevant_ids = results['ids'][0]
        if not relevant_ids:
            results_df = pd.DataFrame()
        else:
            results_df = df[df['id'].isin(relevant_ids)].copy()
            relevance_scores = {id_str: dist for id_str, dist in zip(results['ids'][0], results['distances'][0])}
            results_df['relevance'] = results_df['id'].map(relevance_scores)

# Apply standard filters to the (potentially semantically filtered) dataframe
if selected_sources:
    results_df = results_df[results_df['source'].isin(selected_sources)]
if search_term:
    term_lower = search_term.lower()
    results_df = results_df[results_df.apply(
        lambda row: term_lower in str(row['title']).lower() or term_lower in str(row['keywords']).lower(),
        axis=1
    )]

# Apply Sorting
if sort_key == "Relevance" and 'relevance' in results_df.columns:
    sorted_df = results_df.sort_values('relevance', ascending=True)
elif sort_key == "Importance Score":
    sorted_df = results_df.sort_values('overall_importance_score', ascending=False)
else: # Default to sorting by Date
    sorted_df = results_df.sort_values('published_date', ascending=False)


# --- 7. Main Content Area with Tabs ---
tab_all, tab_feed = st.tabs(["🔥 All Progress", "👤 My Feed"])

# --- "All Progress" Tab ---
with tab_all:
    # --- Pagination Logic ---
    total_items = len(sorted_df)
    page_size = st.session_state.page_size
    total_pages = math.ceil(total_items / page_size) if page_size > 0 else 1
    st.session_state.page_number = max(1, min(st.session_state.page_number, total_pages))

    start_index = (st.session_state.page_number - 1) * page_size
    end_index = start_index + page_size
    paginated_df = sorted_df.iloc[start_index:end_index]

    # --- Pagination UI Display ---
    st.subheader(f"Showing {len(paginated_df)} of {total_items} breakthroughs")
    
    p_col1, p_col2, p_col3, p_col4 = st.columns([2, 2, 1, 5])
    if p_col1.button("⬅️ Previous", use_container_width=True, disabled=(st.session_state.page_number <= 1)):
        st.session_state.page_number -= 1
        st.rerun()
    if p_col2.button("Next ➡️", use_container_width=True, disabled=(st.session_state.page_number >= total_pages)):
        st.session_state.page_number += 1
        st.rerun()
    p_col3.number_input("Page", min_value=1, max_value=total_pages, key="page_number", label_visibility="collapsed")
    p_col4.markdown(f"<div style='text-align: right; padding-top: 10px;'>Page {st.session_state.page_number} of {total_pages}</div>", unsafe_allow_html=True)
    st.divider()

    # --- Display Results ---
    if paginated_df.empty:
        st.info("No results match your criteria.")
    else:
        for _, item in paginated_df.iterrows():
            card_container = st.container(border=True)
            render_progress_card(item.to_dict(), card_container, 
                                 lang_code=st.session_state.display_language, 
                                 key_prefix="all_progress")
            
            # Logic for handling the "Flag for Review" form submission
            if st.session_state.get(f"flagging_item_id_all_progress") == item['id']:
                with st.form(key=f"form_flag_all_{item['id']}", clear_on_submit=True):
                    st.warning(f"Flagging: {item['title']}")
                    reason = st.selectbox("Reason:", ["Inaccurate Summary", "Incorrect Score", "Misleading Title", "Other"], key=f"reason_all_{item['id']}")
                    comment = st.text_area("Optional Comment:", key=f"comment_all_{item['id']}")
                    submitted = st.form_submit_button("Submit Flag")
                    if submitted:
                        db = SessionLocal()
                        try:
                            new_flag = CorrectionFlag(item_id=int(item['id']), reason=reason, user_comment=comment)
                            db.add(new_flag)
                            db.commit()
                            st.success("Flag submitted for review. Thank you!")
                        finally:
                            db.close()
                        del st.session_state[f"flagging_item_id_all_progress"]
                        st.rerun()

# --- "My Feed" Tab ---
with tab_feed:
    if not followed_terms:
        st.info("You are not following any terms. Add some in the sidebar to create your personalized feed.")
    else:
        # Create a case-insensitive regex pattern from the list of followed terms.
        # re.escape ensures that special characters in terms (like C++) are treated literally.
        try:
            pattern = '|'.join(map(re.escape, followed_terms))
            
            # Filter the main DataFrame for items matching any followed term in title or keywords.
            # `na=False` ensures that rows with missing keywords don't cause errors.
            my_feed_df = df[
                df['title'].str.lower().str.contains(pattern, case=False, na=False) |
                df['keywords'].astype(str).str.lower().str.contains(pattern, case=False, na=False)
            ].sort_values('published_date', ascending=False)
        except re.error as e:
            st.error(f"Could not process followed terms due to a regular expression error: {e}")
            my_feed_df = pd.DataFrame() # Create an empty DataFrame on error

        
        st.subheader(f"Found {len(my_feed_df)} items related to your interests")
        
        if my_feed_df.empty:
            st.write("No recent progress matches your followed terms.")
        else:
            # Note: Pagination is not implemented for this tab for simplicity.
            # All matching results are shown.
            for _, item in my_feed_df.iterrows():
                card_container = st.container(border=True)
                
                # --- PASS A DIFFERENT, UNIQUE PREFIX ---
                # This is the crucial fix to prevent key collisions with the "All Progress" tab.
                render_progress_card(
                    item.to_dict(),
                    card_container,
                    lang_code=st.session_state.display_language,
                    key_prefix="my_feed"  # A unique prefix for this rendering context
                )
                
                # --- UPDATED Flagging Logic for this specific tab ---
                # Check for the unique session state key for the "My Feed" tab.
                if st.session_state.get(f"flagging_item_id_my_feed") == item['id']:
                    # Use a unique key for the form as well to avoid conflicts.
                    with st.form(key=f"form_flag_feed_{item['id']}", clear_on_submit=True):
                        st.warning(f"Flagging: {item['title']}")
                        
                        # Every widget inside the form also needs a unique key.
                        reason = st.selectbox(
                            "Reason:",
                            ["Inaccurate Summary", "Incorrect Score", "Misleading Title", "Other"],
                            key=f"reason_feed_{item['id']}"
                        )
                        comment = st.text_area("Optional Comment:", key=f"comment_feed_{item['id']}")
                        
                        submitted = st.form_submit_button("Submit Flag")
                        if submitted:
                            db = SessionLocal()
                            try:
                                new_flag = CorrectionFlag(
                                    item_id=int(item['id']),
                                    reason=reason,
                                    user_comment=comment
                                )
                                db.add(new_flag)
                                db.commit()
                                st.success("Flag submitted for review. Thank you!")
                            finally:
                                db.close()
                            
                            # Delete the specific session state key for this tab's form.
                            del st.session_state[f"flagging_item_id_my_feed"]
                            st.rerun()