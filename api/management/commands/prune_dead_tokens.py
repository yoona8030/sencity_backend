from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from api.models import DeviceToken

class Command(BaseCommand):
    help = '오래 사용 안 된 비활성 토큰 정리'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=90)

    def handle(self, *args, **opts):
        cutoff = timezone.now() - timedelta(days=opts['days'])
        qs = DeviceToken.objects.filter(is_active=False, last_seen__lt=cutoff)
        n = qs.count()
        qs.delete()
        self.stdout.write(self.style.SUCCESS(f'Deleted {n} inactive tokens'))
