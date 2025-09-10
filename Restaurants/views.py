from __future__ import annotations
import json
import logging
from django.db.models import Q, Count, Sum, Min, F  # Add F here

import os
import traceback
from io import StringIO
from datetime import timedelta

from django.conf import settings
from django.core.management import call_command
from django.db import connections, transaction, IntegrityError, models  # Add models here
from django.db.models import Q, Count, Sum
from django.utils import timezone
from django.core.exceptions import ValidationError as DjangoValidationError

from rest_framework import viewsets, status, filters, exceptions, generics, permissions
from rest_framework.decorators import action
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.pagination import PageNumberPagination

from FB.db_router import set_current_tenant, get_current_tenant

from .utils import register_tenant_database, ensure_alias_for_client
from .models import (
    Restaurant, RestaurantSchedule, Blocked_Day, TableBooking, OrderConfigure,
    Cuisine, Category, Item, Customer, RestoCoverImage, RestoMenuImage,
    RestoGalleryImage, RestoOtherFile, ItemType, Ingredient, ItemIngredient,
    Supplier, Warehouse, InventoryItem, InventoryMovement, InventoryAudit, Order
)
from .serializers import (
    RestaurantSerializer, RestaurantScheduleSerializer, BlockedDaySerializer,
    TableBookingSerializer, OrderConfigureSerializer, CuisineSerializer, 
    CategorySerializer, ItemSerializer, CustomerSerializer, RestoCoverImageSerializer,
    RestoMenuImageSerializer, RestoGalleryImageSerializer, RestoOtherFileSerializer,  # Add this
    IngredientSerializer, ItemIngredientSerializer, SupplierSerializer, WarehouseSerializer,
    InventoryItemSerializer, InventoryMovementSerializer, OrderSerializer,
    RestaurantListSerializer, ItemListSerializer
)

logger = logging.getLogger("restaurant.api")

# -------------------------------------------------------------------
# Tenant helpers
# -------------------------------------------------------------------
def _get_tenant_from_request(request):
    return getattr(request.user, "tenant", None) or getattr(request, "tenant_info", None)

def _ensure_alias_ready(tenant: dict) -> str:
    if not tenant or "alias" not in tenant:
        raise exceptions.AuthenticationFailed("Tenant alias missing in token.")
    alias = tenant["alias"]

    if alias not in settings.DATABASES:
        if tenant.get("client_username"):
            register_tenant_database(client_username=tenant["client_username"])
        elif tenant.get("client_id"):
            register_tenant_database(client_id=int(tenant["client_id"]))
        elif alias.startswith("client_"):
            register_tenant_database(client_id=int(alias.split("_", 1)[1]))
        else:
            raise exceptions.APIException("Unable to resolve tenant DB.")
    return alias

class RouterTenantContextMixin(APIView):
    """
    Ensure DB router knows the tenant BEFORE any serializer/query runs.
    """
    def initial(self, request, *args, **kwargs):
        alias = _ensure_alias_ready(_get_tenant_from_request(request))
        set_current_tenant(alias)
        return super().initial(request, *args, **kwargs)

    def finalize_response(self, request, response, *args, **kwargs):
        try:
            return super().finalize_response(request, response, *args, **kwargs)
        finally:
            set_current_tenant(None)

class TenantSerializerContextMixin:
    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        alias = _ensure_alias_ready(_get_tenant_from_request(self.request))
        ctx["alias"] = alias
        ctx["request"] = self.request
        return ctx

class _TenantDBMixin:
    def _alias(self) -> str:
        return _ensure_alias_ready(_get_tenant_from_request(self.request))

# -------------------------------------------------------------------
# Register/Prepare DB for a client
# -------------------------------------------------------------------

class RegisterDBByClientAPIView(APIView):
    authentication_classes = []
    permission_classes = []
    parser_classes = [JSONParser]

    def post(self, request):
        client_id = (request.data or {}).get("client_id")
        client_username = (request.data or {}).get("client_username")

        if not client_id and not client_username:
            return Response({"detail": "Provide client_id or client_username."}, status=400)

        try:
            alias = ensure_alias_for_client(
                client_id=int(client_id) if str(client_id).isdigit() else None,
                client_username=client_username if not client_id else None,
            )

            if settings.DEBUG or str(os.getenv("ASSET_AUTO_MIGRATE", "0")) == "1":
                out = StringIO()
                call_command("migrate", "Restaurants", database=alias, interactive=False, verbosity=1, stdout=out)
                logger.info("Migrated app 'Restaurants' on %s\n%s", alias, out.getvalue())

            try:
                connections[alias].close()
            except Exception:
                pass

            return Response({"detail": "Alias ready", "alias": alias}, status=201)

        except Exception as e:
            logger.exception("RegisterDBByClient failed")
            return Response({"detail": str(e)}, status=400)

class RegisterTenantDatabaseView(APIView):
    permission_classes = [permissions.IsAdminUser]
    
    def post(self, request):
        tenant_id = request.data.get('tenant_id')
        db_config = {
            'NAME': request.data.get('db_name'),
            'USER': request.data.get('db_user'),
            'PASSWORD': request.data.get('db_password'),
            'HOST': request.data.get('db_host', 'localhost'),
            'PORT': request.data.get('db_port', 5432),
        }
        
        if not tenant_id or not all([db_config['NAME'], db_config['USER'], db_config['PASSWORD']]):
            return Response(
                {"error": "Missing required fields"},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        success = register_tenant_database(tenant_id, db_config)
        
        if success:
            return Response(
                {"message": f"Tenant database '{tenant_id}' registered successfully"},
                status=status.HTTP_201_CREATED
            )
        else:
            return Response(
                {"error": "Failed to register tenant database"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

# -------------------------------------------------------------------
# Core Restaurant ViewSets
# -------------------------------------------------------------------

class RestaurantViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = RestaurantSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['pure_veg', 'serves_alcohol', 'wheelchair_accessible', 'cash_on_delivery']
    search_fields = ['restaurant_name', 'address', 'number']
    ordering_fields = ['restaurant_name', 'cost_for_two', 'id']  # Remove 'created_at'
    ordering = ['-id']  # Order by id instead of created_at
    
    queryset = Restaurant.objects.none()

    def get_queryset(self):
        alias = self._alias()
        return Restaurant.objects.using(alias).all()

    def get_serializer_class(self):
        if self.action == 'list':
            return RestaurantListSerializer
        return RestaurantSerializer

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic(using=alias):
            obj = Restaurant(**s.validated_data)
            obj.full_clean(validate_unique=False)
            obj.save(using=alias)
        s.instance = obj
        return Response(s.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'])
    def active(self, request):
        """Get restaurants (no active field exists)"""
        alias = self._alias()
        restaurants = Restaurant.objects.using(alias).all()  # Remove status filter
        serializer = self.get_serializer(restaurants, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def dashboard_stats(self, request):
        alias = self._alias()
        try:
            total_restaurants = Restaurant.objects.using(alias).count()
            total_orders = Order.objects.using(alias).count()
            pending_orders = Order.objects.using(alias).filter(Paid=False).count()
            
            return Response({
                'total_restaurants': total_restaurants,
                'total_orders': total_orders,
                'pending_orders': pending_orders,
                'generated_at': timezone.now().isoformat(),
            })
        except Exception:
            logger.exception("dashboard_stats failed")
            return Response({'error': 'Failed to fetch dashboard statistics'},
                          status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    def add_cuisines(self, request, pk=None):
        """Add cuisines to a restaurant"""
        restaurant = self.get_object()
        cuisine_ids = request.data.get('cuisine_ids', [])
        
        try:
            cuisines = Cuisine.objects.filter(id__in=cuisine_ids)
            restaurant.cuisines.add(*cuisines)
            return Response({'status': 'cuisines added'})
        except Exception as e:
            return Response({'error': str(e)}, status=400)
    
    @action(detail=True, methods=['post'])
    def set_cuisines(self, request, pk=None):
        """Set cuisines for a restaurant (replaces existing)"""
        restaurant = self.get_object()
        cuisine_ids = request.data.get('cuisine_ids', [])
        
        try:
            cuisines = Cuisine.objects.filter(id__in=cuisine_ids)
            restaurant.cuisines.set(cuisines)
            return Response({'status': 'cuisines set'})
        except Exception as e:
            return Response({'error': str(e)}, status=400)

class RestaurantScheduleViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = RestaurantScheduleSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['restaurant']
    
    queryset = RestaurantSchedule.objects.none()  # Add this line

    def get_queryset(self):
        alias = self._alias()
        return RestaurantSchedule.objects.using(alias).select_related('restaurant').all()

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic(using=alias):
            obj = RestaurantSchedule(**s.validated_data)
            obj.full_clean(validate_unique=False)
            obj.save(using=alias)
        s.instance = obj
        return Response(s.data, status=status.HTTP_201_CREATED)

class BlockedDayViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = BlockedDaySerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['restaurant']  # Remove 'date' from filterset_fields
    
    queryset = Blocked_Day.objects.none()

    def get_queryset(self):
        alias = self._alias()
        return Blocked_Day.objects.using(alias).select_related('restaurant').all()

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic(using=alias):
            obj = Blocked_Day(**s.validated_data)
            obj.full_clean(validate_unique=False)
            obj.save(using=alias)
        s.instance = obj
        return Response(s.data, status=status.HTTP_201_CREATED)

class TableBookingViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = TableBookingSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['restaurant']  # Remove 'booking_date', 'is_confirmed'
    
    queryset = TableBooking.objects.none()

    def get_queryset(self):
        alias = self._alias()
        return TableBooking.objects.using(alias).select_related('restaurant').all()

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic(using=alias):
            obj = TableBooking(**s.validated_data)
            obj.full_clean(validate_unique=False)
            obj.save(using=alias)
        s.instance = obj
        return Response(s.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'])
    def today_bookings(self, request):
        """Get today's bookings"""
        alias = self._alias()
        today = timezone.now().date()
        # Update this to use the correct date field from your model
        bookings = TableBooking.objects.using(alias).all()  # Remove date filter for now
        serializer = self.get_serializer(bookings, many=True)
        return Response(serializer.data)

class OrderConfigureViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = OrderConfigureSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['restaurant']
    
    queryset = OrderConfigure.objects.none()  # Add this line

    def get_queryset(self):
        alias = self._alias()
        return OrderConfigure.objects.using(alias).select_related('restaurant').all()

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic(using=alias):
            obj = OrderConfigure(**s.validated_data)
            obj.full_clean(validate_unique=False)
            obj.save(using=alias)
        s.instance = obj
        return Response(s.data, status=status.HTTP_201_CREATED)

# -------------------------------------------------------------------
# Menu Management ViewSets
# -------------------------------------------------------------------

class CuisineViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = CuisineSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'id']  # Remove 'created_at'
    ordering = ['name']
    
    queryset = Cuisine.objects.none()

    def get_queryset(self):
        alias = self._alias()
        return Cuisine.objects.using(alias).all()

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic(using=alias):
            obj = Cuisine(**s.validated_data)
            obj.full_clean(validate_unique=False)
            obj.save(using=alias)
        s.instance = obj
        return Response(s.data, status=status.HTTP_201_CREATED)

class CategoryViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = CategorySerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['cuisine']
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'id']  # Remove 'created_at'
    ordering = ['name']
    
    queryset = Category.objects.none()

    def get_queryset(self):
        alias = self._alias()
        return Category.objects.using(alias).select_related('cuisine').all()

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic(using=alias):
            obj = Category(**s.validated_data)
            obj.full_clean(validate_unique=False)
            obj.save(using=alias)
        s.instance = obj
        return Response(s.data, status=status.HTTP_201_CREATED)

class ItemViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = ItemSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['restaurant', 'cuisine', 'category', 'item_type']
    search_fields = ['item_name', 'description']
    ordering_fields = ['item_name', 'price', 'id']  # Remove 'created_at'
    ordering = ['item_name']
    
    queryset = Item.objects.none()

    def get_queryset(self):
        alias = self._alias()
        return Item.objects.using(alias).select_related('restaurant', 'cuisine', 'category').all()

    def get_serializer_class(self):
        if self.action == 'list':
            return ItemListSerializer
        return ItemSerializer

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic(using=alias):
            obj = Item(**s.validated_data)
            obj.full_clean(validate_unique=False)
            obj.save(using=alias)
        s.instance = obj
        return Response(s.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'])
    def by_cuisine(self, request):
        """Filter items by cuisine"""
        alias = self._alias()
        cuisine_id = request.query_params.get('cuisine_id')
        if cuisine_id:
            items = Item.objects.using(alias).filter(cuisine_id=cuisine_id)
            serializer = self.get_serializer(items, many=True)
            return Response(serializer.data)
        return Response({"error": "cuisine_id parameter required"}, 
                      status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def by_category(self, request):
        """Filter items by category"""
        alias = self._alias()
        category_id = request.query_params.get('category_id')
        if category_id:
            items = Item.objects.using(alias).filter(category_id=category_id)
            serializer = self.get_serializer(items, many=True)
            return Response(serializer.data)
        return Response({"error": "category_id parameter required"}, 
                      status=status.HTTP_400_BAD_REQUEST)

# -------------------------------------------------------------------
# Customer Management ViewSets
# -------------------------------------------------------------------

class CustomerViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = CustomerSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['customer_name', 'phone_number', 'email']
    ordering_fields = ['customer_name', 'id']  # Remove 'created_at'
    ordering = ['-id']
    
    queryset = Customer.objects.none()

    def get_queryset(self):
        alias = self._alias()
        return Customer.objects.using(alias).all()

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic(using=alias):
            obj = Customer(**s.validated_data)
            obj.full_clean(validate_unique=False)
            obj.save(using=alias)
        s.instance = obj
        return Response(s.data, status=status.HTTP_201_CREATED)

# -------------------------------------------------------------------
# Order Management ViewSets
# -------------------------------------------------------------------

class OrderViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = OrderSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['restaurant', 'Paid', 'order_type']
    search_fields = ['customer_name', 'customer_phone']
    ordering_fields = ['order_time', 'total_amount']
    ordering = ['-order_time']
    
    queryset = Order.objects.none()

    def get_queryset(self):
        alias = self._alias()
        return Order.objects.using(alias).select_related('restaurant').all()

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic(using=alias):
            obj = Order(**s.validated_data)
            obj.full_clean(validate_unique=False)
            obj.save(using=alias)
        s.instance = obj
        return Response(s.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'])
    def pending_orders(self, request):
        """Get pending orders"""
        alias = self._alias()
        orders = Order.objects.using(alias).filter(Paid=False)
        serializer = self.get_serializer(orders, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def today_orders(self, request):
        """Get today's orders"""
        alias = self._alias()
        today = timezone.now().date()
        orders = Order.objects.using(alias).filter(order_time__date=today)
        serializer = self.get_serializer(orders, many=True)
        return Response(serializer.data)

# -------------------------------------------------------------------
# Inventory Management ViewSets
# -------------------------------------------------------------------

class SupplierViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = SupplierSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['supplier_name', 'contact_person', 'phone', 'email']
    ordering_fields = ['supplier_name', 'id']  # Remove 'created_at'
    ordering = ['supplier_name']
    
    queryset = Supplier.objects.none()

    def get_queryset(self):
        alias = self._alias()
        return Supplier.objects.using(alias).all()

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic(using=alias):
            obj = Supplier(**s.validated_data)
            obj.full_clean(validate_unique=False)
            obj.save(using=alias)
        s.instance = obj
        return Response(s.data, status=status.HTTP_201_CREATED)

class WarehouseViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = WarehouseSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['restaurant']
    search_fields = ['warehouse_name', 'location']
    ordering_fields = ['warehouse_name', 'id']  # Remove 'created_at'
    ordering = ['warehouse_name']
    
    queryset = Warehouse.objects.none()

    def get_queryset(self):
        alias = self._alias()
        return Warehouse.objects.using(alias).select_related('restaurant').all()

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic(using=alias):
            obj = Warehouse(**s.validated_data)
            obj.full_clean(validate_unique=False)
            obj.save(using=alias)
        s.instance = obj
        return Response(s.data, status=status.HTTP_201_CREATED)

class InventoryItemViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = InventoryItemSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['category', 'preferred_supplier']
    search_fields = ['item_name', 'sku']
    ordering_fields = ['item_name', 'current_stock', 'last_updated']
    ordering = ['item_name']
    
    queryset = InventoryItem.objects.none()

    def get_queryset(self):
        alias = self._alias()
        return InventoryItem.objects.using(alias).select_related('category', 'preferred_supplier').all()

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic(using=alias):
            obj = InventoryItem(**s.validated_data)
            obj.full_clean(validate_unique=False)
            obj.save(using=alias)
        s.instance = obj
        return Response(s.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'])
    def low_stock(self, request):
        """Get items with low stock"""
        alias = self._alias()
        items = InventoryItem.objects.using(alias).filter(
            current_stock__lte=F('min_stock_level')  # Fixed: now uses F
        )
        serializer = self.get_serializer(items, many=True)
        return Response(serializer.data)

class InventoryMovementViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = InventoryMovementSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['item', 'movement_type', 'from_location', 'to_location']
    search_fields = ['item__item_name', 'reference_number']
    ordering_fields = ['timestamp', 'quantity']
    ordering = ['-timestamp']
    
    queryset = InventoryMovement.objects.none()

    def get_queryset(self):
        alias = self._alias()
        return InventoryMovement.objects.using(alias).select_related('item', 'from_location', 'to_location').all()

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic(using=alias):
            obj = InventoryMovement(**s.validated_data)
            obj.full_clean(validate_unique=False)
            obj.save(using=alias)
        s.instance = obj
        return Response(s.data, status=status.HTTP_201_CREATED)

# -------------------------------------------------------------------
# Ingredient Management ViewSets
# -------------------------------------------------------------------

class IngredientViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = IngredientSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['ingredient_name']
    ordering_fields = ['ingredient_name', 'id']  # Remove 'created_at'
    ordering = ['ingredient_name']
    
    queryset = Ingredient.objects.none()

    def get_queryset(self):
        alias = self._alias()
        return Ingredient.objects.using(alias).all()

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic(using=alias):
            obj = Ingredient(**s.validated_data)
            obj.full_clean(validate_unique=False)
            obj.save(using=alias)
        s.instance = obj
        return Response(s.data, status=status.HTTP_201_CREATED)

class ItemIngredientViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = ItemIngredientSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['item', 'ingredient']
    
    queryset = ItemIngredient.objects.none()

    def get_queryset(self):
        alias = self._alias()
        return ItemIngredient.objects.using(alias).select_related('item', 'ingredient').all()

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic(using=alias):
            obj = ItemIngredient(**s.validated_data)
            obj.full_clean(validate_unique=False)
            obj.save(using=alias)
        s.instance = obj
        return Response(s.data, status=status.HTTP_201_CREATED)

# -------------------------------------------------------------------
# Media Management ViewSets
# -------------------------------------------------------------------

class RestoCoverImageViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = RestoCoverImageSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['restaurant']
    
    queryset = RestoCoverImage.objects.none()  # Add this line

    def get_queryset(self):
        alias = self._alias()
        return RestoCoverImage.objects.using(alias).select_related('restaurant').all()

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic(using=alias):
            obj = RestoCoverImage(**s.validated_data)
            obj.full_clean(validate_unique=False)
            obj.save(using=alias)
        s.instance = obj
        return Response(s.data, status=status.HTTP_201_CREATED)

class RestoMenuImageViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = RestoMenuImageSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['restaurant']
    
    queryset = RestoMenuImage.objects.none()  # Add this line

    def get_queryset(self):
        alias = self._alias()
        return RestoMenuImage.objects.using(alias).select_related('restaurant').all()

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic(using=alias):
            obj = RestoMenuImage(**s.validated_data)
            obj.full_clean(validate_unique=False)
            obj.save(using=alias)
        s.instance = obj
        return Response(s.data, status=status.HTTP_201_CREATED)

class RestoGalleryImageViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = RestoGalleryImageSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['restaurant']
    
    queryset = RestoGalleryImage.objects.none()  # Add this line

    def get_queryset(self):
        alias = self._alias()
        return RestoGalleryImage.objects.using(alias).select_related('restaurant').all()

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic(using=alias):
            obj = RestoGalleryImage(**s.validated_data)
            obj.full_clean(validate_unique=False)
            obj.save(using=alias)
        s.instance = obj
        return Response(s.data, status=status.HTTP_201_CREATED)

class RestoOtherFileViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = RestoOtherFileSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['restaurant']
    
    queryset = RestoOtherFile.objects.none()

    def get_queryset(self):
        alias = self._alias()
        return RestoOtherFile.objects.using(alias).select_related('restaurant').all()

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic(using=alias):
            obj = RestoOtherFile(**s.validated_data)
            obj.full_clean(validate_unique=False)
            obj.save(using=alias)
        s.instance = obj
        return Response(s.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'])
    def by_restaurant(self, request):
        """Get files by restaurant"""
        alias = self._alias()
        restaurant_id = request.query_params.get('restaurant_id')
        if restaurant_id:
            files = RestoOtherFile.objects.using(alias).filter(restaurant_id=restaurant_id)
            serializer = self.get_serializer(files, many=True)
            return Response(serializer.data)
        return Response({"error": "restaurant_id parameter required"}, 
                      status=status.HTTP_400_BAD_REQUEST)


