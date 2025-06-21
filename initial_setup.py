# initial_setup.py

import time
from sqlalchemy.exc import OperationalError, IntegrityError
from database import create_all_tables, SessionLocal, Source
from health import get_db_status

def add_initial_sources(db_session):
    """
    Adds a curated list of starting sources to the database.
    Checks for existence before adding to be idempotent.
    """
    initial_sources = [
        # --- Pre-print Servers ---
        {'name': 'arXiv (AI/ML/CV/CL)', 'url': 'https://arxiv.org/corr/home', 'source_type': 'arxiv', 'is_active': True},
        
        # --- Top-Tier Industry Blogs ---
        {'name': 'Google AI Blog', 'url': 'https://ai.google/research/', 'source_type': 'google_blog', 'is_active': True},
        {'name': 'OpenAI Blog', 'url': 'https://openai.com/news/research/', 'source_type': 'openai_blog', 'is_active': True},
        {'name': 'DeepMind Blog', 'url': 'https://deepmind.google/discover/blog/', 'source_type': 'deepmind_blog', 'is_active': True},
        {'name': 'Meta AI Blog', 'url': 'https://ai.meta.com/blog/', 'source_type': 'meta_blog', 'is_active': True},
        {'name': 'Hugging Face Blog', 'url': 'https://huggingface.co/blog', 'source_type': 'huggingface_blog', 'is_active': True},
        {'name': 'NVIDIA AI Blog', 'url': 'https://blogs.nvidia.com/blog/category/generative-ai/', 'source_type': 'nvidia_blog', 'is_active': True},
        {'name': 'Microsoft Research AI', 'url': 'https://www.microsoft.com/en-us/research/blog/category/artificial-intelligence/', 'source_type': 'microsoft_blog', 'is_active': True},

        # --- High-Quality Curated News & Publications ---
        {'name': 'MIT Technology Review (AI)', 'url': 'https://www.technologyreview.com/topic/artificial-intelligence/', 'source_type': 'techreview_ai', 'is_active': True},
        {'name': 'The Gradient', 'url': 'https://thegradient.pub/', 'source_type': 'gradient_pub', 'is_active': True},
    ]

    print("SETUP: Populating initial sources with comprehensive list...")
    sources_added = 0
    for src in initial_sources:
        try:
            # Check if a source with the same name or URL already exists
            exists = db_session.query(Source).filter(
                (Source.name == src['name']) | (Source.url == src['url'])
            ).first()
            
            if not exists:
                new_source = Source(**src)
                db_session.add(new_source)
                db_session.commit()
                print(f"  -> Added source: {src['name']}")
                sources_added += 1
            else:
                print(f"  -> Skipping existing source: {src['name']}")
        except IntegrityError:
            # Handle rare race conditions if run in parallel
            db_session.rollback()
            print(f"  -> IntegrityError while adding {src['name']}, likely already exists.")
        except Exception as e:
            db_session.rollback()
            print(f"  -> ERROR adding source {src['name']}: {e}")
            
    print(f"SETUP: Finished populating sources. Added {sources_added} new sources.")


if __name__ == "__main__":
    print("--- Synthesis Engine Initial Setup ---")
    
    # Wait for the database service to be ready
    max_retries = 10
    retry_delay = 5
    for i in range(max_retries):
        status = get_db_status()
        print(f"Attempt {i+1}/{max_retries}: Checking database status... [{status}]")
        if status == "Online":
            print("SETUP: Database is online.")
            break
        elif i == max_retries - 1:
            print("SETUP: FATAL - Database did not come online after multiple retries. Aborting.")
            exit(1)
        time.sleep(retry_delay)

    # Step 1: Create all database tables defined in database.py
    try:
        create_all_tables()
    except Exception as e:
        print(f"SETUP: FATAL - An error occurred during table creation: {e}")
        exit(1)

    # Step 2: Populate the 'sources' table with an initial list
    db = SessionLocal()
    try:
        add_initial_sources(db)
    finally:
        db.close()
    
    print("--- Initial Setup Complete ---")
    print("The system is now ready. You can start all services via 'docker-compose up -d'.")