from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from orders import api, owner_views, views
from orders.ratelimit import rate_limit
from voice import views as voice_views

login_view = rate_limit("login", 15, 60, as_json=False)(
    auth_views.LoginView.as_view(template_name="owner/login.html", redirect_authenticated_user=True))

urlpatterns = [
    path("admin/", admin.site.urls),

    # customer pages
    path("", views.home, name="home"),
    path("orders/find/", views.order_lookup, name="order_lookup"),
    path("order/<str:token>/", views.order_detail, name="order_detail"),
    path("order/<str:token>/paid/", views.order_claim_paid, name="order_claim_paid"),

    # customer JSON API
    path("api/parse/", voice_views.parse_view, name="api_parse"),
    path("api/resolve/", voice_views.resolve_view, name="api_resolve"),
    path("api/products/search/", voice_views.search_view, name="api_search"),
    path("api/bill/", api.bill_view, name="api_bill"),
    path("api/order/", api.create_order_view, name="api_order"),
    path("api/order/<str:token>/status/", api.order_status_json, name="api_order_status"),

    # owner
    path("owner/login/", login_view, name="owner_login"),
    path("owner/logout/", auth_views.LogoutView.as_view(), name="owner_logout"),
    path("owner/", owner_views.dashboard, name="owner_dashboard"),
    path("owner/api/summary/", owner_views.summary_json, name="owner_summary"),
    path("owner/orders/<int:pk>/", owner_views.order_manage, name="owner_order"),
    path("owner/orders/<int:pk>/print/", owner_views.print_bill, name="owner_print"),
    path("owner/import/", owner_views.import_upload, name="owner_import"),
    path("owner/import/<int:pk>/", owner_views.import_preview, name="owner_import_preview"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
