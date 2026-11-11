from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("integrations/", views.integration_list, name="integration_list"),
    path("new/", views.create, name="create"),
    path("new/terms/", views.accept_terms, name="accept_terms"),
    path("account/", views.account, name="account"),
    path("account/delete/", views.delete_account, name="delete_account"),
    path("account/password/", views.force_password, name="force_password"),
    path("account/invoice/", views.invoice, name="invoice"),
    path("llms.txt", views.llms_txt, name="llms_txt"),
    path("control/", views.admin_dashboard, name="admin_dashboard"),
    path("control/client/new/", views.admin_create_client, name="admin_create_client"),
    path("control/client/<int:pk>/", views.admin_client, name="admin_client"),
    path("control/client/<int:pk>/edit/", views.admin_edit_client, name="admin_edit_client"),
    path("control/client/<int:pk>/delete/", views.admin_delete_client, name="admin_delete_client"),
    path("control/integration/<int:pk>/disable/", views.admin_disable, name="admin_disable"),
    path("control/integration/<int:pk>/delete/", views.admin_delete, name="admin_delete"),
    path("integration/<int:pk>/", views.configure, name="configure"),
    path("integration/<int:pk>/edit/", views.edit_source, name="edit_source"),
    path("integration/<int:pk>/preview/", views.preview, name="preview"),
    path("integration/<int:pk>/result/", views.result, name="result"),
    path("integration/<int:pk>/confirm/", views.confirm, name="confirm"),
    path("integration/<int:pk>/toggle/", views.toggle_integration, name="toggle_integration"),
    path("integration/<int:pk>/schedule/", views.schedule, name="schedule"),
    path("integration/<int:pk>/delete/", views.delete, name="delete"),
]
