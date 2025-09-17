# api/ml_alias.py (새 파일로 분리 추천)
from typing import Tuple, Optional

# 모델이 내는 라벨(영문) -> DB의 기준 키(영문) & 한글표기
# 지금 DB가 'goat'로 저장되어 있다면 임시로 여기에 묶어줌
CANON = {
    "water deer": {"db_key_en": "goat", "ko": "고라니"},  # 임시 매핑
    "roe deer":   {"db_key_en": "roe deer", "ko": "노루"},
    "egret":      {"db_key_en": "egret", "ko": "중대백로"},
    "heron":      {"db_key_en": "heron", "ko": "왜가리"},
    "squirrel":   {"db_key_en": "squirrel", "ko": "다람쥐"},
    "chipmunk":   {"db_key_en": "chipmunk", "ko": "청설모"},
    # 기타 단일종은 라벨과 DB가 같다면 굳이 안 넣어도 됨
}

ALIASES = {
    # 동의어/철자변형도 여기서 흡수
    "water-deer": "water deer",
    "hydropotes inermis": "water deer",
    "goat": "water deer",  # 모델이 goat을 내더라도 고라니로 정규화
}

def normalize_label(label: str) -> str:
    k = (label or "").strip().lower()
    return ALIASES.get(k, k)

def map_to_db(label: str) -> Tuple[str, Optional[str]]:
    norm = normalize_label(label)
    meta = CANON.get(norm)
    if meta:
        return meta["db_key_en"], meta.get("ko")
    # 기본값: 정규화만 하고 그대로 사용
    return norm, None
