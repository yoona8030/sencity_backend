import csv
from pathlib import Path

from django.core.management.base import BaseCommand
from inquiries.models import Inquiry, InquiryMessage, InquiryAttachment
from django.utils import timezone
from django.utils.dateparse import parse_datetime

class Command(BaseCommand):
    help = "Import inquiries, messages, attachments from CSV files"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dir",
            default="fixtures",
            help="Base directory where CSV files exist (default: fixtures)",
        )

    def handle(self, *args, **options):
        base = Path(options["dir"]).resolve()
        self.stdout.write(self.style.NOTICE(f"Base dir: {base}"))

        # 1) Inquiries
        f_inq = base / "inquiries_inquiry.csv"
        if f_inq.exists():
            with f_inq.open(encoding="utf-8") as fp:
                for row in csv.DictReader(fp):
                    Inquiry.objects.update_or_create(
                        id=int(row["id"]),
                        defaults={
                            "user_id": row["user_id"] or None,
                            "admin_id": row["admin_id"] or None,
                            "title": row["title"],
                            "category": row["category"],
                            "priority": row["priority"],
                            "status": row["status"],
                            "created_at": row["created_at"],
                            "updated_at": row["updated_at"],
                            "user_last_read_at": row.get("user_last_read_at") or None,
                            "admin_last_read_at": row.get("admin_last_read_at") or None,
                        },
                    )
            self.stdout.write(self.style.SUCCESS("Imported inquiries"))
        else:
            self.stdout.write(self.style.WARNING(f"NOT FOUND: {f_inq}"))

        # 2) Messages
        f_msg = base / "inquiries_message.csv"   # 파일명 확인!
        if f_msg.exists():
            with f_msg.open(encoding="utf-8") as fp:
                reader = csv.DictReader(fp)
                for row in reader:
                    # created_at 파싱 (비어있으면 now)
                    created_raw = (row.get("created_at") or "").strip()
                    dt = parse_datetime(created_raw) if created_raw else None
                    created_at = dt if dt else timezone.now()

                    def to_int_or_none(v):
                        v = (v or "").strip()
                        return int(v) if v else None

                    InquiryMessage.objects.update_or_create(
                        id=int(row["id"]),
                        defaults={
                            "inquiry_id": int(row["inquiry_id"]),
                            "sender_type": row["sender_type"],
                            "sender_user_id": to_int_or_none(row.get("sender_user_id")),
                            "sender_admin_id": to_int_or_none(row.get("sender_admin_id")),
                            "body": row["body"],
                            "created_at": created_at,
                        },
                    )
            self.stdout.write(self.style.SUCCESS("Imported messages"))
        else:
            self.stdout.write(self.style.WARNING(f"NOT FOUND: {f_msg}"))

       # 3) Attachments
        f_att = base / "inquiries_attachment.csv"
        if f_att.exists():
            with f_att.open(encoding="utf-8") as fp:
                reader = csv.DictReader(fp)
                for row in reader:
                    # ---- 전처리: 숫자/날짜/경로 정리 ----
                    def to_int_or_zero(v):
                        v = (v or "").strip()
                        return int(v) if v else 0

                    # created_at 파싱 (없으면 now)
                    created_raw = (row.get("created_at") or "").strip()
                    created_at = parse_datetime(created_raw) or timezone.now()

                    # FileField에는 media 루트 기준 상대경로만 저장 (예: inquiries/2025/09/04/xxx.jpg)
                    # CSV가 '/media/...' 로 시작하면 제거
                    file_path = (row.get("file") or "").lstrip("/")

                    InquiryAttachment.objects.update_or_create(
                        id=int(row["id"]),
                        defaults={
                            # FK는 *_id로 넣어도 됩니다.
                            "message_id": int(row["message_id"]),
                            "file": file_path,
                            "mime": row.get("mime") or "",
                            "size": to_int_or_zero(row.get("size")),
                            "created_at": created_at,
                        },
                    )
            self.stdout.write(self.style.SUCCESS("Imported attachments"))
        else:
            self.stdout.write(self.style.WARNING(f"NOT FOUND: {f_att}"))
