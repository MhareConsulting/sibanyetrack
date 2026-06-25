from django.urls import path

from . import api, views

urlpatterns = [
    # HTML views
    path('',                                            views.vehicle_list,            name='fuel-vehicle-list'),
    path('events/',                                     views.event_list,              name='fuel-event-list'),
    path('events/<int:event_id>/acknowledge/',          views.acknowledge_event,       name='fuel-event-acknowledge'),
    path('vehicle/<int:vehicle_id>/',                   views.vehicle_fuel_detail,     name='fuel-vehicle-detail'),
    path('vehicle/<int:vehicle_id>/calibration/',       views.calibration_editor,      name='fuel-calibration-editor'),
    path('vehicle/<int:vehicle_id>/calibration/import/',         views.calibration_import_csv,        name='fuel-calibration-import'),
    path('vehicle/<int:vehicle_id>/calibration/import/excel/',   views.calibration_import_excel,      name='fuel-calibration-import-excel'),
    path('vehicle/<int:vehicle_id>/calibration/import/poly/',    views.calibration_import_polynomial, name='fuel-calibration-import-poly'),

    path('prices/',                                       views.price_history,           name='fuel-price-history'),
    path('prices/fetch/',                                 views.fetch_prices_now,        name='fuel-fetch-prices'),
    path('prices/add/',                                   views.price_add,               name='fuel-price-add'),

    # JSON API
    path('api/events/',                                  api.api_events,   name='fuel-api-events'),
    path('api/vehicles/',                                api.api_vehicles, name='fuel-api-vehicles'),
    path('api/vehicles/<int:vehicle_id>/readings/',      api.api_readings, name='fuel-api-readings'),
]
