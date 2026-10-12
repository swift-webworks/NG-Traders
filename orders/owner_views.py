"""Owner / staff screens (custom dashboard). Catalogue editing itself uses Django Admin."""
import functools
import logging

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Max, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from catalogue import importer
from catalogue.models import ImportBatch

from . import services
from .models import Order, ShopSettings

log = logging.getLogger(__name__)

FILTERS = {
    "new": ("New", Q(status=Order.PENDING)),
    "active": ("In progress", Q(status__in=[Order.ACCEPTED, Order.PREPARING, Order.READY, Order.OUT_FOR_DELIVERY])),
    "done": ("Closed", Q(status__in=[Order.COMPLETED, Order.REJECTED, Order.CANCELLED])),
    "all": ("All", Q()),
}


def owner_required(perm):
    """Staff login + a specific permission. Anonymous -> login page; logged in without permission -> 403."""
    def decorator(view):
        @functools.wraps(view)
        def wrapper(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not (user.is_active and user.is_staff and user.has_perm(perm)):
                return render(request, "owner/forbidden.html", status=403)
            return view(request, *args, **kwargs)
        return wrapper
    return decorator


@owner_required("orders.manage_orders")
def dashboard(request):
    current = request.GET.get("f", "new")
    if current not in FILTERS:
        current = "new"
    qs = Order.objects.filter(FILTERS[current][1]).prefetch_related("items")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(order_number__icontains=q) | Q(customer_phone__icontains=q) | Q(customer_name__icontains=q))
    counts = Order.objects.aggregate(
        new=Count("id", filter=FILTERS["new"][1]), active=Count("id", filter=FILTERS["active"][1]),
        awaiting=Count("id", filter=Q(payment_status=Order.PAY_AWAITING) & ~Q(status__in=[Order.REJECTED, Order.CANCELLED])),
        refunds=Count("id", filter=Q(status__in=[Order.REJECTED, Order.CANCELLED], payment_status=Order.PAY_PAID)),
        latest=Max("id"))
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    tabs = [(key, label, counts.get(key)) for key, (label, _) in FILTERS.items()]
    return render(request, "owner/dashboard.html", {
        "page": page, "tabs": tabs, "current": current, "q": q, "counts": counts})


@require_GET
@owner_required("orders.manage_orders")
def summary_json(request):
    """Polled every few seconds by the dashboard to announce new orders."""
    agg = Order.objects.aggregate(latest=Max("id"), pending=Count("id", filter=Q(status=Order.PENDING)),
                                  awaiting=Count("id", filter=Q(payment_status=Order.PAY_AWAITING)))
    return JsonResponse({"latest_id": agg["latest"] or 0, "pending": agg["pending"], "awaiting": agg["awaiting"]})


@owner_required("orders.manage_orders")
def order_manage(request, pk):
    order = get_object_or_404(Order.objects.prefetch_related("items", "status_logs", "payment_records"), pk=pk)
    if request.method == "POST":
        return _handle_order_action(request, order)
    status_labels = dict(Order.STATUS_CHOICES)
    next_statuses = [(s, status_labels[s]) for s in services.allowed_next_statuses(order)]
    return render(request, "owner/order_detail.html", {
        "order": order, "next_statuses": next_statuses,
        "can_verify": request.user.has_perm("orders.verify_payments"),
        "needs_reason": {Order.REJECTED, Order.CANCELLED},
    })


def _handle_order_action(request, order):
    action = request.POST.get("action")
    note = request.POST.get("note", "")
    try:
        if action == "status":
            new_status = request.POST.get("status")
            services.change_status(order.pk, new_status, request.user, note)
            messages.success(request, "Order status updated.")
        elif action in ("verify_upi", "cash", "reject_payment", "refund"):
            if not request.user.has_perm("orders.verify_payments"):
                return render(request, "owner/forbidden.html", status=403)
            if action == "verify_upi":
                services.verify_upi_payment(order.pk, request.user, request.POST.get("reference", ""), note)
                messages.success(request, "UPI payment recorded as PAID.")
            elif action == "cash":
                services.collect_cash(order.pk, request.user, note)
                messages.success(request, "Cash collection recorded. Payment marked PAID.")
            elif action == "reject_payment":
                services.reject_payment(order.pk, request.user, note)
                messages.success(request, "Payment marked as rejected.")
            else:
                services.confirm_refund(order.pk, request.user, request.POST.get("reference", ""), note)
                messages.success(request, "Refund recorded.")
        else:
            messages.error(request, "Unknown action.")
    except services.TransitionError as exc:
        messages.error(request, str(exc))
    except Order.DoesNotExist:
        messages.error(request, "Order not found.")
    return redirect("owner_order", pk=order.pk)


@owner_required("orders.manage_orders")
def print_bill(request, pk):
    """Dedicated A4 print layout. Printing never changes any status."""
    order = get_object_or_404(Order.objects.prefetch_related("items"), pk=pk)
    return render(request, "owner/print_bill.html", {"order": order, "shop": ShopSettings.load(),
                                                     "printed_at": timezone.localtime()})


# ------------------------------------------------------------------ catalogue import

@require_http_methods(["GET", "POST"])
@owner_required("catalogue.change_product")
def import_upload(request):
    if request.method == "POST":
        upload = request.FILES.get("file")
        if not upload:
            messages.error(request, "Please choose a file.")
        else:
            try:
                rows, columns = importer.read_table(upload, upload.name)
                clean, summary = importer.build_preview(rows, columns)
            except importer.ImportFileError as exc:
                messages.error(request, str(exc))
            else:
                batch = ImportBatch.objects.create(filename=upload.name[:255], rows=clean, summary=summary,
                                                   created_by=request.user)
                return redirect("owner_import_preview", pk=batch.pk)
    recent = ImportBatch.objects.all()[:5]
    return render(request, "owner/import_upload.html", {"recent": recent})


@require_http_methods(["GET", "POST"])
@owner_required("catalogue.change_product")
def import_preview(request, pk):
    batch = get_object_or_404(ImportBatch, pk=pk)
    if request.method == "POST":
        if batch.status != "PREVIEW":
            messages.error(request, "This import was already processed.")
            return redirect("owner_import_preview", pk=pk)
        if request.POST.get("action") == "discard":
            batch.status = "DISCARDED"
            batch.save(update_fields=["status"])
            messages.info(request, "Import discarded. Nothing was changed.")
            return redirect("owner_import")
        try:
            with transaction.atomic():
                batch = ImportBatch.objects.select_for_update().get(pk=pk)
                if batch.status != "PREVIEW":
                    raise ValueError("already processed")
                report = importer.apply_rows(batch.rows, request.user)
                batch.status = "APPLIED"
                batch.applied_at = timezone.now()
                batch.summary = {**batch.summary, "report": report}
                batch.save(update_fields=["status", "applied_at", "summary"])
            messages.success(request, f"Import finished: {report['created']} added, {report['updated']} updated, "
                                      f"{report['skipped_errors']} skipped because of errors.")
        except Exception:
            log.exception("catalogue import failed")
            messages.error(request, "The import failed and nothing was changed. Please check the file and try again.")
        return redirect("owner_import_preview", pk=pk)
    return render(request, "owner/import_preview.html", {"batch": batch, "rows": batch.rows[:500],
                                                         "truncated": len(batch.rows) > 500})
