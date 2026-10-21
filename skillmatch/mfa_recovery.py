"""One-time recovery operations; plaintext exists only for the initial response."""

from django.contrib.auth import get_user_model
from django.db import transaction
from django.views.decorators.debug import sensitive_variables
from django_otp.util import random_hex

from .mfa import confirmed_device
from .models import RecoveryCode, RecoveryDevice

RECOVERY_CODE_COUNT = 10


@transaction.atomic
@sensitive_variables()
def generate_codes(authenticator):
    """Replace the entire set after setup confirmation or password re-verification."""
    get_user_model().objects.select_for_update().get(pk=authenticator.user_id)
    if not authenticator.confirmed:
        raise ValueError("Confirm an authenticator before generating recovery codes.")
    device, _ = RecoveryDevice.objects.select_for_update().get_or_create(
        authenticator=authenticator,
        defaults={"user": authenticator.user, "name": "Recovery codes", "confirmed": True},
    )
    device.codes.all().delete()
    # django-otp's generator uses os.urandom. Each code has 128 random bits.
    tokens = set()
    while len(tokens) < RECOVERY_CODE_COUNT:
        tokens.add(random_hex(16))
    codes = ["-".join(token[i : i + 8] for i in range(0, 32, 8)) for token in sorted(tokens)]
    RecoveryCode.objects.bulk_create(
        [RecoveryCode(device=device, digest=device.token_digest(code)) for code in codes]
    )
    device.throttle_reset()
    return codes


@transaction.atomic
@sensitive_variables()
def verify_recovery_code(user, token):
    get_user_model().objects.select_for_update().get(pk=user.pk)
    authenticator = confirmed_device(user)
    if authenticator is None:
        return None
    device = (
        RecoveryDevice.objects.select_for_update()
        .filter(user=user, authenticator=authenticator, confirmed=True)
        .first()
    )
    return device if device is not None and device.verify_token(token) else None


@transaction.atomic
@sensitive_variables()
def regenerate_codes(user, password):
    # An unlocked verified browser alone is insufficient. Password retries use
    # the same persistent exponential back-off as recovery-code verification.
    user = get_user_model().objects.select_for_update().get(pk=user.pk, is_active=True)
    authenticator = confirmed_device(user)
    if authenticator is None:
        return None
    device, _ = RecoveryDevice.objects.select_for_update().get_or_create(
        authenticator=authenticator,
        defaults={"user": user, "name": "Recovery codes", "confirmed": True},
    )
    if not device.verify_is_allowed()[0]:
        return None
    if not user.check_password(password):
        device.throttle_increment()
        return None
    return generate_codes(authenticator)
