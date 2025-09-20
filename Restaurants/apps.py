from django.apps import AppConfig


class RestaurantsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'Restaurants'

    def ready(self):
        import Restaurants.models  # noqa
