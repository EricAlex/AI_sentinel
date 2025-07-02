# ingest.py

import arxiv
from database import SessionLocal, Source, add_progress_item, get_all_sources # Import get_all_sources
# Import our new parsers map and the healer task
from parsers import get_parser_function # Import the new function
from redis import Redis
import os

from sourcerer import attempt_heal_parser

redis_client = Redis.from_url(os.getenv('CELERY_BROKER_URL'), decode_responses=True)

def fetch_from_arxiv(tenant_id: str, max_results=100):
    """Fetches papers from arXiv using its dedicated Python library."""
    print(f"INGEST: Fetching from arXiv source for tenant {tenant_id}...")
    query = "cat:cs.LG OR cat:cs.AI OR cat:cs.CL OR cat:cs.CV OR cat:cs.RO"
    papers = []
    try:
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.SubmittedDate
        )
        for result in search.results():
            papers.append({
                "entry_id": result.entry_id, "title": result.title, "abstract": result.summary.replace('\n', ' '),
                "authors": [author.name for author in result.authors], "published_date": result.published,
                "url": result.pdf_url, "source": "arXiv"
            })
        print(f"INGEST: Found {len(papers)} new papers from arXiv for tenant {tenant_id}.")
        return papers
    except Exception as e:
        print(f"INGEST: ERROR fetching from arXiv for tenant {tenant_id}: {e}")
        return []

def fetch_from_web_sources(tenant_id: str):
    """
    Fetches from all active web sources for a given tenant and triggers the AI healer
    for sources that fail.
    """
    # Get all sources that are active and have a parser defined in our map for this tenant
    sources_to_scrape = get_all_sources(tenant_id) # Use the tenant-aware get_all_sources
    # Filter out sources that don't have a default parser, as custom parsers are loaded dynamically
    sources_to_scrape = [s for s in sources_to_scrape if s.is_active]
        
    all_items = []
    print(f"INGEST: Found {len(sources_to_scrape)} active web sources to scrape for tenant {tenant_id}.")
    for source in sources_to_scrape:
        print(f"--- Scraping source: {source.name} for tenant {tenant_id} ---")
        # Get the parser function dynamically
        parser_func = get_parser_function(tenant_id, source.id, source.source_type)
        if parser_func:
            # --- REDIS FAILURE TRACKING LOGIC ---
            failure_key = f"parser_failure:{tenant_id}:{source.id}" # Make failure key tenant-aware
            
            try:
                new_items = parser_func(source.url, source.name, 10)
                if not new_items:
                    raise ValueError("Parser returned an empty list.")
                
                print(f"-> Found {len(new_items)} items from {source.name} for tenant {tenant_id}")
                all_items.extend(new_items)
                
                # On success, delete the failure key from Redis
                redis_client.delete(failure_key)

            except Exception as e:
                print(f"INGEST: PARSE FAILED for source '{source.name}' (tenant {tenant_id}): {e}.")
                
                # On failure, increment the failure count in Redis
                # INCR is atomic, so it's safe for multiple workers
                failure_count = redis_client.incr(failure_key)
                # Set an expiration so old failures don't count forever (e.g., 6 hours)
                redis_client.expire(failure_key, 6 * 3600)
                
                # Trigger heal after 2 consecutive failures
                if failure_count >= 2:
                    print(f"INGEST: Source '{source.name}' has failed {failure_count} times for tenant {tenant_id}. Triggering AI Healer.")
                    attempt_heal_parser.delay(source.id, tenant_id) # Pass tenant_id to healer
                    # After triggering, delete the key to reset the process and prevent spam
                    redis_client.delete(failure_key)
                continue
        else:
            print(f"INGEST: No parser found for source type '{source.source_type}' for tenant {tenant_id} or globally. Skipping.")
    return all_items