def navigation(request):
    role = ""
    if request.user.is_authenticated:
        account = getattr(request.user, "account", None)
        role = account.active_role if account else ""
    return {"account_role": role}
