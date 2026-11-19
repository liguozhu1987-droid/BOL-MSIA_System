# Generated manually for auth module

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='employee',
            name='last_login',
            field=models.DateTimeField(blank=True, null=True, verbose_name='最后登录'),
        ),
        migrations.AddField(
            model_name='employee',
            name='password',
            field=models.CharField(blank=True, max_length=128, verbose_name='密码哈希'),
        ),
        migrations.CreateModel(
            name='AuthToken',
            fields=[
                ('key', models.CharField(max_length=64, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('expires_at', models.DateTimeField(verbose_name='过期时间')),
                ('employee', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='auth_tokens', to='users.employee', verbose_name='员工')),
            ],
            options={
                'verbose_name': '登录令牌',
                'verbose_name_plural': '登录令牌',
                'db_table': 'CN_IE_BOL_AuthToken',
            },
        ),
        migrations.CreateModel(
            name='PasswordResetToken',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('token', models.CharField(max_length=64, unique=True, verbose_name='重置令牌')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('expires_at', models.DateTimeField(verbose_name='过期时间')),
                ('used', models.BooleanField(default=False, verbose_name='已使用')),
                ('employee', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reset_tokens', to='users.employee', verbose_name='员工')),
            ],
            options={
                'verbose_name': '密码重置令牌',
                'verbose_name_plural': '密码重置令牌',
                'db_table': 'CN_IE_BOL_PasswordResetToken',
            },
        ),
    ]
