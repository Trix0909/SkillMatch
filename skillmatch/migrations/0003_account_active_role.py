from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("skillmatch", "0002_mfa_recovery_codes"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="account",
            name="valid_account_role",
        ),
        migrations.RenameField(
            model_name="account",
            old_name="role",
            new_name="active_role",
        ),
        migrations.AddConstraint(
            model_name="account",
            constraint=models.CheckConstraint(
                condition=models.Q(active_role__in=["seeker", "employer"]),
                name="valid_account_active_role",
            ),
        ),
    ]
