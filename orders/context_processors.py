from .models import ShopSettings


def shop(request):
    return {"shop": ShopSettings.load()}
