# tasks.py

# --- ChromaDB System Hack ---
# This block must be at the very top of the file
# to ensure the correct sqlite3 version is loaded
# before chromadb is imported.
__import__('pysqlite3')
import sys
sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')
# --- End of Hack ---

import os
import time
from celery_app import celery
# --- Update the import ---
from ingest import fetch_from_arxiv, fetch_from_web_sources
from services import analyze_rank_and_translate
from database import SessionLocal, add_progress_item, ProgressItem, get_all_sources, Tenant # Import Tenant model
from sentence_transformers import SentenceTransformer
import chromadb

# --- Initialize models and clients (no changes here) ---
LOCAL_MODEL_PATH = '/app/models/all-MiniLM-L6-v2'

print("TASKS: Loading Sentence Transformer model from local path...")
try:
    embedding_model = SentenceTransformer(LOCAL_MODEL_PATH, device='cpu')
    print("TASKS: Sentence Transformer model loaded successfully.")
except Exception as e:
    print(f"TASKS: FATAL ERROR loading Sentence Transformer model: {e}")
    embedding_model = None

CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
chroma_client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
progress_collection = chroma_client.get_or_create_collection(name="ai_progress", metadata={"hnsw:space": "cosine"})
print("TASKS: Connected to ChromaDB successfully.")

# --- Celery Tasks ---

@celery.task(name="tasks.run_scraper_cycle")
def run_scraper_cycle(tenant_id: str):
    """A single task that orchestrates fetching from all active sources for a given tenant."""
    print(f"TASK: Starting full scraper cycle for tenant: {tenant_id}.")
    all_new_items = []
    
    # Fetch from arXiv using its dedicated function
    all_new_items.extend(fetch_from_arxiv(tenant_id))
    
    # Fetch from all other web sources using the new dispatcher
    all_new_items.extend(fetch_from_web_sources(tenant_id))
    
    if not all_new_items:
        print(f"TASK: No new items found for tenant {tenant_id} in this cycle.")
        return f"Scraper cycle complete for tenant {tenant_id}. No new items found from any source."
    
    # Remove duplicates based on URL before dispatching
    unique_items = {item['url']: item for item in all_new_items}.values()
    
    print(f"TASK: Found a total of {len(unique_items)} unique items for tenant {tenant_id}. Dispatching analysis tasks...")
    for item in unique_items:
        # Dispatch a separate task for each item for parallel processing
        process_item.delay(item, tenant_id)
        
    return f"Scraper cycle complete for tenant {tenant_id}. Dispatched {len(unique_items)} tasks."


@celery.task(name="tasks.process_item", bind=True, max_retries=3, default_retry_delay=60)
def process_item(self, item_data: dict, tenant_id: str):
    """
    The main worker task: takes raw item data, analyzes it, creates embeddings, and stores everything.
    This task is resilient to missing keys from the AI and API failures.
    """
    entry_id = item_data['entry_id']
    title = item_data['title']
    print(f"TASK: Worker processing item: {title} for tenant {tenant_id}")

    # 1. Check if item already exists in PostgreSQL for this tenant
    db = SessionLocal()
    try:
        exists = db.query(ProgressItem).filter(
            (ProgressItem.entry_id == entry_id) & (ProgressItem.tenant_id == tenant_id)
        ).first()
        if exists:
            print(f"TASK: Skipping '{title}' as it already exists in DB for tenant {tenant_id}.")
            return f"Skipped (already exists): {entry_id} for tenant {tenant_id}"
    finally:
        db.close()

    # 2. Perform AI analysis (now using the more robust service layer)
    try:
        # Call the new, all-in-one function, passing tenant_id
        analysis_data = analyze_rank_and_translate(title, item_data['abstract'], tenant_id)
        if not analysis_data:
            raise ValueError("Unified analysis from Gemini returned None or was invalid.")
    except Exception as e:
        print(f"TASK: ERROR during Gemini analysis for '{title}' (tenant {tenant_id}): {e}. Retrying...")
        raise self.retry(exc=e)

    # 3. Validate the analysis data before proceeding
    ranking_data = analysis_data.get('ranking', {})
    scores = ranking_data.get('scores', {})
    analysis_content = analysis_data.get('en', {}) # Main content is in English

    # Check 1: Ensure essential text fields are not empty
    required_fields = ['what_is_new', 'why_it_matters', 'how_it_works']
    missing_fields = [field for field in required_fields if not analysis_content.get(field)]
    if missing_fields:
        print(f"TASK: FAILURE for '{title}'. Missing required analysis fields: {missing_fields}. Item will not be saved.")
        return f"Failed (Missing content): {entry_id} for tenant {tenant_id}"

    # Check 2: Ensure the overall justification is present
    if not ranking_data.get('overall_importance_justification'):
        print(f"TASK: FAILURE for '{title}'. Missing overall importance justification. Item will not be saved.")
        return f"Failed (Missing justification): {entry_id} for tenant {tenant_id}"

    # Check 3: Ensure scores are not all zero and calculate the average
    score_values = []
    score_keys = ['breakthrough_novelty', 'human_impact', 'field_influence', 'technical_maturity']
    for key in score_keys:
        try:
            score_value = float(scores.get(key, {}).get('score', 0))
            score_values.append(score_value)
        except (ValueError, TypeError):
            print(f"TASK: WARNING for '{title}'. Invalid score format for {key}. Defaulting to 0.")
            score_values.append(0)

    if sum(score_values) == 0:
        print(f"TASK: FAILURE for '{title}'. All scores are zero or invalid. Item will not be saved.")
        return f"Failed (All scores zero): {entry_id} for tenant {tenant_id}"

    # 4. Calculate and inject the overall score
    average_score = sum(score_values) / len(score_values)
    analysis_data['ranking']['overall_importance_score'] = f"{average_score:.2f}"

    # 5. Create semantic embedding (now including keywords for better search)
    title_en = analysis_content.get('title', 'No Title Provided')
    what_is_new_en = analysis_content.get('what_is_new', 'No summary available.')
    why_it_matters_en = analysis_content.get('why_it_matters', 'No impact statement available.')
    keywords_en = ", ".join(analysis_data.get('keywords', [])) # Join keywords into a string

    text_to_embed = (
        f"Title: {title_en}\n"
        f"Keywords: {keywords_en}\n\n" # Add the keywords here
        f"Innovation: {what_is_new_en}\n\n"
        f"Impact: {why_it_matters_en}"
    )
    embedding = embedding_model.encode(text_to_embed).tolist()

    # 6. Store results in PostgreSQL
    db_item_data = {**item_data, "analysis_data": analysis_data}
    db_item = add_progress_item(db_item_data, tenant_id) # Pass tenant_id here
    if not db_item:
        print(f"TASK: ERROR failed to save '{title}' to PostgreSQL for tenant {tenant_id}.")
        return f"Failed (Postgres save error): {entry_id} for tenant {tenant_id}"

    # 7. Store embedding in ChromaDB
    try:
        # Consider adding tenant_id to metadata for future tenant-aware ChromaDB queries
        progress_collection.add(
            embeddings=[embedding],
            documents=[text_to_embed],
            metadatas=[{"source": item_data['source'], "title": title, "tenant_id": tenant_id}],
            ids=[str(db_item.id)]
        )
    except Exception as e:
        print(f"TASK: ERROR failed to save embedding for '{title}' to ChromaDB (tenant {tenant_id}): {e}")

    print(f"TASK: Successfully processed and stored '{title}' for tenant {tenant_id}.")
    return f"Success: {entry_id} for tenant {tenant_id}"

@celery.task(name="tasks.trigger_all_tenant_scrapers")
def trigger_all_tenant_scrapers():
    """
    Fetches all active tenants and dispatches a scraper cycle for each.
    """
    print("TASK: Triggering scraper cycles for all tenants.")
    db = SessionLocal()
    try:
        tenants = db.query(Tenant).all() # Fetch all tenants
        for tenant in tenants:
            print(f"TASK: Dispatching scraper cycle for tenant: {tenant.name} ({tenant.id})")
            run_scraper_cycle.delay(tenant.id)
        return f"Dispatched scraper cycles for {len(tenants)} tenants."
    except Exception as e:
        print(f"TASK: Error triggering tenant scrapers: {e}")
        return f"Error triggering tenant scrapers: {e}"
    finally:
        db.close()

# Note: The send_weekly_digest task is omitted here for clarity but would
# be part of this file in the full application.
