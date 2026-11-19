from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0003_rename_employee_id_to_username'),
    ]

    operations = [
        migrations.AddField(
            model_name='employee',
            name='must_change_password',
            field=models.BooleanField(default=False, verbose_name='首次登录需修改密码'),
        ),
    ]