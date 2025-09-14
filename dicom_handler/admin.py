from django.contrib import admin
from django.apps import apps

# Register your models here.

# Get all models from the dicom_handler app and register them
app_models = apps.get_app_config('dicom_handler').get_models()
for model in app_models:
    admin.site.register(model)
