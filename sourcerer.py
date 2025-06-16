# sourcerer.py

import os
import json
import google.generativeai as genai
from googlesearch import search
from celery_app import celery
from database import SessionLocal, Source
from dotenv import load_dotenv

# --- Configuration ---
load_dotenv()
API_KEY = os.getenv("GOOGLE_API_KEY")
if not API_KEY:
    # This service is non-essential, so we can disable it if the key is missing
    print("SOURCERER: WARNING - GOOGLE_API_KEY not found. Sourcerer tasks will be disabled.")
    genai_model = None
else:
    genai.configure(api_key=API_KEY)
    genai_model = genai.GenerativeModel(
        model_name="gemini-1.5-pro-latest",
        generation_config={"response_mime_type": "application/json"}
    )

# --- Prompt for Source Validation ---
SOURCERER_PROMPT = """
You are an AI research analyst responsible for curating our data sources.
Evaluate the given URL and determine if it points to a high-quality, English-language blog or news site that regularly publishes technical content about AI, machine learning, or data science breakthroughs.

**Do NOT approve:**
- Corporate product marketing pages.
- General tech news sites that only occasionally mention AI.
- Individual researcher homepages or university department pages.
- Social media profiles or forums.

**Strongly approve:**
- Dedicated research blogs from major AI labs (e.g., DeepMind, OpenAI).
- High-quality, independent blogs focused on explaining AI research.
- The AI-specific section of a major tech publication (e.g., MIT Technology Review's AI section).

**URL to Analyze:** "{url}"

**Output Schema (JSON):**
{{
  "is_high_quality_source": boolean,
  "reasoning": "A concise, one-sentence justification for your decision.",
  "source_name": "The proper name of the publication (e.g., 'The Gradient', 'Google AI Blog').",
  "source_type": "One of ['blog', 'news', 'other']"
}}
"""

@celery.task(name="sourcerer.find_new_sources")
def find_new_sources():
    """
    A Celery task that searches Google for new AI blogs and validates them with Gemini.
    """
    if not genai_model:
        return "Sourcerer task skipped: Gemini API key not configured."

    print("SOURCERER: Starting cycle to find new AI sources.")
    
    # Use a variety of search queries to get diverse results
    queries = [
        "top AI research blogs 2024",
        "best machine learning blogs for researchers",
        "new large language model announcements blog"
    ]
    
    potential_urls = set()
    for query in queries:
        try:
            for url in search(query, num_results=10, sleep_interval=2):
                potential_urls.add(url)
        except Exception as e:
            print(f"SOURCERER: WARN - Google search failed for query '{query}': {e}")
            continue

    db = SessionLocal()
    try:
        # Get all existing URLs to avoid re-processing
        existing_urls = {s.url for s in db.query(Source.url).all()}
    finally:
        db.close()
    
    new_sources_added = 0
    for url in potential_urls:
        if url in existing_urls:
            continue
        
        print(f"SOURCERER: Evaluating potential new source: {url}")
        try:
            response = genai_model.generate_content(SOURCERER_PROMPT.format(url=url))
            result = json.loads(response.text.strip())
            
            if result.get("is_high_quality_source"):
                print(f"SOURCERER: VALIDATED new source '{result.get('source_name')}' at {url}")
                new_source = Source(
                    name=result.get('source_name'),
                    url=url,
                    source_type=result.get('source_type'),
                    is_active=True # Add new sources as active by default
                )
                db = SessionLocal()
                try:
                    db.add(new_source)
                    db.commit()
                    new_sources_added += 1
                except IntegrityError:
                    db.rollback() # Handle rare race condition if URL was added in another process
                finally:
                    db.close()

        except Exception as e:
            print(f"SOURCERER: Could not process URL {url}. Reason: {e}")
            
    return f"Sourcerer cycle complete. Added {new_sources_added} new sources to the database."