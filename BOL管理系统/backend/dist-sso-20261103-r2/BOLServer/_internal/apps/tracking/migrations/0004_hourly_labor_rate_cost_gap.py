from decimal import Decimal

from django.db import migrations, models


def recalculate_annual_cost_gap(apps, schema_editor):
    HighBolTracking = apps.get_model('tracking', 'HighBolTracking')
    database = schema_editor.connection.alias
    for row in HighBolTracking.objects.using(database).all().iterator():
        bol_gap = Decimal(str(row.current_bol or 0)) - Decimal(str(row.target_bol or 0))
        row.bol_gap = bol_gap.quantize(Decimal('0.0001'))
        annual_volume = Decimal(str(row.annual_volume or 0))
        hourly_rate = Decimal(str(row.labor_rate or 0))
        row.cost_gap = (bol_gap * annual_volume * hourly_rate / Decimal('60')).quantize(
            Decimal('0.01')
        )
        row.save(using=database, update_fields=['bol_gap', 'cost_gap'])


def restore_previous_cost_gap(apps, schema_editor):
    HighBolTracking = apps.get_model('tracking', 'HighBolTracking')
    database = schema_editor.connection.alias
    for row in HighBolTracking.objects.using(database).all().iterator():
        row.cost_gap = (Decimal(str(row.cost_gap or 0)) * Decimal('60')).quantize(
            Decimal('0.01')
        )
        row.save(using=database, update_fields=['cost_gap'])


class Migration(migrations.Migration):
    dependencies = [
        ('tracking', '0003_add_change_fields'),
    ]

    operations = [
        migrations.AlterField(
            model_name='highboltracking',
            name='labor_rate',
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                max_digits=8,
                verbose_name='工时单价(元/小时)',
            ),
        ),
        migrations.AlterField(
            model_name='highboltracking',
            name='cost_gap',
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                max_digits=14,
                verbose_name='年化成本差异估算',
            ),
        ),
        migrations.RunPython(
            recalculate_annual_cost_gap,
            restore_previous_cost_gap,
        ),
    ]