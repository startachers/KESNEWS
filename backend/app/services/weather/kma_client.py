from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from typing import Any, Callable
from urllib.parse import unquote, urlencode
from zoneinfo import ZoneInfo

from backend.app.services.collection.http import CollectionHttpError, http_get

KST = ZoneInfo("Asia/Seoul")
SHORT_URL = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
MID_LAND_URL = "https://apis.data.go.kr/1360000/MidFcstInfoService/getMidLandFcst"
MID_TA_URL = "https://apis.data.go.kr/1360000/MidFcstInfoService/getMidTa"
ALERT_URL = "https://apis.data.go.kr/1360000/WthrWrnInfoService/getPwnStatus"


class KmaApiError(Exception):
    pass


HttpGetter = Callable[[str, dict[str, str], float], tuple[int, str]]


def _items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        value = payload["response"]["body"]["items"]["item"]
    except (KeyError, TypeError):
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return [value] if isinstance(value, dict) else []


def _request_json(
    url: str,
    params: dict[str, Any],
    *,
    service_key: str,
    getter: HttpGetter,
) -> dict[str, Any]:
    # 공공데이터포털은 인코딩/디코딩 인증키를 모두 보여 준다. 이미 인코딩된 키를
    # urlencode에 그대로 넘기면 '%'가 다시 인코딩되어 인증에 실패하므로 한 번
    # 정규화한 뒤 쿼리 문자열을 만든다.
    normalized_key = unquote(service_key)
    query = urlencode({"serviceKey": normalized_key, "dataType": "JSON", **params})
    try:
        status, body = getter(f"{url}?{query}", {"User-Agent": "KESCO-Weather/1.0"}, 15)
    except CollectionHttpError as exc:
        raise KmaApiError(str(exc)) from exc
    if status != 200:
        raise KmaApiError(f"기상청 API가 HTTP {status}로 응답했습니다.")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise KmaApiError("기상청 API가 JSON이 아닌 응답을 반환했습니다.") from exc
    header = (payload.get("response") or {}).get("header") or {}
    if str(header.get("resultCode") or "00") not in {"00", "0"}:
        raise KmaApiError(str(header.get("resultMsg") or "기상청 API 오류"))
    return payload


def _short_base(now: datetime) -> tuple[str, str]:
    available_at = now - timedelta(minutes=15)
    slots = [2, 5, 8, 11, 14, 17, 20, 23]
    chosen = next((hour for hour in reversed(slots) if hour <= available_at.hour), None)
    base_day = available_at.date()
    if chosen is None:
        base_day -= timedelta(days=1)
        chosen = 23
    return base_day.strftime("%Y%m%d"), f"{chosen:02d}00"


def _mid_base(now: datetime) -> str:
    available_at = now - timedelta(minutes=15)
    if available_at.hour >= 18:
        base_day, hour = available_at.date(), 18
    elif available_at.hour >= 6:
        base_day, hour = available_at.date(), 6
    else:
        base_day, hour = available_at.date() - timedelta(days=1), 18
    return f"{base_day:%Y%m%d}{hour:02d}00"


def _iso_kst(raw_date: Any, raw_time: Any = "0000") -> str | None:
    digits = "".join(ch for ch in str(raw_date or "") if ch.isdigit())
    clock = "".join(ch for ch in str(raw_time or "0000") if ch.isdigit()).zfill(4)
    if len(digits) < 8:
        return None
    if len(digits) >= 12 and clock == "0000":
        clock = digits[8:12]
    try:
        parsed = datetime.strptime(f"{digits[:8]}{clock[:4]}", "%Y%m%d%H%M").replace(tzinfo=KST)
    except ValueError:
        return None
    return parsed.isoformat()


def _observation(provider: str, product: str, request_key: str, payload: Any, issued_at: str | None) -> dict[str, Any]:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "provider": provider,
        "product": product,
        "requestKey": request_key,
        "issuedAt": issued_at,
        "payload": payload,
        "payloadHash": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    }


def _current_alert_entries(text: str) -> list[str]:
    return [line.removeprefix("o ").strip() for line in text.splitlines() if line.strip()]


def _preliminary_alert_entries(text: str) -> list[str]:
    entries: list[str] = []
    heading = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "예비특보" in line:
            heading = line
            if ":" in line and line.split(":", 1)[1].strip():
                entries.append(line)
            continue
        entries.append(f"{heading} · {line.removeprefix('o ').strip()}" if heading else line)
    return entries or ([text.strip()] if text.strip() else [])


def collect_alerts(service_key: str, regions: list[dict[str, Any]], getter: HttpGetter = http_get) -> dict[str, Any]:
    try:
        payload = _request_json(
            ALERT_URL,
            {"pageNo": 1, "numOfRows": 1000},
            service_key=service_key,
            getter=getter,
        )
        items = _items(payload)
    except KmaApiError as exc:
        return {"provider": "alerts", "status": "failed", "items": [], "observations": [], "error": str(exc), "issuedAt": None}
    alerts = []
    for item in items:
        issued_at = _iso_kst(item.get("tmFc") or item.get("announceTime") or item.get("tm"))
        current_text = str(item.get("t6") or item.get("title") or item.get("warnTitle") or "").strip()
        preliminary_text = str(item.get("t7") or "").strip()
        entries: list[tuple[str, bool]] = []
        if current_text:
            entries.extend((text, False) for text in _current_alert_entries(current_text))
        if preliminary_text:
            entries.extend((text, True) for text in _preliminary_alert_entries(preliminary_text))
        if not entries:
            fallback = " ".join(
                str(value) for value in item.values() if value not in (None, "")
            ).strip()
            if fallback:
                entries.append((fallback, False))
        for text, preliminary in entries:
            region_ids = [
                region["id"]
                for region in regions
                if any(token in text for token in region.get("areaTokens") or [])
            ]
            alerts.append(
                {
                    "title": text[:2000],
                    "issuedAt": issued_at,
                    "effectiveAt": (
                        issued_at
                        if preliminary
                        else _iso_kst(item.get("tmEf") or item.get("effectiveTime"))
                    ),
                    "expiresAt": _iso_kst(item.get("tmEd") or item.get("expireTime")),
                    "regionIds": region_ids or ["national"],
                    "preliminary": preliminary,
                    "raw": item,
                }
            )
    issued_at = max((item["issuedAt"] for item in alerts if item.get("issuedAt")), default=None)
    return {
        "provider": "alerts",
        "status": "success",
        "items": alerts,
        "observations": [_observation("kma_alert", "getPwnStatus", "national", payload, issued_at)],
        "error": None,
        "issuedAt": issued_at,
    }


def collect_short(service_key: str, regions: list[dict[str, Any]], getter: HttpGetter = http_get, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(KST)
    base_date, base_time = _short_base(now)
    jobs = []
    for region in regions:
        for point in region.get("shortForecastPoints") or []:
            jobs.append((region, point))
    observations: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    failed_region_ids: set[str] = set()

    def fetch(job):
        region, point = job
        payload = _request_json(
            SHORT_URL,
            {"pageNo": 1, "numOfRows": 1000, "base_date": base_date, "base_time": base_time, "nx": point["nx"], "ny": point["ny"]},
            service_key=service_key,
            getter=getter,
        )
        return region, point, payload

    with ThreadPoolExecutor(max_workers=min(8, max(1, len(jobs)))) as executor:
        futures = {executor.submit(fetch, job): job for job in jobs}
        for future in as_completed(futures):
            region, point = futures[future]
            try:
                _, _, payload = future.result()
            except Exception as exc:
                errors.append(f"{point['label']}: {exc}")
                failed_region_ids.add(region["id"])
                continue
            issued_at = _iso_kst(base_date, base_time)
            observations.append(_observation("kma_short", "getVilageFcst", point["id"], payload, issued_at))
            for item in _items(payload):
                rows.append({**item, "regionId": region["id"], "pointId": point["id"]})
    status = "success" if rows and not errors else "partial" if rows else "failed"
    return {
        "provider": "shortForecast",
        "status": status,
        "items": rows,
        "observations": observations,
        "error": "; ".join(errors[:4]) or None,
        "issuedAt": _iso_kst(base_date, base_time) if rows else None,
        "failedRegionIds": sorted(failed_region_ids),
    }


def collect_mid(service_key: str, regions: list[dict[str, Any]], getter: HttpGetter = http_get, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(KST)
    tm_fc = _mid_base(now)
    jobs: list[tuple[str, dict[str, Any], str]] = []
    for region in regions:
        jobs.extend(("land", region, code) for code in region.get("midLandCodes") or [])
        jobs.extend(("temperature", region, item["id"]) for item in region.get("midTemperaturePoints") or [])
    observations: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    failed_region_ids: set[str] = set()

    def fetch(job):
        kind, region, code = job
        url = MID_LAND_URL if kind == "land" else MID_TA_URL
        payload = _request_json(url, {"pageNo": 1, "numOfRows": 10, "regId": code, "tmFc": tm_fc}, service_key=service_key, getter=getter)
        return kind, region, code, payload

    with ThreadPoolExecutor(max_workers=min(8, max(1, len(jobs)))) as executor:
        futures = {executor.submit(fetch, job): job for job in jobs}
        for future in as_completed(futures):
            kind, region, code = futures[future]
            try:
                _, _, _, payload = future.result()
            except Exception as exc:
                errors.append(f"{code}: {exc}")
                failed_region_ids.add(region["id"])
                continue
            observations.append(_observation("kma_mid", f"getMid{kind.title()}", code, payload, _iso_kst(tm_fc[:8], tm_fc[8:])))
            rows.extend({**item, "regionId": region["id"], "kind": kind} for item in _items(payload))
    status = "success" if rows and not errors else "partial" if rows else "failed"
    return {
        "provider": "midForecast",
        "status": status,
        "items": rows,
        "observations": observations,
        "error": "; ".join(errors[:4]) or None,
        "issuedAt": _iso_kst(tm_fc[:8], tm_fc[8:]) if rows else None,
        "failedRegionIds": sorted(failed_region_ids),
    }


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _precipitation_amount(value: Any) -> dict[str, Any] | None:
    text = str(value or "").strip()
    if not text or "강수없음" in text or "강수 없음" in text:
        return None
    numbers = [float(item) for item in re.findall(r"\d+(?:\.\d+)?", text)]
    if not numbers:
        return None
    if "미만" in text:
        lower, upper = 0.0, numbers[0]
    elif "이상" in text:
        lower, upper = numbers[0], None
    elif len(numbers) >= 2:
        lower, upper = numbers[0], numbers[1]
    else:
        lower = upper = numbers[0]
    return {
        "text": text.replace(" ", ""),
        "min": lower,
        "max": upper,
        "unit": "mm/h",
    }


def _weather_text(pty: int, sky: int) -> str:
    if pty in {3, 7}:
        return "눈"
    if pty in {1, 2, 4, 5, 6}:
        return "비"
    return "맑음" if sky <= 1 else "구름많음" if sky <= 3 else "흐림"


def build_daily_summaries(
    report_date: str,
    short_rows: list[dict[str, Any]],
    mid_rows: list[dict[str, Any]],
    regions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    start = date.fromisoformat(report_date)
    regional: dict[tuple[str, str], dict[str, Any]] = {}
    for item in short_rows:
        raw_date = str(item.get("fcstDate") or "")
        if len(raw_date) != 8:
            continue
        day = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
        try:
            offset = (date.fromisoformat(day) - start).days
        except ValueError:
            continue
        if offset < 0 or offset > 3:
            continue
        key = (item["regionId"], day)
        bucket = regional.setdefault(key, {"temps": [], "pops": [], "precipitation": [], "winds": [], "pty": [], "sky": [], "source": "kma_short"})
        category = item.get("category")
        if category == "PCP":
            amount = _precipitation_amount(item.get("fcstValue"))
            if amount:
                bucket["precipitation"].append(amount)
            continue
        value = _number(item.get("fcstValue"))
        if value is None:
            continue
        if category in {"TMP", "TMN", "TMX"}:
            bucket["temps"].append(value)
        elif category == "POP":
            bucket["pops"].append(value)
        elif category == "WSD":
            bucket["winds"].append(value)
        elif category == "PTY":
            bucket["pty"].append(int(value))
        elif category == "SKY":
            bucket["sky"].append(int(value))

    for item in mid_rows:
        region_id = item["regionId"]
        for offset in range(4, 7):
            day = (start + timedelta(days=offset)).isoformat()
            bucket = regional.setdefault((region_id, day), {"temps": [], "pops": [], "precipitation": [], "winds": [], "pty": [], "sky": [], "weather": [], "source": "kma_mid"})
            if item.get("kind") == "land":
                for suffix in ("Am", "Pm"):
                    pop = _number(item.get(f"rnSt{offset}{suffix}"))
                    if pop is not None:
                        bucket["pops"].append(pop)
                    weather = item.get(f"wf{offset}{suffix}")
                    if weather:
                        bucket["weather"].append(str(weather))
            else:
                for name in (f"taMin{offset}", f"taMax{offset}"):
                    value = _number(item.get(name))
                    if value is not None:
                        bucket["temps"].append(value)

    def summarize(buckets: list[dict[str, Any]]) -> dict[str, Any]:
        temps = [value for bucket in buckets for value in bucket["temps"]]
        pops = [value for bucket in buckets for value in bucket["pops"]]
        winds = [value for bucket in buckets for value in bucket["winds"]]
        precipitation = [value for bucket in buckets for value in bucket["precipitation"]]
        weather_phrases = [value for bucket in buckets for value in bucket.get("weather", [])]
        pty = max((value for bucket in buckets for value in bucket["pty"]), default=0)
        sky = max((value for bucket in buckets for value in bucket["sky"]), default=1)
        if weather_phrases:
            weather_text = next((value for value in weather_phrases if "비" in value or "눈" in value), weather_phrases[0])
        else:
            weather_text = _weather_text(pty, sky)
        max_hourly_precipitation = max(
            precipitation,
            key=lambda item: item["max"] if item["max"] is not None else item["min"] + 10000,
            default=None,
        )
        return {
            "weatherText": weather_text if buckets else "정보 없음",
            "temperature": {
                "min": round(min(temps)) if temps else None,
                "max": round(max(temps)) if temps else None,
                "isNationalRange": len(buckets) > 1,
            },
            "maxPrecipitationProbability": round(max(pops)) if pops else None,
            "maxHourlyPrecipitation": max_hourly_precipitation,
            "maxWindSpeed": round(max(winds), 1) if winds else None,
            "riskLevel": "normal" if buckets else "unknown",
            "source": buckets[0]["source"] if buckets else None,
        }

    region_definitions = regions or [
        {"id": region_id, "label": region_id}
        for region_id in sorted({region_id for region_id, _ in regional})
    ]
    days: list[dict[str, Any]] = []
    for offset in range(7):
        day = (start + timedelta(days=offset)).isoformat()
        buckets = [value for (_, value_day), value in regional.items() if value_day == day]
        national = summarize(buckets)
        region_summaries = []
        for region in region_definitions:
            region_buckets = [
                value
                for (region_id, value_day), value in regional.items()
                if value_day == day and region_id == region["id"]
            ]
            region_summaries.append(
                {
                    "regionId": region["id"],
                    "regionLabel": region.get("label") or region["id"],
                    **summarize(region_buckets),
                }
            )
        days.append(
            {
                "date": day,
                **national,
                "temperature": {**national["temperature"], "isNationalRange": True},
                "affectedRegionCount": 0,
                "regions": region_summaries,
            }
        )
    return days
