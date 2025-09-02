from django.db import migrations, transaction
from django.db.models import Count

def forwards(apps, schema_editor):
    Notification = apps.get_model("api", "Notification")
    Feedback     = apps.get_model("api", "Feedback")
    Admin        = apps.get_model("api", "Admin")

    # 1) 개인 알림(type=individual)인데 수신자가 '관리자 계정(User.admin 존재)'인 것 삭제
    admin_user_ids = list(
        Admin.objects.exclude(user_id__isnull=True).values_list("user_id", flat=True)
    )
    if admin_user_ids:
        Notification.objects.filter(
            type="individual", user_id__in=admin_user_ids
        ).delete()

    # 2) report_id 비어있는 개인 알림에 report_id 연결(피드백 내용 매칭)
    with transaction.atomic():
        qs = Notification.objects.select_for_update().filter(
            type="individual", report_id__isnull=True
        )
        for n in qs.iterator():
            fb = (
                Feedback.objects
                .filter(user_id=n.user_id, content=n.reply)
                .order_by("-feedback_datetime")
                .first()
            )
            if fb:
                n.report_id = fb.report_id
                n.save(update_fields=["report_id"])

    # 3) (user, report)별 개인 알림 중복 제거 → 최신 1개만 유지
    dup_groups = (
        Notification.objects
        .filter(type="individual", report_id__isnull=False)
        .values("user_id", "report_id")
        .annotate(c=Count("id"))
        .filter(c__gt=1)
    )
    for g in dup_groups:
        rows = (
            Notification.objects
            .filter(type="individual", user_id=g["user_id"], report_id=g["report_id"])
            .order_by("-created_at", "-id")
        )
        for extra in rows[1:]:
            extra.delete()

def backwards(apps, schema_editor):
    # 데이터 정리는 되돌리지 않음
    pass

class Migration(migrations.Migration):
    dependencies = [
        ("api", "0008_notification_report"),  # 현재 마지막 번호에 맞춰 주세요
    ]
    operations = [
        migrations.RunPython(forwards, backwards),
    ]
