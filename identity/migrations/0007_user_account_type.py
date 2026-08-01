from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("identity", "0006_user_password_lockout")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="account_type",
            field=models.CharField(
                choices=[("researcher", "Researcher"), ("company", "Company")],
                db_index=True,
                default="researcher",
                max_length=20,
            ),
        ),
    ]
