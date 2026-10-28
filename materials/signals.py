from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Material


@receiver(post_delete, sender=Material)
def remove_material_file(sender, instance, **kwargs):
    if instance.file:
        instance.file.delete(save=False)
