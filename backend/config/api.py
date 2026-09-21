from ninja import NinjaAPI
from ninja.security import django_auth

from accounts.api import router as auth_router
from accounts.services import PinError
from core.api import router as core_router
from inventory.api import router as inventory_router
from inventory.services import StockError
from sales.api import router as sales_router
from sales.services import SaleError

# Every endpoint needs a logged-in session (and a CSRF token for writes),
# except the few in accounts.api marked auth=None.
api = NinjaAPI(title="Drug POS API", version="0.1", auth=django_auth)

api.add_router("/auth", auth_router)
api.add_router("/", core_router)
api.add_router("/", inventory_router)
api.add_router("/", sales_router)


@api.exception_handler(SaleError)
def sale_error(request, exc: SaleError):
    return api.create_response(request, {"detail": exc.message}, status=exc.status)


@api.exception_handler(StockError)
def stock_error(request, exc: StockError):
    return api.create_response(request, {"detail": exc.message}, status=400)


@api.exception_handler(PinError)
def pin_error(request, exc: PinError):
    return api.create_response(request, {"detail": exc.message}, status=exc.status)
