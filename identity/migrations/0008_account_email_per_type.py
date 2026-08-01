from django.db import migrations, models
from django.db.models.functions import Lower


class Migration(migrations.Migration):
    dependencies = [("identity", "0007_user_account_type")]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="username",
            field=models.EmailField(max_length=254),
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.UniqueConstraint(
                Lower("username"),
                "account_type",
                name="identity_unique_email_per_account_type",
            ),
        ),
    ]
