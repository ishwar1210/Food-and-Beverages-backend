from django.urls import path, include
from rest_framework.routers import DefaultRouter
from django.conf import settings
from django.conf.urls.static import static
from .views import (
    # Core Restaurant ViewSets
    RestaurantViewSet, RestaurantScheduleViewSet, BlockedDayViewSet,
    TableBookingViewSet, OrderConfigureViewSet,
    
    # Menu Management ViewSets
    CuisineViewSet, CategoryViewSet, ItemViewSet,
    
    # Customer & Order ViewSets
    CustomerViewSet, OrderViewSet,
    
    # Inventory Management ViewSets
    SupplierViewSet, WarehouseViewSet, InventoryItemViewSet, InventoryMovementViewSet,
    
    # Ingredient Management ViewSets
    IngredientViewSet, ItemIngredientViewSet,
    
    # Media Management ViewSets
    RestoCoverImageViewSet, RestoMenuImageViewSet, RestoGalleryImageViewSet,
    RestoOtherFileViewSet,  # Add this
    
    # Utility Views
    RegisterDBByClientAPIView, RegisterTenantDatabaseView
)

# Router registration
router = DefaultRouter()

# Core Restaurant endpoints
router.register(r'restaurants', RestaurantViewSet, basename='restaurant')
router.register(r'schedules', RestaurantScheduleViewSet, basename='restaurant-schedule')
router.register(r'blocked-days', BlockedDayViewSet, basename='blocked-day')
router.register(r'table-bookings', TableBookingViewSet, basename='table-booking')
router.register(r'order-configs', OrderConfigureViewSet, basename='order-configure')

# Menu Management endpoints
router.register(r'cuisines', CuisineViewSet, basename='cuisine')
router.register(r'categories', CategoryViewSet, basename='category')
router.register(r'items', ItemViewSet, basename='item')

# Customer & Order endpoints
router.register(r'customers', CustomerViewSet, basename='customer')
router.register(r'orders', OrderViewSet, basename='order')

# Inventory Management endpoints
router.register(r'suppliers', SupplierViewSet, basename='supplier')
router.register(r'warehouses', WarehouseViewSet, basename='warehouse')
router.register(r'inventory-items', InventoryItemViewSet, basename='inventory-item')
router.register(r'inventory-movements', InventoryMovementViewSet, basename='inventory-movement')

# Ingredient Management endpoints
router.register(r'ingredients', IngredientViewSet, basename='ingredient')
router.register(r'item-ingredients', ItemIngredientViewSet, basename='item-ingredient')

# Media Management endpoints
router.register(r'cover-images', RestoCoverImageViewSet, basename='cover-image')
router.register(r'menu-images', RestoMenuImageViewSet, basename='menu-image')
router.register(r'gallery-images', RestoGalleryImageViewSet, basename='gallery-image')
router.register(r'other-files', RestoOtherFileViewSet, basename='other-file')  

urlpatterns = [
    # Tenant database registration
    path('register-db/', RegisterDBByClientAPIView.as_view(), name='register-db-client'),
    path('register-tenant/', RegisterTenantDatabaseView.as_view(), name='register-tenant'),
    
    # Include all router URLs
    path('', include(router.urls)),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)