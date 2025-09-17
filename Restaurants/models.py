from django.db import models
from django.utils import timezone
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import transaction
from django.core.validators import MinValueValidator


# ---------------- Base (soft delete + audit) ----------------
class ActiveManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class DeletedManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=True)


class BaseModel(models.Model):
    id = models.BigAutoField(primary_key=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    created_by_id = models.BigIntegerField(null=True, blank=True)
    updated_by_id = models.BigIntegerField(null=True, blank=True)

    is_active = models.BooleanField(default=True)

    # soft-delete
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by_id = models.BigIntegerField(null=True, blank=True)

    objects = ActiveManager()
    deleted_objects = DeletedManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True






# Create your models here.

class Customer(BaseModel):
    user_id = models.BigIntegerField(null=False, blank=False, unique=True)
    username = models.CharField(max_length=150, null=True, blank=True)
    loyalty_points = models.IntegerField(default=0)

    def __str__(self):
        return f"Customer {self.user_id}"

# -------------------- restaurant basic details --------------------
class Restaurant(BaseModel):
    restaurant_name = models.CharField(max_length=100)
    address = models.CharField(max_length=255, blank=False)
    number = models.CharField(max_length=15, blank=False)
    alternative_number = models.CharField(max_length=15, blank=False)
    landline_number = models.CharField(max_length=15, blank=False)
    delivery_time = models.CharField(max_length=100, blank=True)
    serves_alcohol = models.BooleanField(default=False)
    wheelchair_accessible = models.BooleanField(default=False)
    cash_on_delivery = models.BooleanField(default=False)
    pure_veg = models.BooleanField(default=False)
    terms_and_conditions = models.TextField(blank=True)
    closing_message = models.TextField(blank=True)
    cost_for_two = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    disclaimer = models.TextField(blank=True)

    def __str__(self):
        return self.restaurant_name

# ------------------- restaurant details done -------------------
class RestaurantSchedule(BaseModel):
    DAY_CHOICES = [
        (1, "Monday"),
        (2, "Tuesday"),
        (3, "Wednesday"),
        (4, "Thursday"),
        (5, "Friday"),
        (6, "Saturday"),
        (7, "Sunday"),
    ]

    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name="schedules")
    day = models.PositiveSmallIntegerField(choices=DAY_CHOICES)
    operational = models.BooleanField(default=False)

    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    break_start_time = models.TimeField(null=True, blank=True)
    break_end_time = models.TimeField(null=True, blank=True)

    booking_allowed = models.BooleanField(default=False)
    order_allowed = models.BooleanField(default=False)
    last_order_time = models.TimeField(null=True, blank=True)

    class Meta:
        unique_together = ("restaurant", "day")
        indexes = [
            models.Index(fields=["restaurant", "day"]),
        ]

    def __str__(self):
        return f"{self.restaurant.name} - {self.get_day_display()}"


# ------------------- Blocked Days done  -------------------

class Blocked_Day(BaseModel):
    BLOCK_TYPE_CHOICES = [
        ('order', 'Order'),
        ('booking', 'Booking'),
    ]

    restaurant = models.ForeignKey("RestaurantSchedule", on_delete=models.CASCADE, related_name="blocked_days")
    block_type = models.CharField(max_length=10, choices=BLOCK_TYPE_CHOICES) 
    start_date = models.DateField() # example: 2023-01-01
    end_date = models.DateField()

    def __str__(self):
        return f"{self.restaurant.name} - {self.block_type} Blocked from {self.start_date} to {self.end_date}"

# ------------------- table booking - done --------------
class TableBooking(BaseModel):
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE)
    no_of_tables = models.IntegerField(default=0)
    min_people = models.IntegerField(default=1)
    max_people = models.IntegerField(default=10)
    can_cancel_before = models.TimeField(null=True, blank=True) # example: 00:12
    booking_not_available_text = models.TextField(blank=True)
    no_of_floors = models.IntegerField(default=1)

# ------------------- order configure - done --------------
class OrderConfigure(BaseModel):
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE)
    GST_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0) # example: 5.00
    delivery_charge = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    service_charge = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    minimum_order = models.IntegerField(default=0)
    order_not_available_text = models.TextField(blank=True)

# ------------------- attachments -------------------
class RestoCoverImage(BaseModel):
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name="cover_images")
    image = models.ImageField(upload_to='resto_cover_images/')
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"Cover Image for {self.restaurant.restaurant_name}"

class RestoMenuImage(BaseModel):
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name="menu_images")
    image = models.ImageField(upload_to='resto_menu_images/')

    def __str__(self):
        return f"Menu Image for {self.restaurant.restaurant_name}"

class RestoGalleryImage(BaseModel):
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name="gallery_images")
    image = models.ImageField(upload_to='resto_gallery_images/')

    def __str__(self):
        return f"Gallery Image for {self.restaurant.restaurant_name}"

class RestoOtherFile(BaseModel):
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name="other_files")
    file = models.FileField(upload_to='resto_other_files/')

    def __str__(self):
        return f"Other File for {self.restaurant.restaurant_name}"



# ------------------- Menu Management done  -------------------

# ------------------- master data done -------------------
class MasterCuisine(BaseModel):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class MasterItem(BaseModel):
    master_cuisine = models.ForeignKey(
        MasterCuisine, on_delete=models.CASCADE, related_name="master_items"
    )
    name = models.CharField(max_length=100)
    item_type = models.CharField(max_length=50, blank=False, null=False) # veg, non-veg, egg

    def __str__(self):
        return f"{self.name} ({self.master_cuisine.name})"


# ------------------- Cuisine done-------------------
class Cuisine(BaseModel):
    name = models.CharField(max_length=100)
    restaurant = models.ForeignKey(
        "Restaurant", on_delete=models.CASCADE, related_name="cuisines"
    )
    master_cuisine = models.ForeignKey(
        MasterCuisine, on_delete=models.CASCADE, related_name="restaurant_cuisines"
    )

    class Meta:
        unique_together = ("restaurant","name")

    def __str__(self):
        return f"{self.name} - {self.restaurant.name}"


# ------------------- Category done-------------------
class Category(BaseModel):
    cuisine = models.ForeignKey(
        Cuisine, on_delete=models.SET_NULL,
        related_name="categories", null=True, blank=True
    )
    restaurant = models.ForeignKey(
        "Restaurant", on_delete=models.SET_NULL,
        related_name="categories", null=True
    )
    parent = models.ForeignKey(
        "self", null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="subcategories"
    )
    name = models.CharField(max_length=100)
    timing = models.CharField(max_length=50, blank=True, null=True)

    def __str__(self):
        return self.name


# ------------------- Item done -------------------
class Item(BaseModel):
    restaurant = models.ForeignKey(
        "Restaurant", on_delete=models.CASCADE, related_name="items"
    )
    cuisine = models.ForeignKey(
        Cuisine, on_delete=models.CASCADE, related_name="items"
    )
    # optional but recommended to keep mapping with MasterItem
    master_item = models.ForeignKey(
        MasterItem, on_delete=models.SET_NULL, null=True, blank=True, related_name="restaurant_items"
    )
    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, blank=True, related_name="items"
    )
    item_name = models.CharField(max_length=100)
    master_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    description = models.TextField(blank=True, null=True)
    item_type = models.CharField(max_length=50, blank=False, null=False) # veg, non-veg, egg

    class Meta:
        unique_together = ("restaurant", "item_name")

    def __str__(self):
        return f"{self.item_name} ({self.restaurant.name})"


# ------------------- ingredients done -------------------
class Ingredient(BaseModel):
    name = models.CharField(max_length=100)
    def __str__(self):
        return self.name

# ------------------- item ingredients done-------------------
class QtyIngredient(BaseModel):
    item = models.ForeignKey(Item, on_delete=models.CASCADE)
    ingredient = models.ForeignKey(Ingredient, on_delete=models.CASCADE)
    qty = models.DecimalField(max_digits=10, decimal_places=2)
    qty_type = models.CharField(max_length=20, choices=[('grams', 'Grams'), ('ml', 'Milliliters'), ('pieces', 'Pieces')])

    def __str__(self):
        return f"{self.qty} {self.qty_type} of {self.ingredient.name} for {self.item.item_name}"

# ------------------- Suppliers / Warehouses / UOM done -------------------
class Supplier(BaseModel):
    name = models.CharField(max_length=255)
    contact_info = models.TextField(blank=True)

    def __str__(self):
        return self.name


class Warehouse(BaseModel):
    name = models.CharField(max_length=255)
    restaurant = models.OneToOneField("Restaurant", on_delete=models.CASCADE, null=True, blank=True, related_name="warehouse")

    def __str__(self):
        return f"{self.name} ({self.restaurant.name})" if self.restaurant else self.name


UOM_CHOICES = [
    ('grams', 'Grams'),
    ('kg', 'Kilograms'),
    ('ml', 'Milliliters'),
    ('ltr', 'Liters'),
    ('pieces', 'Pieces'),
    ('unit', 'Unit'),
]


# ------------------- Inventory Item (SKU) done -------------------
class InventoryItem(BaseModel):
    name = models.CharField(max_length=255)
    sku = models.CharField(max_length=100, unique=True) # Stock Keeping Unit shortly barcode
    description = models.TextField(blank=True)
    uom = models.CharField(max_length=20, choices=UOM_CHOICES, default='unit') # unit of measure for stock
    current_qty = models.DecimalField(max_digits=18, decimal_places=4, default=0, validators=[MinValueValidator(0)])
    last_updated = models.DateTimeField(auto_now=True)

    # control fields
    reorder_point = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    safety_stock = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    #lead_time_days = models.IntegerField(default=0)
    eoq = models.DecimalField(max_digits=18, decimal_places=4, default=0) # Economic Order Quantity
    preferred_supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True)

    # stock management
    #category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True)
    bin_location = models.CharField(max_length=100, blank=True)
    #serialized = models.BooleanField(default=False)
    expiry_date = models.DateField(null=True, blank=True)

    # advanced / analytics
    valuation = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    stock_turnover_rate = models.DecimalField(max_digits=8, decimal_places=4, default=0)
    forecast = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    #ml_model_version = models.CharField(max_length=50, blank=True)
    barcode_status = models.BooleanField(default=False)
    #rfid_tag_id = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return f"{self.sku} - {self.description or 'Item'}"

    def needs_reorder(self):
        return self.current_qty <= self.reorder_point

    def adjust_qty(self, delta):
        """
        Adjust current_qty by delta (positive or negative). Prevent negative unless business allows.
        """
        self.current_qty = max(self.current_qty + delta, 0)
        self.save(update_fields=['current_qty', 'last_updated'])


# ------------------- Inventory Movement / Transfer done-------------------
MOVEMENT_CHOICES = [
    ('IN', 'Stock In'),
    ('OUT', 'Stock Out'),
    ('TRANSFER', 'Transfer'),
]

class InventoryMovement(BaseModel):
    item = models.ForeignKey(InventoryItem, on_delete=models.CASCADE, related_name='movements')
    movement_type = models.CharField(max_length=10, choices=MOVEMENT_CHOICES)
    qty = models.DecimalField(max_digits=18, decimal_places=4, validators=[MinValueValidator(0)])
    uom = models.CharField(max_length=20, choices=UOM_CHOICES, default='unit')
    #from_location = models.ForeignKey(Warehouse, on_delete=models.SET_NULL, null=True, blank=True, related_name='movements_from')
    #to_location = models.ForeignKey(Warehouse, on_delete=models.SET_NULL, null=True, blank=True, related_name='movements_to')
    #transfer_order_number = models.CharField(max_length=100, blank=True)
    #ship_date = models.DateField(null=True, blank=True)
    #receive_date = models.DateField(null=True, blank=True)
    #batch_serial_number = models.CharField(max_length=200, blank=True)
    #inspection_status = models.CharField(max_length=50, blank=True)
    remarks = models.TextField(blank=True)
    #timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.movement_type} {self.qty} {self.uom} - {self.item.sku} @ {self.created_at}"


# -------------------  / Audit / done-------------------

class InventoryAudit(BaseModel):
    action = models.CharField(max_length=100)
    #user_id = models.BigIntegerField(null=True, blank=True)
    item = models.ForeignKey(InventoryItem, on_delete=models.SET_NULL, null=True, blank=True)
    qty_before = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    qty_after = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
   # timestamp = models.DateTimeField(auto_now_add=True)
    #details = models.TextField(blank=True)


# ------------------- Signals: keep InventoryItem.current_qty in sync done-------------------
@receiver(post_save, sender=InventoryMovement)
def _apply_movement_to_item(sender, instance: InventoryMovement, created, **kwargs):
    if not created:
        return
    with transaction.atomic():
        item = instance.item
        if instance.movement_type == 'IN':
            item.adjust_qty(instance.qty)
        elif instance.movement_type == 'OUT':
            item.adjust_qty(-instance.qty)
        elif instance.movement_type == 'TRANSFER':
            # for transfer we do not change global qty; optionally update item.location if to_location provided
            if instance.to_location:
                item.location = instance.to_location
                item.save(update_fields=['location', 'last_updated'])

        # create audit record
        InventoryAudit.objects.create(
            action=f"Movement {instance.movement_type}",
            user_id=None,
            item=item,
            qty_before=None,
            qty_after=item.current_qty,
            details=f"Movement id={instance.id} qty={instance.qty} uom={instance.uom}"
        )

# ------------------- orders -------------------

class Order(BaseModel):
    PAYMENT_MODE_CHOICES = [
        ('cash', 'Cash'),
        ('Due', 'Due'),
        ('card', 'Card'),
        ('Part Payment', 'Part Payment'),
        ('Other', 'Other')
    ]
    ORDER_TYPE_CHOICES = [
        ('dine_in', 'Dine In'),
        ('Pick_Up', 'Pick Up'),
        ('delivery', 'Delivery'),
    ]
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE)
    item_name = models.CharField(max_length=50)
    Qty = models.IntegerField(default=1)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    kot = models.IntegerField(default=1)
    order_time = models.DateTimeField(auto_now_add=True)
    total_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    payment_mode = models.CharField(max_length=20, choices=PAYMENT_MODE_CHOICES)
    order_type = models.CharField(max_length=20, choices=ORDER_TYPE_CHOICES)
    Paid = models.BooleanField(default=False)
    loyalty = models.BooleanField(default=False)
    loyalty_points = models.IntegerField(default=0)