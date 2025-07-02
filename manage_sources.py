# manage_sources.py
from database import SessionLocal, Source, add_new_source, update_source, delete_source
from sourcerer import SHARED_TENANT_ID # Import the shared tenant ID

def set_source_status(source_name: str, is_active: bool, tenant_id: str, is_shared: bool = False):
    db = SessionLocal()
    try:
        # Find the source, considering both tenant-specific and shared sources
        source = db.query(Source).filter(
            (Source.name == source_name) & 
            ((Source.tenant_id == tenant_id) | (Source.is_shared == True))
        ).first()
        
        if source:
            source.is_active = is_active
            db.commit()
            print(f"ACTION: Set source '{source_name}' active status to: {is_active} for tenant {tenant_id}.")
        else:
            print(f"WARN: Source '{source_name}' not found for tenant {tenant_id} or as shared.")
    finally:
        db.close()

if __name__ == "__main__":
    print("--- Source Management (System-level) ---")
    print("Note: This script operates on the SHARED_TENANT_ID for system-wide sources.")

    # Example: Add a new shared source
    # add_new_source(name="Example Shared Blog", url="https://example.com/blog", source_type="blog", tenant_id=SHARED_TENANT_ID, is_shared=True)

    # Disable all known broken sources to create a stable baseline
    # These operations will now apply to sources associated with SHARED_TENANT_ID
    set_source_status("Google AI Blog", False, SHARED_TENANT_ID)
    set_source_status("OpenAI Blog", False, SHARED_TENANT_ID)
    set_source_status("DeepMind Blog", False, SHARED_TENANT_ID)
    set_source_status("Meta AI Blog", False, SHARED_TENANT_ID)
    set_source_status("Hugging Face Blog", False, SHARED_TENANT_ID)
    set_source_status("NVIDIA AI Blog", False, SHARED_TENANT_ID)
    set_source_status("MIT Technology Review (AI)", False, SHARED_TENANT_ID)
    set_source_status("The Gradient", False, SHARED_TENANT_ID)
    
    print("\n--- Current Status (Shared Sources) ---")
    db = SessionLocal()
    try:
        # Only show sources for the shared tenant
        for s in db.query(Source).filter(Source.tenant_id == SHARED_TENANT_ID).all():
            print(f"{'[ACTIVE]' if s.is_active else '[INACTIVE]'} {s.name}")
    finally:
        db.close()