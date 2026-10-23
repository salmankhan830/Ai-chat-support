from django.urls import path
from . import views

urlpatterns = [
    path('', views.orders_list, name='orders'),
    path('<int:order_id>/', views.order_details, name='order_details'),
]