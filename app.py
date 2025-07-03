# app.py

# --- ChromaDB System Hack ---
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
    delete_followed_term  # Import the new delete function
)
from ui_components import render_progress_card
from celery.result import AsyncResult
from tasks import run_scraper_cycle
from sourcerer import find_new_sources

# --- 1. Page Configuration ---
st.set_page_config(
    page_title="The AI Progress Sentinel",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- 2. Caching and Resource Loading ---
LOCAL_MODEL_PATH = '/app/models/all-MiniLM-L6-v2'

@st.cache_resource
def get_embedding_model():
    print("Loading embedding model from local path...")
    return SentenceTransformer(LOCAL_MODEL_PATH)

def get_chroma_client():
    print("Connecting to ChromaDB...")
    CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
    CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
    return chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)

@st.cache_data(ttl=60)
def load_data():
    print("Loading data from PostgreSQL...")
    return get_all_progress_items()

# --- 3. Initialization ---
model = get_embedding_model()
client = get_chroma_client()
progress_collection = client.get_or_create_collection(name="ai_progress")
all_data = load_data()
st.cache_data.clear() # Clear cache on app start to ensure fresh data

# Initialize session state for BOTH tabs' pagination independently
if "all_progress_page" not in st.session_state:
    st.session_state.all_progress_page = 1
if "my_feed_page" not in st.session_state:
    st.session_state.my_feed_page = 1
if "page_size" not in st.session_state:
    st.session_state.page_size = 10


# Persistent Language State Logic
LANGUAGES = {'English': 'en', '中文 (Chinese)': 'zh'}
query_params = st.query_params.to_dict()
initial_lang_code = query_params.get("lang", "en")
if initial_lang_code not in LANGUAGES.values():
    initial_lang_code = 'en'
st.session_state.display_language = initial_lang_code

# --- 4. Sidebar ---
with st.sidebar:
    st.header("Display Options")
    
    def language_changed():
        selected_name = st.session_state.language_selector_key
        new_lang_code = LANGUAGES[selected_name]
        st.session_state.display_language = new_lang_code
        st.query_params.lang = new_lang_code

    current_lang_name = next((name for name, code in LANGUAGES.items() if code == st.session_state.display_language), 'English')
    lang_names = list(LANGUAGES.keys())
    current_index = lang_names.index(current_lang_name)

    st.selectbox("Display Language:", options=lang_names, index=current_index, key="language_selector_key", on_change=language_changed)

    st.divider()
    st.header("Filters & Controls")
    if st.button("🔄 Refresh Data", use_container_width=True):
        st.cache_data.clear()
        st.session_state.all_progress_page = 1
        st.session_state.my_feed_page = 1
        st.rerun()

    st.subheader("Search")
    semantic_query = st.text_input("Search for concepts...", placeholder="e.g., efficient transformers", key="semantic_query_input")
    search_term = st.text_input("Filter results by keyword...", placeholder="e.g., mamba", key="keyword_search_input")

    sort_options = ["Importance Score", "Date"]
    default_sort_value = "Importance Score" # Default if no semantic query

    if semantic_query:
        sort_options.insert(0, "Relevance")
        default_sort_value = "Relevance" # If semantic query, default to Relevance

    # Use a session state variable to control the default value of the selectbox
    # This ensures that when semantic_query is active, "Relevance" is pre-selected.
    if "current_sort_key" not in st.session_state:
        st.session_state.current_sort_key = default_sort_value
    elif semantic_query and st.session_state.current_sort_key != "Relevance":
        # If semantic query is active, and sort key is not Relevance, set it to Relevance
        st.session_state.current_sort_key = "Relevance"
    elif not semantic_query and st.session_state.current_sort_key == "Relevance":
        # If semantic query is NOT active, and sort key IS Relevance, reset it to default
        st.session_state.current_sort_key = "Importance Score"

    sort_key = st.selectbox("Sort by", options=sort_options, key="sort_by_selectbox", index=sort_options.index(st.session_state.current_sort_key))
    
    all_sources = sorted(list(set(item['source'] for item in all_data))) if all_data else []
    selected_sources = st.multiselect("Filter by Source", options=all_sources, default=all_sources)

    st.divider()
    st.header("Paging")
    st.number_input("Items per page:", min_value=5, max_value=50, step=5, key="page_size")

    # --- Term Management UI ---
    st.divider()
    st.header("Manage My Feed")
    db = SessionLocal()
    try:
        followed_terms = [row.term for row in db.query(FollowedTerm.term).all()]
        if not followed_terms:
            st.caption("Not following any terms yet.")
        else:
            for term in followed_terms:
                term_col, button_col = st.columns([4, 1])
                term_col.write(f"• `{term}`")
                if button_col.button("❌", key=f"delete_term_{term}", help=f"Stop following '{term}'"):
                    delete_followed_term(term)
                    st.rerun()
        
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


    # --- Admin Actions ---
    st.divider()
    st.header("Admin Actions")

    if st.button("Run Scraper Cycle", use_container_width=True):
        task = run_scraper_cycle.delay()
        st.session_state['scraper_task_id'] = task.id

    if st.button("Find New Sources", use_container_width=True):
        task = find_new_sources.delay()
        st.session_state['sourcerer_task_id'] = task.id

    if 'scraper_task_id' in st.session_state:
        task_id = st.session_state['scraper_task_id']
        result = AsyncResult(task_id)
        st.progress(1 if result.ready() else 0, text=f"Scraper: {result.state}")
        if result.ready():
            with st.expander("Scraper Result"):
                st.write(result.get())
            del st.session_state['scraper_task_id']


    if 'sourcerer_task_id' in st.session_state:
        task_id = st.session_state['sourcerer_task_id']
        result = AsyncResult(task_id)
        st.progress(1 if result.ready() else 0, text=f"Sourcerer: {result.state}")
        if result.ready():
            with st.expander("Sourcerer Result"):
                st.write(result.get())
            del st.session_state['sourcerer_task_id']


# --- 5. Main App ---
st.title("🧠 The AI Progress Sentinel")
st.caption("AI-Powered Summaries & Rankings of AI Progress. Continuously Updated.")

if not all_data:
    st.warning("The database is currently empty. Please wait for the scraper to populate it.")
    st.stop()

print(f"DEBUG APP: all_data has {len(all_data)} items")
df = pd.DataFrame(all_data)
print(f"DEBUG APP: DataFrame has {len(df)} rows after conversion")
df['id'] = df['id'].astype(str)
df['published_date'] = pd.to_datetime(df['published_date'], errors='coerce')


# --- Reusable Display Function ---
def process_and_display_feed(input_df: pd.DataFrame, tab_key_prefix: str):
    print(f"DEBUG APP: process_and_display_feed received {len(input_df)} rows")
    page_number_key = f"{tab_key_prefix}_page"
    
    # Filtering Logic
    results_df = input_df
    if semantic_query:
        print(f"DEBUG APP: Semantic query active: {semantic_query}")
        with st.spinner("Performing semantic search..."):
            query_embedding = model.encode(semantic_query).tolist()
            results = progress_collection.query(query_embeddings=[query_embedding], n_results=50)
            relevant_ids = results['ids'][0]
            if not relevant_ids:
                results_df = pd.DataFrame(columns=df.columns)
                print("DEBUG APP: Semantic search returned no relevant IDs.")
            else:
                results_df = df[df['id'].isin(relevant_ids)].copy()
                relevance_scores = {id_str: dist for id_str, dist in zip(results['ids'][0], results['distances'][0])}
                results_df['relevance'] = results_df['id'].map(relevance_scores)
                print(f"DEBUG APP: Semantic search filtered to {len(results_df)} rows.")
    
    if selected_sources:
        print(f"DEBUG APP: Source filter active: {selected_sources}")
        results_df = results_df[results_df['source'].isin(selected_sources)]
        print(f"DEBUG APP: After source filter: {len(results_df)} rows.")
    if search_term:
        print(f"DEBUG APP: Keyword filter active: {search_term}")
        term_lower = search_term.lower()
        results_df = results_df[results_df.apply(
            lambda row: term_lower in str(row['title']).lower() or term_lower in str(row['keywords']).lower(),
            axis=1
        )]
        print(f"DEBUG APP: After keyword filter: {len(results_df)} rows.")
    
    print(f"DEBUG APP: Before sorting, results_df has {len(results_df)} rows.")
    # Sorting Logic
    if sort_key == "Relevance" and 'relevance' in results_df.columns:
        sorted_df = results_df.sort_values('relevance', ascending=True)
        print(f"DEBUG APP: Sorted by Relevance. sorted_df has {len(sorted_df)} rows.")
    elif sort_key == "Importance Score":
        results_df['overall_importance_score'] = pd.to_numeric(results_df['overall_importance_score'], errors='coerce').fillna(0.0)
        sorted_df = results_df.sort_values('overall_importance_score', ascending=False)
        print(f"DEBUG APP: Sorted by Importance Score. sorted_df has {len(sorted_df)} rows.")
    else: # Default to date
        sorted_df = results_df.sort_values('published_date', ascending=False, na_position='last')
        print(f"DEBUG APP: Sorted by Date. sorted_df has {len(sorted_df)} rows.")

    # Pagination Logic
    total_items = len(sorted_df)
    page_size = st.session_state.page_size
    total_pages = math.ceil(total_items / page_size) if page_size > 0 else 1
    if st.session_state.get(page_number_key, 1) > total_pages:
        st.session_state[page_number_key] = 1
    
    start_index = (st.session_state[page_number_key] - 1) * page_size
    end_index = start_index + page_size
    paginated_df = sorted_df.iloc[start_index:end_index]
    print(f"DEBUG APP: Paginated_df has {len(paginated_df)} rows (Page {st.session_state[page_number_key]} of {total_pages}).")

    # Pagination UI
    st.subheader(f"Showing {len(paginated_df)} of {total_items} breakthroughs")
    p_col1, p_col2, p_col3, p_col4 = st.columns([2, 2, 1, 5])
    if p_col1.button("⬅️ Previous", use_container_width=True, disabled=(st.session_state[page_number_key] <= 1), key=f"prev_{tab_key_prefix}"):
        st.session_state[page_number_key] -= 1
        st.rerun()
    if p_col2.button("Next ➡️", use_container_width=True, disabled=(st.session_state[page_number_key] >= total_pages), key=f"next_{tab_key_prefix}"):
        st.session_state[page_number_key] += 1
        st.rerun()
    p_col3.number_input("Page", min_value=1, max_value=total_pages or 1, key=page_number_key, label_visibility="collapsed")
    p_col4.markdown(f"<div style='text-align: right; padding-top: 10px;'>Page {st.session_state[page_number_key]} of {total_pages}</div>", unsafe_allow_html=True)
    st.divider()

    # Display Results
    if paginated_df.empty:
        st.info("No results match your criteria.")
    else:
        for _, item in paginated_df.iterrows():
            card_container = st.container(border=True)
            render_progress_card(item.to_dict(), card_container, lang_code=st.session_state.display_language, key_prefix=f"{tab_key_prefix}_{item['id']}")
            
            # Flagging logic
            if st.session_state.get(f"flagging_item_id_{tab_key_prefix}_{item['id']}") == item['id']:
                with st.form(key=f"form_flag_{tab_key_prefix}_{item['id']}", clear_on_submit=True):
                    st.warning(f"Flagging: {item['title']}")
                    reason = st.selectbox("Reason:", ["Inaccurate Summary", "Incorrect Score", "Other"], key=f"reason_{tab_key_prefix}_{item['id']}")
                    comment = st.text_area("Optional Comment:", key=f"comment_{tab_key_prefix}_{item['id']}")
                    submitted = st.form_submit_button("Submit Flag")
                    if submitted:
                        db = SessionLocal()
                        try:
                            new_flag = CorrectionFlag(item_id=int(item['id']), reason=reason, user_comment=comment)
                            db.add(new_flag)
                            db.commit()
                            st.success("Flag submitted!")
                        finally:
                            db.close()
                        del st.session_state[f"flagging_item_id_{tab_key_prefix}_{item['id']}"]
                        st.rerun()

# --- Tab Definitions ---
tab_titles = ["🔥 All Progress", "❤️ My Feed"]

# Use st.radio to simulate tabs and manage active tab state
selected_tab_title = st.radio("", tab_titles, key="main_tab_selector", horizontal=True)

if selected_tab_title == "🔥 All Progress":
    process_and_display_feed(df, tab_key_prefix="all_progress")

elif selected_tab_title == "👤 My Feed":
    db = SessionLocal()
    followed_terms = [row.term for row in db.query(FollowedTerm.term).all()]
    db.close()

    if not followed_terms:
        st.info("You are not following any terms. Add some in the sidebar to create your personalized feed.")
    else:
        try:
            pattern = '|'.join(map(re.escape, followed_terms))
            my_feed_df = df[df.apply(
                lambda row: bool(
                    re.search(pattern, str(row['title']).lower()) or
                    re.search(pattern, str(row['keywords']).lower())
                ),
                axis=1
            )]
            process_and_display_feed(my_feed_df, tab_key_prefix="my_feed")
        except re.error as e:
            st.error(f"Could not process followed terms due to a regular expression error: {e}")