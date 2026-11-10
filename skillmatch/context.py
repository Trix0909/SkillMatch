def navigation(request):
    role = ""
    if request.user.is_authenticated:
        account = getattr(request.user, "account", None)
        role = account.active_role if account else ""
    context = {"account_role": role}
    if role in {"seeker", "employer"} and request.user.is_active:
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
            "messages": Message.objects.filter(connection__in=connections, read_at__isnull=True)
            .exclude(sender=request.user)
            .count(),
            "updates": ConnectionActivity.objects.filter(
                connection__in=connections, read_at__isnull=True
            )
            .exclude(actor=request.user)
            .count(),
        }
        match = getattr(request, "resolver_match", None)
        if match and match.url_name in {"recommendations", "employer_jobs"}:
            context["connection_recent_activity"] = (
                ConnectionActivity.objects.filter(connection__in=connections)
                .exclude(actor=request.user)
                .select_related("connection__job", "connection__seeker__user")
                .order_by("-created_at", "-pk")[:5]
            )
    return context
