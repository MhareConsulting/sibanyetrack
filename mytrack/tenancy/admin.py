from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Depot, Organisation, User, UserDepotAccess


@admin.register(Depot)
class DepotAdmin(admin.ModelAdmin):
    list_display = ("name", "organisation", "is_active", "open_time", "close_time")
    list_filter = ("organisation", "is_active")
    search_fields = ("name", "address")


@admin.register(UserDepotAccess)
class UserDepotAccessAdmin(admin.ModelAdmin):
    list_display = ("user", "depot")
    list_filter = ("depot",)
    raw_id_fields = ("user", "depot")


class DepotAccessInline(admin.TabularInline):
    model = UserDepotAccess
    extra = 1
    raw_id_fields = ("depot",)


class MyUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("myTrack", {"fields": ("organisation", "role")}),
    )
    inlines = [DepotAccessInline]


admin.site.register(Organisation)
admin.site.register(User, MyUserAdmin)
