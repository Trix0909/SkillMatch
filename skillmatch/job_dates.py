"""Runtime business dates for inclusive job deadlines (Africa/Nairobi in settings)."""

from django.utils import timezone


def business_date():
    # Use the configured business timezone, not a per-request activated timezone.
    return timezone.localdate(timezone=timezone.get_default_timezone())
