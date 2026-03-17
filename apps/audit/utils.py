from .models import AuditLog


def log_action(user, action, model_name, object_id,
               old_value=None, new_value=None, object_repr=''):
    AuditLog.objects.create(
        user=user,
        action=action,
        model_name=model_name,
        object_id=object_id,
        object_repr=object_repr,
        old_value=old_value,
        new_value=new_value,
    )
