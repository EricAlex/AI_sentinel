import sys
import os
from database import create_tenant, create_user, get_tenant_by_name, SHARED_TENANT_ID

def create_system_admin(email, password):
    db = SessionLocal()
    try:
        tenant = get_tenant_by_name("system_shared_sources")
        if not tenant:
            tenant = create_tenant(name="System Shared Sources", description="Tenant for globally shared content and configurations.", id="system_shared_sources")
            if not tenant:
                print("Failed to create system_shared_sources tenant.")
                return

        user = create_user(tenant_id=tenant.id, username=email, password=password, is_admin=True)
        if user:
            print(f"Successfully created system administrator: {email}")
        else:
            print(f"Failed to create system administrator: {email}. User might already exist.")
    finally:
        db.close()

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python create_system_admin.py <email> <password>")
        sys.exit(1)

    email = sys.argv[1]
    password = sys.argv[2]

    create_system_admin(email, password)
