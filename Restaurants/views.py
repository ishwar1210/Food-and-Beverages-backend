from __future__ import annotations
import json
import logging
from django.db.models import Q, Count, Sum, Min, F  # Add F here

from django.db.models import Prefetch
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
from .pagination import StandardResultsSetPagination
from rest_framework.parsers import MultiPartParser, FormParser

from FB.db_router import set_current_tenant, get_current_tenant

from .utils import register_tenant_database, ensure_alias_for_client
from .models import (
    Restaurant, RestaurantSchedule, Blocked_Day, TableBooking, OrderConfigure, MasterCuisine, MasterItem,
    Cuisine, Category, Item, Customer, RestoCoverImage, RestoMenuImage,
    RestoGalleryImage, RestoOtherFile,  Ingredient, QtyIngredient,
    Supplier, Warehouse, InventoryItem, InventoryMovement, InventoryAudit, Order, tablebookingfloor, Table, 
    TableBookingLog, KOT, Billing
)
from .serializers import (
    RestaurantSerializer, RestaurantScheduleSerializer, BlockedDaySerializer,
    TableBookingSerializer, OrderConfigureSerializer, MasterCuisineSerializer, MasterItemSerializer, CuisineSerializer,
    CategorySerializer,  ItemSerializer, CustomerSerializer, RestoCoverImageSerializer,
    RestoMenuImageSerializer, RestoGalleryImageSerializer, RestoOtherFileSerializer,
    IngredientSerializer, QtyIngredientSerializer, SupplierSerializer, WarehouseSerializer,
    InventoryItemSerializer, InventoryMovementSerializer, OrderSerializer,
    RestaurantListSerializer, ItemListSerializer , RestaurantScheduleBulkSerializer, CuisineNestedSerializer,
    TableBookingFloorSerializer , TableSerializer, TableBookingLogSerializer, KOTSerializer, BillingSerializer
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

class RestaurantViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet ):
    serializer_class = RestaurantSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['pure_veg', 'serves_alcohol', 'wheelchair_accessible', 'cash_on_delivery']
    search_fields = ['restaurant_name', 'address', 'number']
    ordering_fields = ['restaurant_name', 'cost_for_two', 'id']
    ordering = ['-id']

    queryset = Restaurant.objects.none()

    def get_queryset(self):
        alias = self._alias()
        return Restaurant.objects.using(alias).all()

    def get_serializer_class(self):
        if self.action == 'list':
            return RestaurantListSerializer
        return RestaurantSerializer

    def perform_create(self, serializer):
        alias = self._alias()
        serializer.save(
            created_by_id=self.request.user.id if self.request.user.is_authenticated else None,
            using=alias
    )

    def perform_update(self, serializer):
        alias = self._alias()
        serializer.save(
            updated_by_id=self.request.user.id if self.request.user.is_authenticated else None,
            using=alias
    )

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
        """Get restaurants (no active field exists now)"""
        alias = self._alias()
        restaurants = Restaurant.objects.using(alias).all()
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
            return Response(
                {'error': 'Failed to fetch dashboard statistics'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class RestaurantScheduleViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = RestaurantScheduleSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["restaurant", "day", "operational"]
    search_fields = ["restaurant__restaurant_name"]
    ordering_fields = ["day", "start_time", "end_time", "id"]
    ordering = ["day"]

    queryset = RestaurantSchedule.objects.none()

    def get_queryset(self):
        alias = self._alias()
        return (
            RestaurantSchedule.objects.using(alias)
            .select_related("restaurant")
            .all()
        )

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic(using=alias):
            obj = RestaurantSchedule(**serializer.validated_data)
            obj.full_clean(validate_unique=False)
            obj.save(using=alias)

        serializer.instance = obj
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"], url_path="by-restaurant/(?P<restaurant_id>[^/.]+)")
    def by_restaurant(self, request, restaurant_id=None):
        """Get full 7-day schedule of a restaurant (ensures missing days are created)."""
        alias = self._alias()

        # Ensure all 7 days exist
        for day in range(1, 8):
            RestaurantSchedule.objects.using(alias).get_or_create(
                restaurant_id=restaurant_id,
                day=day,
                defaults={"operational": False},
            )

        schedules = (
            RestaurantSchedule.objects.using(alias)
            .filter(restaurant_id=restaurant_id)
            .order_by("day")
        )

        serializer = self.get_serializer(schedules, many=True)
        return Response(serializer.data)

class RestaurantScheduleBulkView(
    RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, generics.CreateAPIView
):
    serializer_class = RestaurantScheduleBulkSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        objs = s.save()

        # Response frontend ke liye — har din ka alag record
        output = [
            {
                "day": obj.day,
                "day_display": obj.get_day_display(),
                "operational": obj.operational,
                "start_time": obj.start_time,
                "end_time": obj.end_time,
                "break_start_time": obj.break_start_time,
                "break_end_time": obj.break_end_time,
                "booking_allowed": obj.booking_allowed,
                "order_allowed": obj.order_allowed,
                "last_order_time": obj.last_order_time,
            }
            for obj in objs
        ]
        return Response(output, status=status.HTTP_201_CREATED)

class RestaurantWeeklyScheduleView(APIView):
    """
    Returns 7 rows (Mon-Sun) for a restaurant's schedule.
    If some days are missing, they will be filled with defaults (blank).
    """
    pagination_class = StandardResultsSetPagination
    def get(self, request, restaurant_id):
        # Pehle se existing schedules fetch karo
        schedules = RestaurantSchedule.objects.filter(restaurant_id=restaurant_id)
        schedule_map = {s.day: s for s in schedules}  # map day → schedule

        # Default response structure (1-7 = Mon-Sun)
        days = range(1, 8)
        output = []

        for day in days:
            if day in schedule_map:
                serialized = RestaurantScheduleSerializer(schedule_map[day]).data
            else:
                
                serialized = {
                    "day": day,
                    "operational": False,
                    "start_time": None,
                    "end_time": None,
                    "break_start_time": None,
                    "break_end_time": None,
                    "booking_allowed": False,
                    "order_allowed": False,
                    "last_order_time": None,
                }
            output.append(serialized)

        return Response(output, status=status.HTTP_200_OK)

class BlockedDayViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = BlockedDaySerializer
    pagination_class = StandardResultsSetPagination
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
    pagination_class = StandardResultsSetPagination
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
    pagination_class = StandardResultsSetPagination
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

class MasterCuisineViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = MasterCuisineSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name"]
    ordering_fields = ["name", "id"]
    ordering = ["name"]
    queryset = MasterCuisine.objects.none()

    def get_queryset(self):
        alias = self._alias()
        return MasterCuisine.objects.using(alias).all()


class MasterItemViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = MasterItemSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["master_cuisine"]
    search_fields = ["name"]
    ordering_fields = ["name", "id"]
    ordering = ["name"]
    queryset = MasterItem.objects.none()

    def get_queryset(self):
        alias = self._alias()
        return MasterItem.objects.using(alias).select_related("master_cuisine").all()


class CuisineViewSet(
    RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet
):
    serializer_class = CuisineSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name"]
    ordering_fields = ["name", "id"]
    ordering = ["name"]
    queryset = Cuisine.objects.none()

    def get_queryset(self):
        alias = self._alias()
        return Cuisine.objects.using(alias).select_related("restaurant", "master_cuisine").all()

    def perform_create(self, serializer):
        alias = self._alias()

        # pehle cuisine ko tenant DB me save karna
        cuisine = serializer.save(using=alias)

        # ab master items uthao
        master_items = MasterItem.objects.using(alias).filter(
            master_cuisine=cuisine.master_cuisine
        )

        # bulk create items
        items_to_create = [
            Item(
                restaurant=cuisine.restaurant,
                cuisine=cuisine,
                master_item=m_item,
                item_name=m_item.name,
                price=0,        # default price
                master_price=0, # default master price
                item_type=m_item.item_type
            )
            for m_item in master_items
        ]
        if items_to_create:
            Item.objects.using(alias).bulk_create(items_to_create)


class CategoryViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = CategorySerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["cuisines", "restaurant"]
    search_fields = ["name"]
    ordering_fields = ["name", "id"]
    ordering = ["name"]
    queryset = Category.objects.none()

    def get_queryset(self):
        alias = self._alias()
        return Category.objects.using(alias).select_related( "restaurant", "parent").all()


class ItemViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = ItemSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["restaurant", "cuisine", "category", "item_type", "master_item"]
    search_fields = ["item_name", "description"]
    ordering_fields = ["item_name", "price", "id"]
    ordering = ["item_name"]
    queryset = Item.objects.none()

    def get_queryset(self):
        alias = self._alias()
        qs = Item.objects.using(alias).select_related(
            "restaurant", "cuisine", "master_item", "category"
        ).all()

        # Filter by restaurant and pure_veg logic
        restaurant_id = self.request.query_params.get("restaurant")
        if restaurant_id:
            try:
                restaurant = Restaurant.objects.using(alias).get(pk=restaurant_id)
                if restaurant.pure_veg:
                    qs = qs.filter(restaurant_id=restaurant_id, master_item__is_veg=True)
                else:
                    qs = qs.filter(restaurant_id=restaurant_id)
            except Restaurant.DoesNotExist:
                qs = qs.none()
        return qs

    @action(detail=False, methods=["get"])
    def by_cuisine(self, request):
        alias = self._alias()
        cuisine_id = request.query_params.get("cuisine_id")
        if cuisine_id:
            items = Item.objects.using(alias).filter(cuisine_id=cuisine_id)
            serializer = self.get_serializer(items, many=True)
            return Response(serializer.data)
        return Response({"error": "cuisine_id parameter required"}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["get"])
    def by_category(self, request):
        alias = self._alias()
        category_id = request.query_params.get("category_id")
        if category_id:
            items = Item.objects.using(alias).filter(category_id=category_id)
            serializer = self.get_serializer(items, many=True)
            return Response(serializer.data)
        return Response({"error": "category_id parameter required"}, status=status.HTTP_400_BAD_REQUEST)

# -------------------------------------------------------------------
# Customer Management ViewSets
# -------------------------------------------------------------------

class CustomerViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = CustomerSerializer
    pagination_class = StandardResultsSetPagination
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
    pagination_class = StandardResultsSetPagination
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
    pagination_class = StandardResultsSetPagination
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
    pagination_class = StandardResultsSetPagination
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
    pagination_class = StandardResultsSetPagination
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
    pagination_class = StandardResultsSetPagination
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
    pagination_class = StandardResultsSetPagination
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

class QtyIngredientViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = QtyIngredientSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['item', 'ingredient']
    
    queryset = QtyIngredient.objects.none()

    def get_queryset(self):
        alias = self._alias()
        return QtyIngredient.objects.using(alias).select_related('item', 'ingredient').all()

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic(using=alias):
            obj = QtyIngredient(**s.validated_data)
            obj.full_clean(validate_unique=False)
            obj.save(using=alias)
        s.instance = obj
        return Response(s.data, status=status.HTTP_201_CREATED)

# -------------------------------------------------------------------
# Media Management ViewSets
# -------------------------------------------------------------------



class RestoCoverImageViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = RestoCoverImageSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['restaurant']
    parser_classes = [MultiPartParser, FormParser]  # Add this line
    
    queryset = RestoCoverImage.objects.none()

    def get_queryset(self):
        alias = self._alias()
        return RestoCoverImage.objects.using(alias).select_related('restaurant').all()

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        # Handle multi-upload for cover images too
        files = request.FILES.getlist("images") or request.FILES.getlist("image")
        restaurant_id = request.data.get("restaurant")
        if not restaurant_id:
            return Response({"detail": "restaurant required"}, status=400)
        if not files:
            return Response({"detail": "No image(s) provided"}, status=400)
        objs = []
        for f in files:
            obj = RestoCoverImage(restaurant_id=restaurant_id, image=f)
            obj.save(using=alias)
            objs.append(obj)
        data = RestoCoverImageSerializer(objs, many=True, context={"alias": alias}).data
        return Response(data, status=201)

# ------------------- Menu Image -------------------
class RestoMenuImageViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = RestoMenuImageSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['restaurant']
    parser_classes = [MultiPartParser, FormParser]  # Ensure this line exists
    queryset = RestoMenuImage.objects.none()

    def get_queryset(self):
        alias = self._alias()
        return RestoMenuImage.objects.using(alias).all()

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["alias"] = self._alias()
        return ctx

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        # Accept field names: images (multi) OR image (single)
        files = request.FILES.getlist("images")  # preferred multi
        if not files:
            files = request.FILES.getlist("image")  # fallback if frontend sends multiple under 'image'
        restaurant_id = request.data.get("restaurant")
        if not restaurant_id:
            return Response({"detail": "restaurant required"}, status=400)
        if not files:
            return Response({"detail": "No image(s) provided (use field 'images')"}, status=400)

        # Multi create
        objs = []
        for f in files:
            obj = RestoMenuImage(restaurant_id=restaurant_id, image=f)
            obj.save(using=alias)
            objs.append(obj)
        data = RestoMenuImageSerializer(objs, many=True, context={"alias": alias}).data
        return Response(data, status=201)


# ------------------- Gallery Image -------------------
class RestoGalleryImageViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = RestoGalleryImageSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['restaurant']
    parser_classes = [MultiPartParser, FormParser]  # Ensure this line exists
    queryset = RestoGalleryImage.objects.none()

    def get_queryset(self):
        alias = self._alias()
        return RestoGalleryImage.objects.using(alias).all()

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["alias"] = self._alias()
        return ctx

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        files = request.FILES.getlist("images") or request.FILES.getlist("image")
        restaurant_id = request.data.get("restaurant")
        if not restaurant_id:
            return Response({"detail": "restaurant required"}, status=400)
        if not files:
            return Response({"detail": "No image(s) provided"}, status=400)
        objs = []
        for f in files:
            obj = RestoGalleryImage(restaurant_id=restaurant_id, image=f)
            obj.save(using=alias)
            objs.append(obj)
        data = RestoGalleryImageSerializer(objs, many=True, context={"alias": alias}).data
        return Response(data, status=201)


# ------------------- Other File -------------------
class RestoOtherFileViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = RestoOtherFileSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['restaurant']
    parser_classes = [MultiPartParser, FormParser]  # Ensure this line exists
    queryset = RestoOtherFile.objects.none()

    def get_queryset(self):
        alias = self._alias()
        return RestoOtherFile.objects.using(alias).all()

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["alias"] = self._alias()
        return ctx

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        files = request.FILES.getlist("files") or request.FILES.getlist("file")
        restaurant_id = request.data.get("restaurant")
        if not restaurant_id:
            return Response({"detail": "restaurant required"}, status=400)
        if not files:
            return Response({"detail": "No file(s) provided"}, status=400)
        objs = []
        for f in files:
            obj = RestoOtherFile(restaurant_id=restaurant_id, file=f)
            obj.save(using=alias)
            objs.append(obj)
        data = RestoOtherFileSerializer(objs, many=True, context={"alias": alias}).data
        return Response(data, status=201)

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

# -------------------------------------------------------------------
class CuisineViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet): 
    serializer_class = CuisineSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name"]
    ordering_fields = ["name", "id"]
    ordering = ["name"]
    queryset = Cuisine.objects.none()

    def get_queryset(self):
        alias = self._alias()
        return Cuisine.objects.using(alias).select_related("restaurant", "master_cuisine").all()

    def perform_create(self, serializer):
        alias = self._alias()
        cuisine = serializer.save()
        master_items = MasterItem.objects.using(alias).filter(master_cuisine=cuisine.master_cuisine)
        items_to_create = [
            Item(
                restaurant=cuisine.restaurant,
                cuisine=cuisine,
                master_item=m_item,
                item_name=m_item.name,
                price=0,
            )
            for m_item in master_items
        ]
        if items_to_create:
            Item.objects.using(alias).bulk_create(items_to_create)

    # 🔹 Custom nested API
    @action(detail=False, methods=["get"])
    def with_categories_items(self, request):
        alias = self._alias()
        cuisines = Cuisine.objects.using(alias).prefetch_related(
            Prefetch("categories", queryset=Category.objects.using(alias).prefetch_related("items"))
        )
        serializer = CuisineNestedSerializer(cuisines, many=True)
        return Response(serializer.data)

# ============= Table Booking ViewSets =============

class TableBookingFloorViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = TableBookingFloorSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['floor_name']
    ordering_fields = ['floor_name', 'id']
    ordering = ['floor_name']

    queryset = tablebookingfloor.objects.none()

    def get_queryset(self):
        alias = self._alias()
        return tablebookingfloor.objects.using(alias).all()

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic(using=alias):
            obj = tablebookingfloor(**s.validated_data)
            obj.full_clean(validate_unique=False)
            obj.save(using=alias)
        s.instance = obj
        return Response(s.data, status=status.HTTP_201_CREATED)


class TableViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = TableSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["restaurant", "floor", "status"]
    search_fields = []
    ordering_fields = ["id"]
    ordering = ["id"]
    queryset = Table.objects.none()

    def get_queryset(self):
        alias = self._alias()
        return Table.objects.using(alias).select_related("restaurant", "floor").all()

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["alias"] = self._alias()
        return ctx

class TableBookingLogViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = TableBookingLogSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['customer__name']
    ordering_fields = ['start_time', 'end_time', 'id']
    ordering = ['-start_time']

    queryset = TableBookingLog.objects.none()

    def get_queryset(self):
        alias = self._alias()
        return TableBookingLog.objects.using(alias).all()

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic(using=alias):
            obj = TableBookingLog(**s.validated_data)
            obj.full_clean(validate_unique=False)
            obj.save(using=alias)
        s.instance = obj
        return Response(s.data, status=status.HTTP_201_CREATED)


# ============= KOT & Billing ViewSets =============

class KOTViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = KOTSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['kot_number', 'order__id', 'customer__name']
    ordering_fields = ['kot_number', 'time', 'id']
    ordering = ['-time']

    queryset = KOT.objects.none()

    def get_queryset(self):
        alias = self._alias()
        return KOT.objects.using(alias).all()

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic(using=alias):
            obj = KOT(**s.validated_data)
            obj.full_clean(validate_unique=False)
            obj.save(using=alias)
        s.instance = obj
        return Response(s.data, status=status.HTTP_201_CREATED)


class BillingViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = BillingSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['customer__name', 'order__id']
    ordering_fields = ['billing_time', 'total_amount', 'id']
    ordering = ['-billing_time']

    queryset = Billing.objects.none()

    def get_queryset(self):
        alias = self._alias()
        return Billing.objects.using(alias).all()

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic(using=alias):
            obj = Billing(**s.validated_data)
            obj.full_clean(validate_unique=False)
            obj.save(using=alias)
        s.instance = obj
        return Response(s.data, status=status.HTTP_201_CREATED)
