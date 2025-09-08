from rest_framework import serializers
from rest_framework.validators import UniqueTogetherValidator, UniqueValidator
from django.db.models import Sum  # Add this import
from .models import (
    Restaurant, RestaurantSchedule, Blocked_Day, TableBooking, OrderConfigure,
    Cuisine, Category, Item, Customer, RestoCoverImage, RestoMenuImage,
    RestoGalleryImage, RestoOtherFile, ItemType, Ingredient, ItemIngredient,
    Supplier, Warehouse, InventoryItem, InventoryMovement, InventoryAudit, Order
)

class AliasContextMixin:
    @property
    def alias(self) -> str:
        alias = self.context.get("alias")
        if not alias:
            raise RuntimeError("Serializer context missing 'alias'.")
        return alias

class AliasModelSerializer(AliasContextMixin, serializers.ModelSerializer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Serializer-level unique validators
        for v in self.validators:
            if isinstance(v, (UniqueTogetherValidator, UniqueValidator)) and getattr(v, "queryset", None) is not None:
                v.queryset = v.queryset.using(self.alias)

        for field in self.fields.values():
            for val in getattr(field, "validators", []):
                if isinstance(val, UniqueValidator) and getattr(val, "queryset", None) is not None:
                    val.queryset = val.queryset.using(self.alias)

# ================= Core Restaurant Serializers =================

class RestaurantSerializer(AliasModelSerializer):
    class Meta:
        model = Restaurant
        fields = '__all__'
        read_only_fields = ['id']

    def create(self, validated_data):
        obj = Restaurant(**validated_data)
        obj.full_clean(validate_unique=False)
        obj.save(using=self.alias)
        return obj

class RestaurantScheduleSerializer(AliasModelSerializer):
    restaurant = serializers.PrimaryKeyRelatedField(queryset=Restaurant.objects.none())

    class Meta:
        model = RestaurantSchedule
        fields = '__all__'
        read_only_fields = ['id']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["restaurant"].queryset = Restaurant.objects.using(self.alias).all()

    def create(self, validated_data):
        obj = RestaurantSchedule(**validated_data)
        obj.full_clean(validate_unique=False)
        obj.save(using=self.alias)
        return obj

class BlockedDaySerializer(AliasModelSerializer):
    restaurant = serializers.PrimaryKeyRelatedField(queryset=RestaurantSchedule.objects.none())

    class Meta:
        model = Blocked_Day
        fields = '__all__'  # Use __all__ to include all actual model fields
        read_only_fields = ['id']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["restaurant"].queryset = RestaurantSchedule.objects.using(self.alias).all()

    def create(self, validated_data):
        obj = Blocked_Day(**validated_data)
        obj.full_clean(validate_unique=False)
        obj.save(using=self.alias)
        return obj

class TableBookingSerializer(AliasModelSerializer):
    restaurant = serializers.PrimaryKeyRelatedField(queryset=Restaurant.objects.none())

    class Meta:
        model = TableBooking
        fields = '__all__'  # Use __all__ to include all actual model fields
        read_only_fields = ['id']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["restaurant"].queryset = Restaurant.objects.using(self.alias).all()

    def create(self, validated_data):
        obj = TableBooking(**validated_data)
        obj.full_clean(validate_unique=False)
        obj.save(using=self.alias)
        return obj

class OrderConfigureSerializer(AliasModelSerializer):
    restaurant = serializers.PrimaryKeyRelatedField(queryset=Restaurant.objects.none())

    class Meta:
        model = OrderConfigure
        fields = '__all__'
        read_only_fields = ['id']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["restaurant"].queryset = Restaurant.objects.using(self.alias).all()

    def create(self, validated_data):
        obj = OrderConfigure(**validated_data)
        obj.full_clean(validate_unique=False)
        obj.save(using=self.alias)
        return obj

# ================= Menu Management Serializers =================

class CuisineSerializer(AliasModelSerializer):
    class Meta:
        model = Cuisine
        fields = '__all__'
        read_only_fields = ['id']

    def create(self, validated_data):
        obj = Cuisine(**validated_data)
        obj.full_clean(validate_unique=False)
        obj.save(using=self.alias)
        return obj

class CategorySerializer(AliasModelSerializer):
    cuisine = serializers.PrimaryKeyRelatedField(queryset=Cuisine.objects.none())

    class Meta:
        model = Category
        fields = '__all__'
        read_only_fields = ['id']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cuisine"].queryset = Cuisine.objects.using(self.alias).all()

    def create(self, validated_data):
        obj = Category(**validated_data)
        obj.full_clean(validate_unique=False)
        obj.save(using=self.alias)
        return obj

class ItemSerializer(AliasModelSerializer):
    restaurant = serializers.PrimaryKeyRelatedField(queryset=RestaurantSchedule.objects.none())
    cuisine = serializers.PrimaryKeyRelatedField(queryset=Cuisine.objects.none())
    category = serializers.PrimaryKeyRelatedField(queryset=Category.objects.none())

    class Meta:
        model = Item
        fields = '__all__'
        read_only_fields = ['id']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["restaurant"].queryset = RestaurantSchedule.objects.using(self.alias).all()
        self.fields["cuisine"].queryset = Cuisine.objects.using(self.alias).all()
        self.fields["category"].queryset = Category.objects.using(self.alias).all()

    def create(self, validated_data):
        obj = Item(**validated_data)
        obj.full_clean(validate_unique=False)
        obj.save(using=self.alias)
        return obj

# ================= Customer Serializers =================

class CustomerSerializer(AliasModelSerializer):
    class Meta:
        model = Customer
        fields = '__all__'
        read_only_fields = ['id']

    def create(self, validated_data):
        obj = Customer(**validated_data)
        obj.full_clean(validate_unique=False)
        obj.save(using=self.alias)
        return obj

# ================= Attachment Serializers =================

class RestoCoverImageSerializer(AliasModelSerializer):
    restaurant = serializers.PrimaryKeyRelatedField(queryset=Restaurant.objects.none())

    class Meta:
        model = RestoCoverImage
        fields = '__all__'
        read_only_fields = ['id']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["restaurant"].queryset = Restaurant.objects.using(self.alias).all()

    def create(self, validated_data):
        obj = RestoCoverImage(**validated_data)
        obj.full_clean(validate_unique=False)
        obj.save(using=self.alias)
        return obj

class RestoMenuImageSerializer(AliasModelSerializer):
    restaurant = serializers.PrimaryKeyRelatedField(queryset=Restaurant.objects.none())

    class Meta:
        model = RestoMenuImage
        fields = '__all__'
        read_only_fields = ['id']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["restaurant"].queryset = Restaurant.objects.using(self.alias).all()

    def create(self, validated_data):
        obj = RestoMenuImage(**validated_data)
        obj.full_clean(validate_unique=False)
        obj.save(using=self.alias)
        return obj

class RestoGalleryImageSerializer(AliasModelSerializer):
    restaurant = serializers.PrimaryKeyRelatedField(queryset=Restaurant.objects.none())

    class Meta:
        model = RestoGalleryImage
        fields = '__all__'
        read_only_fields = ['id']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["restaurant"].queryset = Restaurant.objects.using(self.alias).all()

    def create(self, validated_data):
        obj = RestoGalleryImage(**validated_data)
        obj.full_clean(validate_unique=False)
        obj.save(using=self.alias)
        return obj

class RestoOtherFileSerializer(AliasModelSerializer):
    restaurant = serializers.PrimaryKeyRelatedField(queryset=Restaurant.objects.none())

    class Meta:
        model = RestoOtherFile
        fields = ['id', 'restaurant', 'file']
        read_only_fields = ['id']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["restaurant"].queryset = Restaurant.objects.using(self.alias).all()

    def create(self, validated_data):
        obj = RestoOtherFile(**validated_data)
        obj.full_clean(validate_unique=False)
        obj.save(using=self.alias)
        return obj

# ================= Ingredient Management Serializers =================

class IngredientSerializer(AliasModelSerializer):
    class Meta:
        model = Ingredient
        fields = '__all__'
        read_only_fields = ['id']

    def create(self, validated_data):
        obj = Ingredient(**validated_data)
        obj.full_clean(validate_unique=False)
        obj.save(using=self.alias)
        return obj

class ItemIngredientSerializer(AliasModelSerializer):
    item = serializers.PrimaryKeyRelatedField(queryset=Item.objects.none())
    ingredient = serializers.PrimaryKeyRelatedField(queryset=Ingredient.objects.none())

    class Meta:
        model = ItemIngredient
        fields = '__all__'
        read_only_fields = ['id']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["item"].queryset = Item.objects.using(self.alias).all()
        self.fields["ingredient"].queryset = Ingredient.objects.using(self.alias).all()

    def create(self, validated_data):
        obj = ItemIngredient(**validated_data)
        obj.full_clean(validate_unique=False)
        obj.save(using=self.alias)
        return obj

# ================= Inventory Management Serializers =================

class SupplierSerializer(AliasModelSerializer):
    class Meta:
        model = Supplier
        fields = '__all__'
        read_only_fields = ['id']

    def create(self, validated_data):
        obj = Supplier(**validated_data)
        obj.full_clean(validate_unique=False)
        obj.save(using=self.alias)
        return obj

class WarehouseSerializer(AliasModelSerializer):
    restaurant = serializers.PrimaryKeyRelatedField(queryset=Restaurant.objects.none(), required=False, allow_null=True)

    class Meta:
        model = Warehouse
        fields = '__all__'
        read_only_fields = ['id']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["restaurant"].queryset = Restaurant.objects.using(self.alias).all()

    def create(self, validated_data):
        obj = Warehouse(**validated_data)
        obj.full_clean(validate_unique=False)
        obj.save(using=self.alias)
        return obj

class InventoryItemSerializer(AliasModelSerializer):
    preferred_supplier = serializers.PrimaryKeyRelatedField(queryset=Supplier.objects.none(), required=False, allow_null=True)
    category = serializers.PrimaryKeyRelatedField(queryset=Category.objects.none(), required=False, allow_null=True)

    class Meta:
        model = InventoryItem
        fields = '__all__'
        read_only_fields = ['id', 'last_updated']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["preferred_supplier"].queryset = Supplier.objects.using(self.alias).all()
        self.fields["category"].queryset = Category.objects.using(self.alias).all()

    def create(self, validated_data):
        obj = InventoryItem(**validated_data)
        obj.full_clean(validate_unique=False)
        obj.save(using=self.alias)
        return obj

class InventoryMovementSerializer(AliasModelSerializer):
    item = serializers.PrimaryKeyRelatedField(queryset=InventoryItem.objects.none())
    from_location = serializers.PrimaryKeyRelatedField(queryset=Warehouse.objects.none(), required=False, allow_null=True)
    to_location = serializers.PrimaryKeyRelatedField(queryset=Warehouse.objects.none(), required=False, allow_null=True)

    class Meta:
        model = InventoryMovement
        fields = '__all__'
        read_only_fields = ['id', 'timestamp']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["item"].queryset = InventoryItem.objects.using(self.alias).all()
        self.fields["from_location"].queryset = Warehouse.objects.using(self.alias).all()
        self.fields["to_location"].queryset = Warehouse.objects.using(self.alias).all()

    def create(self, validated_data):
        obj = InventoryMovement(**validated_data)
        obj.full_clean(validate_unique=False)
        obj.save(using=self.alias)
        return obj

# ================= Order Management Serializers =================

class OrderSerializer(AliasModelSerializer):
    restaurant = serializers.PrimaryKeyRelatedField(queryset=Restaurant.objects.none())

    class Meta:
        model = Order
        fields = '__all__'
        read_only_fields = ['id', 'order_time']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["restaurant"].queryset = Restaurant.objects.using(self.alias).all()

    def create(self, validated_data):
        obj = Order(**validated_data)
        obj.full_clean(validate_unique=False)
        obj.save(using=self.alias)
        return obj

# ================= List Serializers (for detailed views) =================

class RestaurantListSerializer(serializers.ModelSerializer):
    """List view with related data for restaurants"""
    total_tables = serializers.SerializerMethodField()
    active_orders_count = serializers.SerializerMethodField()

    class Meta:
        model = Restaurant
        fields = [
            'id', 'restaurant_name', 'address', 'number', 'alternative_number',
            'landline_number', 'cost_for_two', 'delivery_time', 'pure_veg',
            'serves_alcohol', 'wheelchair_accessible', 'cash_on_delivery',
            'terms_and_conditions', 'closing_message',
            'total_tables', 'active_orders_count'
        ]

    def get_total_tables(self, obj):
        try:
            return obj.tablebooking_set.aggregate(
                total=Sum('no_of_tables')
            )['total'] or 0
        except:
            return 0

    def get_active_orders_count(self, obj):
        try:
            return obj.order_set.filter(Paid=False).count()
        except:
            return 0

class ItemListSerializer(serializers.ModelSerializer):
    """List view with cuisine and category names"""
    cuisine_name = serializers.CharField(source='cuisine.name', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    restaurant_name = serializers.CharField(source='restaurant.restaurant_name', read_only=True)

    class Meta:
        model = Item
        fields = [
            'id', 'item_name', 'description', 'price', 'item_type',
            'cuisine_name', 'category_name', 'restaurant_name'
        ]

