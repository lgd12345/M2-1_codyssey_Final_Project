from app.company_admin import customer_install
from app.company_admin.install_routes import build_router

router = build_router(customer_install, 'customer-installation', 'customer-installation.html')
