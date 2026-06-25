from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from datetime import datetime

from mytrack.intelligence.views import _depot_context, _vehicle_qs
from mytrack.vehicles.models import Vehicle

from .exports import export_csv_response, export_pdf_response, export_xlsx_response
from .forms import CustomReportBuilderForm
from .models import (
    CustomReportDefinition, CustomReportDomain, CustomReportRun,
    ReportSchedule, ReportScheduleFrequency, SavedReportTemplate,
)
from .services import execute_custom_report, run_common_report
from .tasks import run_custom_report_job


def _ensure_reporting_enabled():
    if not getattr(settings, "REPORTING_FEATURE_ENABLED", True):
        raise Http404("Reporting is disabled.")


PREVIEW_LIMIT = 250
EXPORT_LIMIT = 5000
MAX_EXPORT_DAYS_WITHOUT_VEHICLE = 7


def _export_or_none(report_name, rows, export_format, metadata=None):
    export_format = (export_format or "").lower()
    if export_format == "csv":
        return export_csv_response(report_name, rows, metadata=metadata)
    if export_format == "pdf":
        return export_pdf_response(report_name, report_name.replace("-", " ").title(), rows, metadata=metadata)
    if export_format == "xlsx":
        return export_xlsx_response(report_name, rows, metadata=metadata)
    return None


def _build_export_metadata(request, org, active_depot, domain):
    vehicle_label = "All Vehicles"
    vehicle_id = request.GET.get("vehicle")
    if vehicle_id:
        vehicle = Vehicle.objects.filter(pk=vehicle_id, organisation=org).only("registration").first()
        if vehicle:
            vehicle_label = vehicle.registration
    current_tz = timezone.get_current_timezone()
    generated_at = timezone.localtime(timezone.now(), current_tz).strftime("%d-%m-%Y %H:%M")
    date_from = request.GET.get("date_from") or "-"
    date_to = request.GET.get("date_to") or "-"
    return {
        "title": f"{domain.title()} Report",
        "organisation": org.name,
        "depot": active_depot.name if active_depot else "All Depots",
        "vehicle": vehicle_label,
        "date_range": f"{date_from} to {date_to}",
        "generated_at": generated_at,
    }


def _display_value(value):
    if hasattr(value, "strftime"):
        try:
            local_dt = timezone.localtime(value, timezone.get_current_timezone())
            return local_dt.strftime("%d-%m-%Y %H:%M")
        except Exception:  # noqa: BLE001
            return value
    return value


def _parse_iso_date_safe(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _custom_export_guard_violation(definition):
    filters = definition.filters or {}
    date_from = _parse_iso_date_safe(filters.get("date_from"))
    date_to = _parse_iso_date_safe(filters.get("date_to"))
    vehicle = filters.get("vehicle")
    if not date_from or not date_to:
        return "Custom report must include date_from and date_to filters before export or run."
    if date_from > date_to:
        date_from, date_to = date_to, date_from
    date_window_days = (date_to - date_from).days + 1
    if date_window_days > MAX_EXPORT_DAYS_WITHOUT_VEHICLE and not vehicle:
        return f"Vehicle selection is required for custom report exports/runs longer than {MAX_EXPORT_DAYS_WITHOUT_VEHICLE} days."
    return ""


def _prepare_rows_for_display(rows):
    return [{key: _display_value(val) for key, val in row.items()} for row in rows]


@login_required
def reporting_home(request):
    _ensure_reporting_enabled()
    org = request.user.organisation
    active_depot, _, _, depot_ctx = _depot_context(request)
    templates = SavedReportTemplate.objects.filter(organisation=org).order_by("name")
    vehicles = _vehicle_qs(org, active_depot).order_by("registration").values_list("id", "registration")
    return render(
        request,
        "reporting/home.html",
        {
            "domains": CustomReportDomain.choices,
            "saved_templates": templates,
            "vehicles_json": list(vehicles),
            **depot_ctx,
        },
    )


@login_required
def save_report_template(request):
    if request.method != "POST":
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(["POST"])
    org = request.user.organisation
    name = request.POST.get("template_name", "").strip()
    domain = request.POST.get("domain", "")
    config_keys = ["columns", "metrics", "group_by", "filters", "sort_by"]
    config = {k: request.POST.getlist(k) if k != "filters" else dict(request.POST) for k in config_keys}
    config = {k: request.POST.getlist(k) for k in ["columns", "metrics", "group_by", "sort_by"]}
    config["filters"] = {k: v for k, v in request.POST.items()
                         if k not in ("csrfmiddlewaretoken", "template_name", "domain", "columns", "metrics", "group_by", "sort_by")}
    if name and domain in dict(CustomReportDomain.choices):
        SavedReportTemplate.objects.update_or_create(
            organisation=org,
            name=name,
            defaults={"domain": domain, "config": config, "created_by": request.user},
        )
        messages.success(request, f"Template '{name}' saved.")
    return redirect("reporting-home")


@login_required
def load_report_template(request, pk):
    org = request.user.organisation
    tpl = get_object_or_404(SavedReportTemplate, pk=pk, organisation=org)
    import json
    from urllib.parse import urlencode
    cfg = tpl.config
    params = {}
    for k, v in cfg.items():
        if isinstance(v, list):
            for item in v:
                params.setdefault(k, []).append(item)
        elif isinstance(v, dict):
            for dk, dv in v.items():
                params[dk] = dv
        else:
            params[k] = v
    params["domain"] = tpl.domain
    flat = []
    for k, v in params.items():
        if isinstance(v, list):
            for item in v:
                flat.append((k, item))
        else:
            flat.append((k, v))
    return redirect(f"{request.build_absolute_uri('/reporting/custom/')}?{urlencode(flat)}")


@login_required
def delete_report_template(request, pk):
    if request.method != "POST":
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(["POST"])
    org = request.user.organisation
    tpl = get_object_or_404(SavedReportTemplate, pk=pk, organisation=org)
    name = tpl.name
    tpl.delete()
    messages.success(request, f"Template '{name}' deleted.")
    return redirect("reporting-home")


@login_required
def report_schedule_list(request):
    org = request.user.organisation
    _, _, _, depot_ctx = _depot_context(request)
    schedules = ReportSchedule.objects.filter(organisation=org).select_related("template")
    templates = SavedReportTemplate.objects.filter(organisation=org).order_by("name")
    return render(request, "reporting/schedules.html", {
        "schedules": schedules,
        "templates": templates,
        "frequencies": ReportScheduleFrequency.choices,
        **depot_ctx,
    })


@login_required
def report_schedule_create(request):
    if request.method != "POST":
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(["POST"])
    org = request.user.organisation
    template_id = request.POST.get("template")
    frequency = request.POST.get("frequency")
    recipients = request.POST.get("recipients", "").strip()
    tpl = get_object_or_404(SavedReportTemplate, pk=template_id, organisation=org)
    if frequency in dict(ReportScheduleFrequency.choices) and recipients:
        from django.utils import timezone as tz
        ReportSchedule.objects.create(
            organisation=org,
            template=tpl,
            frequency=frequency,
            recipients=recipients,
            next_run_at=tz.now(),
        )
        messages.success(request, f"Schedule created for '{tpl.name}'.")
    return redirect("reporting-schedules")


@login_required
def report_schedule_delete(request, pk):
    if request.method != "POST":
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(["POST"])
    org = request.user.organisation
    sched = get_object_or_404(ReportSchedule, pk=pk, organisation=org)
    sched.delete()
    messages.success(request, "Schedule deleted.")
    return redirect("reporting-schedules")


@login_required
def common_report(request, domain):
    _ensure_reporting_enabled()
    org = request.user.organisation
    active_depot, _, _, depot_ctx = _depot_context(request)
    if domain not in dict(CustomReportDomain.choices):
        raise Http404("Unknown report domain.")

    preview_requested = request.GET.get("preview") == "1"
    export_requested = bool(request.GET.get("export"))
    vehicle_selected = bool(request.GET.get("vehicle"))
    date_from_selected = bool(request.GET.get("date_from"))
    date_to_selected = bool(request.GET.get("date_to"))
    can_query = preview_requested or export_requested
    export_block_reason = ""

    result = run_common_report(domain, org, depot=active_depot, params=request.GET)
    rows_qs = result["rows"]
    rows_for_export = []
    rows_for_preview = []
    total_rows = 0
    date_window_days = None
    if can_query:
        # Require a specific date range for large-fleet safety.
        if not (date_from_selected and date_to_selected):
            messages.warning(request, "Please choose Date From and Date To before loading or exporting.")
        else:
            try:
                date_from_obj = datetime.strptime(request.GET.get("date_from"), "%Y-%m-%d").date()
                date_to_obj = datetime.strptime(request.GET.get("date_to"), "%Y-%m-%d").date()
                if date_from_obj > date_to_obj:
                    date_from_obj, date_to_obj = date_to_obj, date_from_obj
                date_window_days = (date_to_obj - date_from_obj).days + 1
            except (TypeError, ValueError):
                date_window_days = None

            if export_requested and date_window_days and date_window_days > MAX_EXPORT_DAYS_WITHOUT_VEHICLE and not vehicle_selected:
                export_block_reason = (
                    f"Vehicle selection is required for exports longer than {MAX_EXPORT_DAYS_WITHOUT_VEHICLE} days."
                )
            else:
                total_rows = rows_qs.count()
                rows_for_export = list(rows_qs.values()[:EXPORT_LIMIT])
                rows_for_preview = _prepare_rows_for_display(rows_for_export[:PREVIEW_LIMIT])

    export_response = None
    if export_requested and rows_for_export:
        metadata = _build_export_metadata(request, org, active_depot, domain)
        export_response = _export_or_none(f"{domain}-report", rows_for_export, request.GET.get("export"), metadata=metadata)
    if export_response:
        return export_response

    page = Paginator(rows_for_preview, 50).get_page(request.GET.get("page", 1))
    vehicles = _vehicle_qs(org, active_depot).order_by("registration")
    selected_vehicle_label = "All Vehicles"
    if request.GET.get("vehicle"):
        selected_vehicle = vehicles.filter(pk=request.GET.get("vehicle")).first()
        if selected_vehicle:
            selected_vehicle_label = selected_vehicle.registration
    return render(
        request,
        "reporting/common_report.html",
        {
            "domain": domain,
            "summary": result["summary"],
            "page_obj": page,
            "vehicles": vehicles,
            "preview_requested": preview_requested,
            "query_ready": date_from_selected and date_to_selected,
            "total_rows": total_rows,
            "preview_limit": PREVIEW_LIMIT,
            "export_limit": EXPORT_LIMIT,
            "max_export_days_without_vehicle": MAX_EXPORT_DAYS_WITHOUT_VEHICLE,
            "date_window_days": date_window_days,
            "selected_vehicle_label": selected_vehicle_label,
            "export_block_reason": export_block_reason,
            **depot_ctx,
        },
    )


@login_required
def custom_builder(request):
    _ensure_reporting_enabled()
    org = request.user.organisation
    active_depot, _, _, depot_ctx = _depot_context(request)
    editing_id = request.GET.get("edit")
    instance = None
    if editing_id:
        instance = get_object_or_404(CustomReportDefinition, pk=editing_id, organisation=org)

    if request.method == "POST":
        form = CustomReportBuilderForm(request.POST, instance=instance)
        if form.is_valid():
            report = form.save(commit=False)
            report.organisation = org
            report.owner = request.user
            report.save()
            messages.success(request, "Custom report definition saved.")
            return redirect("reporting-custom-builder")
    else:
        form = CustomReportBuilderForm(instance=instance)

    definitions = []
    runs = []
    try:
        definitions = list(
            CustomReportDefinition.objects.filter(organisation=org).order_by("name")
        )
        runs = list(
            CustomReportRun.objects.filter(definition__organisation=org).select_related("definition")[:30]
        )
    except Exception as exc:  # noqa: BLE001
        messages.error(request, f"Could not load saved report definitions: {exc}")

    preview_rows = []
    preview_report_id = request.GET.get("preview")
    if preview_report_id:
        definition = get_object_or_404(CustomReportDefinition, pk=preview_report_id, organisation=org)
        try:
            preview_rows = _prepare_rows_for_display(execute_custom_report(definition, depot=active_depot)[:100])
        except Exception as exc:  # noqa: BLE001
            messages.error(request, f"Preview failed: {exc}")

    return render(
        request,
        "reporting/custom_builder.html",
        {
            "form": form,
            "definitions": definitions,
            "runs": runs,
            "preview_rows": preview_rows,
            **depot_ctx,
        },
    )


@login_required
def run_custom_report(request, report_id):
    _ensure_reporting_enabled()
    org = request.user.organisation
    definition = get_object_or_404(CustomReportDefinition, pk=report_id, organisation=org)
    violation = _custom_export_guard_violation(definition)
    if violation:
        messages.warning(request, violation)
        return redirect("reporting-custom-builder")
    run = CustomReportRun.objects.create(
        definition=definition,
        requested_by=request.user,
        format=request.POST.get("format", "csv"),
    )
    try:
        run_custom_report_job(run.id)
        messages.success(request, f"Report '{definition.name}' executed.")
    except Exception as exc:  # noqa: BLE001
        messages.error(request, f"Report execution failed: {exc}")
    return redirect("reporting-custom-builder")


@login_required
def export_custom_report(request, run_id):
    _ensure_reporting_enabled()
    run = get_object_or_404(
        CustomReportRun.objects.select_related("definition", "definition__organisation"),
        pk=run_id,
        definition__organisation=request.user.organisation,
    )
    violation = _custom_export_guard_violation(run.definition)
    if violation:
        messages.warning(request, violation)
        return redirect("reporting-custom-builder")
    rows = execute_custom_report(run.definition)
    fmt = request.GET.get("format", run.format or "csv")
    metadata = {
        "title": run.definition.name,
        "organisation": run.definition.organisation.name,
        "depot": "Scoped by active selection at run time",
        "vehicle": "As per report filters",
        "date_range": str((run.definition.filters or {}).get("date_from", "-"))
        + " to "
        + str((run.definition.filters or {}).get("date_to", "-")),
        "generated_at": timezone.localtime(timezone.now(), timezone.get_current_timezone()).strftime("%d-%m-%Y %H:%M"),
    }
    response = _export_or_none(run.definition.name.lower().replace(" ", "-"), rows, fmt, metadata=metadata)
    if not response:
        raise Http404("Unsupported export format.")
    return response
