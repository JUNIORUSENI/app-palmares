from .models import AuditLog

# object_repr est limité à 200 caractères en base : un nom de fichier plus long ferait échouer l'enregistrement
_REPR_MAX = AuditLog._meta.get_field('object_repr').max_length


def log_action(user, action, model_name, object_id,
               old_value=None, new_value=None, object_repr=''):
    AuditLog.objects.create(
        user=user,
        action=action,
        model_name=model_name,
        object_id=object_id,
        object_repr=str(object_repr)[:_REPR_MAX],
        old_value=old_value,
        new_value=new_value,
    )
