# Generated by Django 3.0.7 on 2020-10-09 19:33

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("experiments", "0121_prune_add_version_changelogs"),
    ]

    def prune_new_changelog(apps, schema_editor):

        ExperimentChangeLog = apps.get_model("experiments", "ExperimentChangeLog")

        ExperimentChangeLog.objects.filter(
            message="Added Version(s)",
        ).delete()

    operations = [
        migrations.RunPython(prune_new_changelog, reverse_code=migrations.RunPython.noop)
    ]