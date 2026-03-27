import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('imports', '0002_academic_year_nullable'),
    ]

    operations = [
        migrations.AddField(
            model_name='sourcefile',
            name='batch_id',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
    ]
