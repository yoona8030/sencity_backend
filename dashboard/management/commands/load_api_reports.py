# dashboard/management/commands/load_api_reports.py
import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.contrib.auth import get_user_model
from django.utils import timezone

from dashboard.models import Report  # Report에 title 유무 상관없이 동작

# (선택) Animal 모델이 있으면 같이 매핑
try:
    from dashboard.models import Animal  # 없으면 ImportError
    HAS_ANIMAL = True
except Exception:
    HAS_ANIMAL = False

# Report에 title 필드가 있는지 자동 감지(있으면 저장, 없으면 무시)
try:
    HAS_TITLE = any(f.name == "title" for f in Report._meta.get_fields())
except Exception:
    HAS_TITLE = False

# 동물 키워드 목록 (분류용) — '야생고양이' 포함
KNOWN_ANIMALS = [
    "고라니","너구리","중대백로","노루","멧돼지","멧토끼","반달가슴곰",
    "족제비","왜가리","다람쥐","청설모","야생고양이","고양이","개","기타"
]

def split_title_and_animal(original_text: str):
    """
    '야생고양이 출몰' -> (title='야생고양이 출몰', animal='야생고양이')
    '고라니 목격'     -> (title='고라니 목격',   animal='고라니')
    동물명이 없으면 animal='기타'
    """
    text = (original_text or "").strip()
    animal = "기타"
    for name in KNOWN_ANIMALS:
        if name and name in text:
            animal = name
            break
    title = text  # 제목은 원문 그대로
    return title, animal


class Command(BaseCommand):
    help = "Load legacy API data(JSON) into Report table preserving id/reporter/date/region/status."

    def add_arguments(self, parser):
        parser.add_argument("json_path", type=str, help="Path to JSON array file.")
        parser.add_argument("--tz", type=str, default="Asia/Seoul",
                            help="Timezone for naive datetimes (default: Asia/Seoul)")
        parser.add_argument("--keep-ids", action="store_true",
                            help="Preserve `id` from json if provided.")
        parser.add_argument("--update-if-exists", action="store_true",
                            help="Update existing record when same id exists (with --keep-ids).")

    def handle(self, *args, **opts):
        path = Path(opts["json_path"])
        if not path.exists():
            raise CommandError(f"File not found: {path}")

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            raise CommandError(f"Invalid JSON: {e}")

        if not isinstance(data, list):
            raise CommandError("JSON root must be an array of objects.")

        tz = ZoneInfo(opts["tz"])
        User = get_user_model()

        def get_or_create_user(name, is_staff=False):
            if not name:
                return None
            username = str(name).strip()
            user, _ = User.objects.get_or_create(
                username=username,
                defaults={
                    "email": f"{username}@example.invalid",
                    "is_staff": is_staff,
                    "is_active": True,
                }
            )
            return user

        created_cnt = updated_cnt = skipped_cnt = 0

        with transaction.atomic():
            for i, row in enumerate(data, start=1):
                try:
                    rid           = row.get("id")
                    # 원문(문장) — title 키가 있으면 그걸 우선, 없으면 기존 animal_name(문장일 수 있음)
                    original_text = row.get("title") or row.get("animal_name") or ""
                    region        = row["report_region"]
                    status        = row["status"]
                    dt_str        = row["report_date"]
                    reporter_name = row.get("reporter")
                    admin_name    = row.get("admin")      # Report 모델엔 필드 없음(참고용)
                    lat           = float(row.get("latitude", 0.0))
                    lon           = float(row.get("longitude", 0.0))

                    # 제목/동물 분리
                    title_text, animal_name = split_title_and_animal(original_text)

                    # datetime 파싱 (naive → 지정 TZ → UTC)
                    try:
                        dt = datetime.fromisoformat(dt_str)
                    except ValueError:
                        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=tz)
                    dt = dt.astimezone(timezone.utc)

                    reporter_user = get_or_create_user(reporter_name, is_staff=False)
                    _admin_user   = get_or_create_user(admin_name,   is_staff=True)  # 모델에 저장은 안 함

                    if opts["keep-ids"] and rid is not None:
                        try:
                            obj = Report.objects.get(id=rid)
                            if opts["update-if-exists"]:
                                # 업데이트
                                update_fields = [
                                    "animal_name","report_region","status",
                                    "report_date","user","latitude","longitude"
                                ]
                                obj.animal_name   = animal_name
                                obj.report_region = region
                                obj.status        = status
                                obj.report_date   = dt
                                obj.user          = reporter_user
                                obj.latitude      = lat
                                obj.longitude     = lon
                                if HAS_TITLE:
                                    obj.title = title_text
                                    update_fields.insert(0, "title")
                                obj.save(update_fields=update_fields)
                                updated_cnt += 1
                            else:
                                skipped_cnt += 1
                            continue
                        except Report.DoesNotExist:
                            # 새로 생성 (PK 유지)
                            kwargs = dict(
                                id=rid,
                                animal_name=animal_name,
                                report_region=region,
                                status=status,
                                report_date=dt,
                                user=reporter_user,
                                latitude=lat,
                                longitude=lon,
                            )
                            if HAS_TITLE:
                                kwargs["title"] = title_text
                            obj = Report(**kwargs)
                            obj.save(force_insert=True)
                            created_cnt += 1
                    else:
                        # 고유성 기준 — 프로젝트에 맞게 조정 가능
                        get_or_create_kwargs = dict(
                            report_region=region,
                            report_date=dt,
                        )
                        if HAS_TITLE:
                            get_or_create_kwargs["title"] = title_text
                        else:
                            get_or_create_kwargs["animal_name"] = animal_name

                        obj, created = Report.objects.get_or_create(
                            **get_or_create_kwargs,
                            defaults=dict(
                                animal_name=animal_name,
                                status=status,
                                user=reporter_user,
                                latitude=lat,
                                longitude=lon,
                            ),
                        )
                        if created:
                            created_cnt += 1
                        else:
                            if opts["update-if-exists"]:
                                obj.animal_name = animal_name
                                obj.status      = status
                                obj.user        = reporter_user
                                obj.latitude    = lat
                                obj.longitude   = lon
                                obj.save(update_fields=["animal_name","status","user","latitude","longitude"])
                                updated_cnt += 1
                            else:
                                skipped_cnt += 1

                    # (선택) Animal FK가 있다면 매핑 (모델에 animal 필드가 있는 경우만)
                    if HAS_ANIMAL and hasattr(obj, "animal_id"):
                        try:
                            animal_obj = Animal.objects.get(name=animal_name)
                            if obj.animal_id != animal_obj.id:
                                obj.animal = animal_obj
                                obj.save(update_fields=["animal"])
                        except Animal.DoesNotExist:
                            pass

                except KeyError as e:
                    raise CommandError(f"Row {i}: missing required key {e!s}")
                except Exception as e:
                    raise CommandError(f"Row {i} failed: {e}")

        self.stdout.write(self.style.SUCCESS(
            f"Done. created={created_cnt}, updated={updated_cnt}, skipped={skipped_cnt}"
        ))
        if not HAS_ANIMAL:
            self.stdout.write(self.style.NOTICE(
                "참고: Animal 모델이 없어 Report.animal FK 매핑은 생략했습니다. "
                "Report.animal_name(문자열)만 채워졌습니다."
            ))
        if not HAS_TITLE:
            self.stdout.write(self.style.NOTICE(
                "참고: Report 모델에 title 필드가 없어 제목은 저장되지 않았습니다. "
                "제목을 보존하려면 Report.title(CharField)을 추가하세요."
            ))
