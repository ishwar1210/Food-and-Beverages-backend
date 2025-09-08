from django.utils.deprecation import MiddlewareMixin
from FB.db_router import set_current_tenant
from django.conf import settings

class TenantMiddleware(MiddlewareMixin):
    """
    Middleware that sets current tenant based on headers
    """
    def process_request(self, request):
        # Get tenant from header (or use vcnew_db as default)
        tenant = request.headers.get('X-Tenant-ID', 'vcnew_db')
        
        # Only set if it's a valid database connection
        if tenant in settings.DATABASES:
            set_current_tenant(tenant)
        else:
            # Log warning that tenant doesn't exist
            print(f"Warning: Requested tenant '{tenant}' doesn't exist in DATABASES")
            # Use default for tenant apps
            set_current_tenant('vcnew_db')
        
        return None
    
    def process_response(self, request, response):
        # Clear tenant context after request completes
        set_current_tenant(None)
        return response