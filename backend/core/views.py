from django.conf import settings
from django.http import FileResponse, HttpResponse


def spa(request):
    """The React sales screen (frontend/dist, built with `npm run build`)."""
    index = settings.FRONTEND_DIST / "index.html"
    if not index.exists():
        return HttpResponse(
            "<p style='font-family:sans-serif'>ยังไม่ได้ build หน้าขาย — "
            "ระหว่างพัฒนาให้เปิด <a href='http://localhost:5173'>http://localhost:5173</a> "
            "หรือรัน <code>npm run build</code> ในโฟลเดอร์ frontend</p>"
        )
    return FileResponse(index.open("rb"), content_type="text/html; charset=utf-8")
