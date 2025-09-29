from django.contrib import admin
from django.apps import apps
from django.contrib import admin
from allauth.account.decorators import secure_admin_login

admin.autodiscover()
admin.site.login = secure_admin_login(admin.site.login)
# Register your models here.

# Get all models from the dicom_handler app and register them
app_models = apps.get_app_config('dicom_handler').get_models()
for model in app_models:
    admin.site.register(model)
