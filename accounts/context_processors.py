def account_identity(request):
    user = getattr(request, "user", None)

    if not user or not user.is_authenticated:
        return {}

    google_name = ""
    google_email = ""

    try:
        social_account = user.socialaccount_set.filter(
            provider="google",
        ).first()
    except Exception:
        social_account = None

    if social_account:
        extra_data = social_account.extra_data or {}
        google_name = (
            extra_data.get("name")
            or " ".join(
                part
                for part in (
                    extra_data.get("given_name"),
                    extra_data.get("family_name"),
                )
                if part
            )
        ).strip()
        google_email = extra_data.get("email", "")

    display_name = (
        google_name
        or user.get_full_name()
        or google_email
        or user.email
    )

    initial_source = display_name or user.email or "C"

    return {
        "account_display_name": display_name,
        "account_display_email": google_email or user.email,
        "account_display_initial": initial_source[:1].upper(),
        "account_is_google": bool(social_account),
    }
