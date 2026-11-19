from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0004_employee_must_change_password'),
    ]

    operations = [
        migrations.AddField(
            model_name='authtoken',
            name='source',
            field=models.CharField(
                choices=[('local', '本地登录'), ('oidc', '统一身份登录')],
                default='local',
                help_text='local=本地账密登录签发; oidc=统一身份登录(Keycloak)签发; 切换日 DELETE source=local 作废旧本地令牌 (方案文档 6.2)',
                max_length=8,
                verbose_name='来源',
            ),
        ),
    ]
