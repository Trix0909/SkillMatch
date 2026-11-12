from django.urls import reverse


def profile_dropdown(user, role):
    """The signed-in identity must not depend on a viewed profile or a bound form."""
    employer = role == "employer"
    profile = getattr(user, "employer_profile" if employer else "seeker_profile", None)
    image = getattr(profile, "logo" if employer else "photo", None)
    name = (
        (getattr(profile, "company_name", "") or "").strip()
        if employer
        else user.get_full_name().strip()
    ) or user.username
    return {
        "name": name,
        "initial": name[0].upper(),
        "image_url": image.url if image else "",
        "role_label": "Employer account" if employer else "Job seeker account",
        "profile_label": "View company profile" if employer else "View profile",
        "profile_icon": "building" if employer else "person",
        "profile_url": reverse("profile_detail", args=[profile.pk])
        if not employer and profile
        else reverse("profile_edit"),
    }


def navigation(request):
    role = ""
    if request.user.is_authenticated:
        account = getattr(request.user, "account", None)
        role = account.active_role if account else ""
    context = {
        "account_role": role,
        "workspace_base": {
            "seeker": "skillmatch/dashboard_base.html",
            "employer": "skillmatch/employer_base.html",
        }.get(role, "base.html"),
    }
    if role in {"seeker", "employer"} and request.user.is_active:
        context["profile_dropdown"] = profile_dropdown(request.user, role)
        from django.db.models import Q

        from .models import Connection, ConnectionActivity, Message

        scope = (
            Q(seeker__user=request.user)
            if role == "seeker"
            else Q(job__employer__user=request.user)
        )
        connections = Connection.objects.filter(scope)
        context["connection_counts"] = {
            "pending": connections.filter(status="pending").exclude(initiated_by=role).count(),
            "messages": Message.objects.filter(
                connection__in=connections, read_at__isnull=True, unsent_at__isnull=True
            )
            .exclude(sender=request.user)
            .count(),
            "updates": ConnectionActivity.objects.filter(
                connection__in=connections, read_at__isnull=True
            )
            .exclude(actor=request.user)
            .count(),
        }
        # Requests already have an unread creation activity; do not count them twice.
        context["connection_notification_count"] = (
            context["connection_counts"]["messages"] + context["connection_counts"]["updates"]
        )
        match = getattr(request, "resolver_match", None)
        if match and match.url_name in {"recommendations", "employer_jobs"}:
            context["connection_recent_activity"] = (
                ConnectionActivity.objects.filter(connection__in=connections)
                .exclude(actor=request.user)
                .select_related("connection__job", "connection__seeker__user")
                .order_by("-created_at", "-pk")[:5]
            )
    return context
