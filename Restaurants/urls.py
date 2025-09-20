from django.urls import path, include
from rest_framework.routers import DefaultRouter
from django.conf import settings
from django.conf.urls.static import static
from .views import (
    # Core Restaurant ViewSets
    RestaurantViewSet,  BlockedDayViewSet,
    TableBookingViewSet, OrderConfigureViewSet, RestaurantScheduleViewSet, RestaurantScheduleBulkView,

    # Menu Management ViewSets
    MasterCuisineViewSet, MasterItemViewSet, CuisineViewSet, CategoryViewSet,  ItemViewSet,

    # Customer & Order ViewSets
    CustomerViewSet, OrderViewSet, OrderItemViewSet,

    # Inventory Management ViewSets
    SupplierViewSet, WarehouseViewSet, InventoryItemViewSet, InventoryMovementViewSet,

    # Ingredient Management ViewSets
    IngredientViewSet, QtyIngredientViewSet,

    # Media Management ViewSets
    RestoCoverImageViewSet, RestoMenuImageViewSet, RestoGalleryImageViewSet,
    RestoOtherFileViewSet,  # Add this
    
    # Utility Views
    RegisterDBByClientAPIView, RegisterTenantDatabaseView, RestaurantWeeklyScheduleView,

    # New ViewSets
    TableBookingFloorViewSet, TableViewSet, TableBookingLogViewSet, KOTViewSet, BillingViewSet,
)

# Router registration
router = DefaultRouter()

# Core Restaurant endpoints
router.register(r'restaurants', RestaurantViewSet, basename='restaurant')
router.register(r"restaurant-schedules", RestaurantScheduleViewSet, basename="restaurant-schedule")
router.register(r'blocked-days', BlockedDayViewSet, basename='blocked-day')
router.register(r'table-bookings', TableBookingViewSet, basename='table-booking')
router.register(r'order-configs', OrderConfigureViewSet, basename='order-configure')

# Menu Management endpoints
router.register(r'master-cuisines', MasterCuisineViewSet, basename="mastercuisine")
router.register(r'master-items', MasterItemViewSet, basename="masteritem")
router.register(r'cuisines', CuisineViewSet, basename='cuisine')
router.register(r'categories', CategoryViewSet, basename='category')
router.register(r'items', ItemViewSet, basename='item')

# Customer & Order endpoints
router.register(r'customers', CustomerViewSet, basename='customer')
router.register(r'order-items', OrderItemViewSet, basename='order-item')
router.register(r'orders', OrderViewSet, basename='order')

# Inventory Management endpoints
router.register(r'suppliers', SupplierViewSet, basename='supplier')
router.register(r'warehouses', WarehouseViewSet, basename='warehouse')
router.register(r'inventory-items', InventoryItemViewSet, basename='inventory-item')
router.register(r'inventory-movements', InventoryMovementViewSet, basename='inventory-movement')

# Ingredient Management endpoints
router.register(r'ingredients', IngredientViewSet, basename='ingredient')
router.register(r'qty-ingredients', QtyIngredientViewSet, basename='qty-ingredient')

# Media Management endpoints
router.register(r'cover-images', RestoCoverImageViewSet, basename='cover-image')
router.register(r'menu-images', RestoMenuImageViewSet, basename='menu-image')
router.register(r'gallery-images', RestoGalleryImageViewSet, basename='gallery-image')
router.register(r'other-files', RestoOtherFileViewSet, basename='other-file')  

# New endpoints
router.register(r'tablebookingfloors', TableBookingFloorViewSet, basename="tablebookingfloor")
router.register(r'tables', TableViewSet, basename="table")
router.register(r'tablebookinglogs', TableBookingLogViewSet, basename="tablebookinglog")
router.register(r'kots', KOTViewSet, basename="kot")
router.register(r'billings', BillingViewSet, basename="billing")

urlpatterns = [
    # Tenant database registration
    path('register-db/', RegisterDBByClientAPIView.as_view(), name='register-db-client'),
    path('register-tenant/', RegisterTenantDatabaseView.as_view(), name='register-tenant'),
    
    # Bulk create/update (multi-days)
    path('restaurant-schedules/bulk/', RestaurantScheduleBulkView.as_view(), name='restaurant-schedule-bulk'),

    # Always return full weekly schedule (7 rows)
    path('restaurants/<int:restaurant_id>/weekly-schedule/', RestaurantWeeklyScheduleView.as_view(), name='restaurant-weekly-schedule'),

    # Include all router URLs
    path('', include(router.urls)),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)