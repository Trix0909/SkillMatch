"""Read-only dashboard data, always scoped through the registered ModelAdmin."""

from datetime import datetime
from urllib.parse import urlencode

from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.db.models import Count
from django.db.models.functions import TruncMonth
from django.urls import reverse
from django.utils import timezone

from .models import EmployerProfile, JobPost, JobSeekerProfile, SkillCategory


def model_link(site, request, model, action="changelist"):
    model_admin = site._registry.get(model)
    if model_admin is None or not model_admin.has_module_permission(request):
        return None
    permitted = (
        model_admin.has_add_permission(request)
        if action == "add"
        else model_admin.has_view_or_change_permission(request)
    )
    if not permitted:
        return None
    opts = model._meta
    return reverse(f"{site.name}:{opts.app_label}_{opts.model_name}_{action}")


def visible_queryset(site, request, model):
    if model_link(site, request, model):
        return site._registry[model].get_queryset(request)
    return None


def navigation(site, request):
    items = [{"label": "Overview", "icon": "home", "url": reverse("admin:index")}]
    for label, icon, model in (
        ("Users", "people", get_user_model()),
        ("Job seeker profiles", "document", JobSeekerProfile),
        ("Employer profiles", "building", EmployerProfile),
        ("Job posts", "briefcase", JobPost),
        ("Skill categories", "layers", SkillCategory),
    ):
        url = model_link(site, request, model)
        if url:
            items.append({"label": label, "icon": icon, "url": url})
    items.extend(
        [
            {"label": "Reports", "icon": "chart", "url": reverse("admin:reports")},
            {"label": "Settings", "icon": "settings", "url": reverse("admin:settings")},
        ]
    )
    for item in items:
        item["active"] = (
            request.path == item["url"]
            if item["label"] == "Overview"
            else request.path.startswith(item["url"])
        )
    return items


def monthly_series(queryset, field, months):
    """Count existing records before each month end, using local month boundaries."""
    if queryset is None:
        return None
    now = timezone.now()
    totals = {
        (row["month"].year, row["month"].month): row["total"]
        for row in queryset.filter(**{f"{field}__lte": now})
        .order_by()
        .annotate(month=TruncMonth(field))
        .values("month")
        .annotate(total=Count("pk"))
    }
    cumulative = sum(n for key, n in totals.items() if key < months[0])
    rows = []
    for year, month in months:
        new = totals.get((year, month), 0)
        cumulative += new
        rows.append(
            {
                "label": datetime(year, month, 1).strftime("%b %Y"),
                "short": datetime(year, month, 1).strftime("%b"),
                "new": new,
                "total": cumulative,
            }
        )
    return rows


def dashboard_data(site, request):
    user_model = get_user_model()
    metrics = []
    for label, icon, model, note in (
        ("Total users", "people", user_model, "Registered user accounts"),
        ("Job seekers", "person", JobSeekerProfile, "Distinct users with seeker profiles"),
        ("Employers", "building", EmployerProfile, "Distinct users with employer profiles"),
        ("Job posts", "briefcase", JobPost, "All posts · open and closed"),
    ):
        qs = visible_queryset(site, request, model)
        count = (
            None
            if qs is None
            else (
                qs.values("user_id").distinct().count()
                if model in (JobSeekerProfile, EmployerProfile)
                else qs.count()
            )
        )
        metrics.append(
            {
                "label": label,
                "icon": icon,
                "value": count,
                "note": note if qs is not None else "View permission required",
            }
        )
    period = 6 if request.GET.get("period") == "6" else 12
    today = timezone.localdate()
    end = today.year * 12 + today.month - 1
    months = [divmod(index, 12) for index in range(end - period + 1, end + 1)]
    months = [(year, month + 1) for year, month in months]
    users = monthly_series(visible_queryset(site, request, user_model), "date_joined", months)
    jobs = monthly_series(visible_queryset(site, request, JobPost), "created_at", months)
    chart = None
    if users is not None:
        # A small server-rendered SVG keeps analytics local and works without JavaScript.
        maximum = max(4, max(row["total"] for row in users))
        step = max(1, (maximum + 3) // 4)
        ceiling = step * 4
        points = []
        for index, row in enumerate(users):
            x = 52 + index * 624 / (period - 1)
            y = 194 - row["total"] / ceiling * 176
            points.append({**row, "x": round(x, 2), "y": round(y, 2)})
        line = " ".join(f"{point['x']},{point['y']}" for point in points)
        chart = {
            "points": points,
            "line": line,
            "area": f"52,194 {line} 676,194",
            "ticks": [{"y": 194 - i * 44, "value": i * step} for i in range(5)],
        }
    actions = []
    for label, icon, description, model, action in (
        ("Add new user", "person-add", "Create a user account.", user_model, "add"),
        ("Add job post", "briefcase", "Create a new job opportunity.", JobPost, "add"),
        ("Manage skills", "layers", "Add or update skill categories.", SkillCategory, "changelist"),
    ):
        url = model_link(site, request, model, action)
        if url:
            actions.append({"label": label, "icon": icon, "description": description, "url": url})
    actions.append(
        {
            "label": "View reports",
            "icon": "chart",
            "description": "Explore recorded platform growth.",
            "url": reverse("admin:reports"),
        }
    )
    report_rows = []
    for index, (year, month) in enumerate(months):
        report_rows.append(
            {
                "label": datetime(year, month, 1).strftime("%b %Y"),
                "users": users[index]["new"] if users is not None else None,
                "jobs": jobs[index]["new"] if jobs is not None else None,
            }
        )
    return {
        "metrics": metrics,
        "growth_chart": chart,
        "period": period,
        "quick_actions": actions,
        "report_rows": report_rows,
        "recent_activity": recent_activity(site, request),
    }


def recent_activity(site, request):
    """Match Django's personal admin log, omitting objects no longer visible."""
    events = []
    for entry in LogEntry.objects.filter(user=request.user).select_related("content_type")[:100]:
        model = entry.content_type.model_class() if entry.content_type else None
        if model is None or not model_link(site, request, model):
            continue
        model_admin = site._registry[model]
        url = None
        if entry.is_deletion():
            if not request.user.is_superuser:
                continue
        else:
            obj = model_admin.get_object(request, entry.object_id)
            if obj is None or not model_admin.has_view_or_change_permission(request, obj):
                continue
            url = entry.get_admin_url()
        events.append(
            {
                "object": entry.object_repr,
                "model": str(model._meta.verbose_name),
                "action": entry.get_action_flag_display(),
                "time": entry.action_time,
                "url": url,
                "deleted": entry.is_deletion(),
            }
        )
        if len(events) == 5:
            break
    return events


def search_destinations(site, request, query):
    destinations = []
    for app in site.get_app_list(request):
        for item in app["models"]:
            if not item.get("admin_url"):
                continue
            model_admin = site._registry[item["model"]]
            if query and model_admin.get_search_fields(request):
                destinations.append(
                    {
                        "label": f"Search {item['name'].lower()}",
                        "url": item["admin_url"] + "?" + urlencode({"q": query}),
                        "description": "Open matching records in Django admin",
                    }
                )
            elif not query or query.casefold() in item["name"].casefold():
                destinations.append(
                    {
                        "label": item["name"],
                        "url": item["admin_url"],
                        "description": "Open administration page",
                    }
                )
    for label, name in (("Reports", "reports"), ("Settings", "settings")):
        if not query or query.casefold() in label.casefold():
            destinations.append(
                {
                    "label": label,
                    "url": reverse(f"admin:{name}"),
                    "description": "Open administration page",
                }
            )
    return destinations
