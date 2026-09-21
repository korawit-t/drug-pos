from django.core.management.base import BaseCommand, CommandError

from inventory.services import stock_mismatches


class Command(BaseCommand):
    help = "ตรวจว่ายอดคงเหลือของทุก lot ตรงกับสมุดบัญชีสต็อก (StockMovement)"

    def handle(self, *args, **options):
        mismatches = stock_mismatches()
        if not mismatches:
            self.stdout.write(self.style.SUCCESS("สต็อกตรงกับ ledger ทุก lot"))
            return
        for lot in mismatches:
            self.stdout.write(f"{lot}: คงเหลือ {lot.qty_on_hand} แต่ ledger รวมได้ {lot.ledger}")
        raise CommandError(f"พบ {len(mismatches)} lot ที่ยอดไม่ตรง")
