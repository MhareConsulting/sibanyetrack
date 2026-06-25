from django.contrib import admin

from .models import CalibrationPoint, FuelEvent, FuelReading, TankCalibration


class CalibrationPointInline(admin.TabularInline):
    model  = CalibrationPoint
    extra  = 3
    fields = ('raw_value', 'litres')


@admin.register(TankCalibration)
class TankCalibrationAdmin(admin.ModelAdmin):
    list_display  = ('vehicle', 'bottom_blind_litres', 'top_blind_litres', 'point_count', 'updated_at')
    list_filter   = ('vehicle__organisation',)
    search_fields = ('vehicle__registration', 'vehicle__label', 'notes')
    inlines       = [CalibrationPointInline]

    @admin.display(description='Points')
    def point_count(self, obj):
        return obj.points.count()


@admin.register(FuelReading)
class FuelReadingAdmin(admin.ModelAdmin):
    list_display = ('vehicle', 'fuel_level_litres', 'raw_sensor_value', 'speed_kmh', 'device_timestamp')
    list_filter  = ('vehicle__organisation',)
    ordering     = ('-device_timestamp',)


@admin.register(FuelEvent)
class FuelEventAdmin(admin.ModelAdmin):
    list_display  = ('vehicle', 'kind', 'delta_litres', 'level_before', 'level_after', 'occurred_at', 'acknowledged', 'notes')
    list_filter   = ('kind', 'acknowledged', 'vehicle__organisation')
    search_fields = ('vehicle__registration', 'vehicle__label', 'driver_name', 'notes')
    ordering      = ('-occurred_at',)
    list_editable = ('acknowledged',)
    readonly_fields = ('created_at',)
