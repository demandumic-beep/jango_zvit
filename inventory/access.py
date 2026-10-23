from functools import wraps
from urllib.parse import urlencode

from django.shortcuts import redirect
from django.urls import reverse

CLIENT_COOKIE = "sl_client"     # підписане cookie з id клієнта
PREVIEW_COOKIE = "sl_preview"   # прапорець «адмін дивиться як клієнт»


def is_staff(request):
    user = getattr(request, "user", None)
    return bool(user and user.is_authenticated and user.is_staff)


def staff_required(view):
    """Пускає лише адміністраторів, інших веде на сторінку входу."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not is_staff(request):
            query = urlencode({"next": request.get_full_path()})
            return redirect(f"{reverse('login')}?{query}")
        return view(request, *args, **kwargs)
    return wrapper
