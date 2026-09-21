from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from ninja import Router, Schema
from ninja.errors import HttpError
from ninja.utils import check_csrf

router = Router(tags=["auth"])


class LoginIn(Schema):
    username: str
    password: str


class MeOut(Schema):
    id: int
    username: str
    name: str
    role: str
    is_staff: bool


def _me(user) -> dict:
    return {
        "id": user.pk,
        "username": user.username,
        "name": user.label_name,
        "role": user.role,
        "is_staff": user.is_staff,
    }


@router.get("/csrf", auth=None)
def csrf(request):
    """Sets the csrftoken cookie the React app sends back in X-CSRFToken."""
    get_token(request)
    return {"ok": True}


@router.post("/login", auth=None, response=MeOut)
def do_login(request, data: LoginIn):
    if check_csrf(request):
        raise HttpError(403, "หน้าเว็บหมดอายุ รีเฟรชแล้วลองใหม่")
    user = authenticate(request, username=data.username, password=data.password)
    if user is None:
        raise HttpError(401, "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
    login(request, user)
    return _me(user)


@router.post("/logout")
def do_logout(request):
    logout(request)
    return {"ok": True}


@router.get("/me", response=MeOut)
def me(request):
    return _me(request.user)
