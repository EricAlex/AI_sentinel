# manage_sources.py
from database import SessionLocal, Source

def set_source_status(source_name, is_active: bool):
    db = SessionLocal()
    try:
        source = db.query(Source).filter(Source.name == source_name).first()
        if source:
            source.is_active = is_active
            db.commit()
            print(f"ACTION: Set source '{source_name}' active status to: {is_active}")
        else:
            print(f"WARN: Source '{source_name}' not found in database.")
    finally:
        db.close()

if __name__ == "__main__":
    print("--- Source Management ---")
    # Disable all known broken sources to create a stable baseline
    set_source_status("Google AI Blog", False)
    set_source_status("OpenAI Blog", False)
    set_source_status("DeepMind Blog", False)
    set_source_status("Meta AI Blog", False)
    set_source_status("Hugging Face Blog", False)
    set_source_status("NVIDIA AI Blog", False)
    set_source_status("MIT Technology Review (AI)", False)
    set_source_status("The Gradient", False)
    
    print("\n--- Current Status ---")
    db = SessionLocal()
    for s in db.query(Source).all():
        print(f"{'[ACTIVE]' if s.is_active else '[INACTIVE]'} {s.name}")
    db.close()