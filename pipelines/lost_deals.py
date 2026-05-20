from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from bitrix.api import Bitrix24API
from pipelines.calls import user_name_map
from pipelines.deals import deal_id_from_report_row, deal_url_from_id, normalize_deal_filter_dates
from pipelines.stage_history import fetch_stage_name_map
from pipelines.stages import DEFAULT_STAGE_NAMES, safe_int, stage_display_name

from logging_setup import get_logger

logger = get_logger(__name__)


LOST_DEAL_SELECT = [
    "ID",
    "TITLE",
    "STAGE_ID",
    "STAGE_SEMANTIC_ID",
    "CATEGORY_ID",
    "DATE_CREATE",
    "DATE_MODIFY",
    "CLOSEDATE",
    "ASSIGNED_BY_ID",
    "OPPORTUNITY",
    "COMMENTS",
    "SOURCE_ID",
    "SOURCE_DESCRIPTION",
    "CONTACT_ID",
    "COMPANY_ID",
]

REASON_RULES: List[Tuple[str, str, List[str]]] = [
    (
        "Цена/бюджет",
        r"дорог|дороже|цена|стоим|прайс|бюджет|дешев|скидк|финанс|денег|оплат|сумм",
        [
            "ROI-калькулятор окупаемости",
            "скрипт ценности до обсуждения цены",
            "пакеты КП с базовым и расширенным вариантом",
        ],
    ),
    (
        "Нет связи с клиентом",
        r"не дозвон|не отвечает|нет связи|недоступ|молчит|не берет|не бер[её]т|перезвон|не выходит",
        [
            "регламент 6 касаний",
            "авто-задачи на повторный контакт",
            "шаблоны WhatsApp/email после пропущенного звонка",
        ],
    ),
    (
        "Нет потребности/не актуально",
        r"не актуаль|нет потребн|не нужно|не требуется|не интересно|отказ|передумал|без потреб",
        [
            "короткий квалификационный чек-лист",
            "карта болей клиента по сегментам",
            "цепочка прогрева для отложенного спроса",
        ],
    ),
    (
        "Конкурент или уже купили",
        r"конкур|друг(ой|ая|ие)|уже куп|купили|выбрали|поставщик|альтернатив|есть решение",
        [
            "battlecard по конкурентам",
            "таблица отличий и рисков текущего решения",
            "скрипт возврата к сравнению по ценности",
        ],
    ),
    (
        "Отложили решение",
        r"позже|потом|отлож|не сейчас|верн[её]мся|следующ|квартал|месяц|срок",
        [
            "план nurturing-касаний",
            "автоматическая задача на дату возврата",
            "мини-КП с фиксированным следующим шагом",
        ],
    ),
    (
        "Техническое несоответствие",
        r"функционал|интеграц|тех|не подходит|доработ|ошибка|невозмож|не можем|не умеет",
        [
            "пресейл-чеклист до КП",
            "реестр типовых технических ограничений",
            "быстрый маршрут эскалации в тех. пресейл",
        ],
    ),
    (
        "КП/счет/документы не доведены",
        r"\bкп\b|коммерческ|счет|сч[её]т|договор|документ|защита|презентац|предложени",
        [
            "шаблоны КП по сегментам",
            "контроль отправки КП и защиты КП",
            "авто-задача на follow-up после отправки счета",
        ],
    ),
    (
        "Проверка РОП/качество лида",
        r"\bроп\b|проверке роп|проверка роп|нецелев|мусор|фейк|спам",
        [
            "разбор источников лидов",
            "фильтр качества лида на входе",
            "обязательная причина отклонения перед переводом в проигрыш",
        ],
    ),
    (
        "Дубль/ошибка",
        r"дубл|дубликат|ошибоч|ошибка|возврат",
        [
            "правила дедупликации CRM",
            "проверка карточки перед началом работы",
            "автоматический контроль дублей",
        ],
    ),
]

DEFAULT_CONVERSION_TOOLS = [
    "обязательное поле причины проигрыша",
    "короткий разбор последнего контакта перед закрытием",
    "еженедельный разбор топ-3 причин отказов",
]


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _as_float(value: Any) -> float:
    try:
        return float(str(value or 0).replace(",", "."))
    except Exception:
        return 0.0


def _lifetime_days(deal: Dict[str, Any]) -> Optional[float]:
    created = _parse_dt(deal.get("DATE_CREATE"))
    closed = _parse_dt(deal.get("CLOSEDATE")) or _parse_dt(deal.get("DATE_MODIFY"))
    if not created or not closed:
        return None
    try:
        return round(max(0.0, (closed - created).total_seconds() / 86400.0), 2)
    except Exception:
        return None


def _stage_filter_keys() -> set[str]:
    return {"STAGE_ID", "=STAGE_ID", "@STAGE_ID", "!STAGE_ID", "!=STAGE_ID"}


def _infer_category_id(stage_value: Any) -> Optional[int]:
    values: Iterable[Any]
    if isinstance(stage_value, list):
        values = stage_value
    else:
        values = [stage_value]
    for value in values:
        match = re.match(r"^C(\d+):", str(value or ""))
        if match:
            return int(match.group(1))
    return None


def lost_filter_from_base(base_filter: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    removed_stage_value: Any = None
    for key, value in dict(base_filter or {}).items():
        if key in _stage_filter_keys():
            removed_stage_value = value
            continue
        if "STAGE_SEMANTIC_ID" in key:
            continue
        out[key] = value

    if "CATEGORY_ID" not in out:
        category_id = _infer_category_id(removed_stage_value)
        if category_id is not None:
            out["CATEGORY_ID"] = category_id

    out["=STAGE_SEMANTIC_ID"] = "F"
    return out


def _fallback_lost_stage_ids(category_id: Any = None) -> List[str]:
    category = safe_int(category_id)
    prefix = f"C{category}:" if category is not None and category > 0 else ""
    ids = []
    for stage_id, name in DEFAULT_STAGE_NAMES.items():
        lower_name = name.lower()
        if "проигран" not in lower_name and "возврат" not in lower_name:
            continue
        if prefix:
            if stage_id.startswith(prefix):
                ids.append(stage_id)
        elif ":" not in stage_id:
            ids.append(stage_id)
        elif stage_id.startswith("C1:"):
            ids.append(stage_id)
    return ids or ["LOSE"]


def _fallback_lost_filter(base_filter: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: v for k, v in dict(base_filter or {}).items() if k not in _stage_filter_keys()}
    out.pop("=STAGE_SEMANTIC_ID", None)
    out.pop("STAGE_SEMANTIC_ID", None)
    out["STAGE_ID"] = _fallback_lost_stage_ids(out.get("CATEGORY_ID"))
    return out


async def _fetch_deals_page(
    api: Bitrix24API,
    flt: Dict[str, Any],
    start: Optional[int],
) -> Dict[str, Any]:
    return await api.call(
        "crm.deal.list",
        {
            "filter": flt,
            "select": LOST_DEAL_SELECT,
            "order": {"DATE_MODIFY": "DESC", "ID": "DESC"},
            "start": start or 0,
        },
    )


async def fetch_lost_deals(api: Bitrix24API, flt: Dict[str, Any], limit: int = 500) -> List[Dict[str, Any]]:
    max_items = max(0, int(limit or 0))
    if max_items <= 0:
        return []

    async def fetch_with_filter(active_filter: Dict[str, Any]) -> List[Dict[str, Any]]:
        deals: List[Dict[str, Any]] = []
        start: Optional[int] = 0
        while start is not None and len(deals) < max_items:
            res = await _fetch_deals_page(api, active_filter, start)
            chunk = res.get("result", []) or []
            if not chunk:
                break
            deals.extend(chunk[: max_items - len(deals)])
            next_start = res.get("next")
            if next_start is None:
                break
            start = safe_int(next_start)
        return deals

    try:
        return await fetch_with_filter(flt)
    except Exception as e:
        fallback = _fallback_lost_filter(flt)
        logger.warning(f"[WARN] Не удалось получить проигранные сделки по STAGE_SEMANTIC_ID: {e}")
        logger.warning("[WARN] Пробую резервный фильтр по STAGE_ID проигрыша")
        return await fetch_with_filter(fallback)


def result_text_index(results: List[Dict[str, Any]]) -> Dict[str, str]:
    index: Dict[str, List[str]] = defaultdict(list)
    fields = [
        "conversation_meaning",
        "client_work_conclusion",
        "call_quality_conclusion",
        "objections_combined",
        "unhandled_objections",
        "objection_recommendations",
        "recommendations",
        "transcripts_combined",
        "transcript_text",
        "transcript_marked",
        "error",
    ]
    for row in results:
        deal_id = deal_id_from_report_row(row)
        if not deal_id:
            continue
        for field in fields:
            value = _clean_text(row.get(field))
            if value:
                index[deal_id].append(value)
    return {deal_id: " ".join(parts) for deal_id, parts in index.items()}


def _evidence_snippet(text: str, match: re.Match[str], radius: int = 90) -> str:
    start = max(0, match.start() - radius)
    end = min(len(text), match.end() + radius)
    return text[start:end].strip(" .;,\n\t")


def classify_loss_reason(text: str) -> Dict[str, Any]:
    clean = _clean_text(text)
    lowered = clean.lower()
    for category, pattern, tools in REASON_RULES:
        match = re.search(pattern, lowered, flags=re.IGNORECASE)
        if match:
            return {
                "loss_reason_category": category,
                "loss_reason_confidence": "Высокая",
                "loss_reason_evidence": _evidence_snippet(clean, match),
                "conversion_tools": "; ".join(tools),
                "conversion_next_action": conversion_next_action(category),
            }
    return {
        "loss_reason_category": "Причина не указана",
        "loss_reason_confidence": "Низкая",
        "loss_reason_evidence": "",
        "conversion_tools": "; ".join(DEFAULT_CONVERSION_TOOLS),
        "conversion_next_action": conversion_next_action("Причина не указана"),
    }


def conversion_next_action(category: str) -> str:
    actions = {
        "Цена/бюджет": "Проверить, была ли до цены показана выгода, окупаемость и альтернатива пакетами.",
        "Нет связи с клиентом": "Ввести контроль касаний: звонок, сообщение, письмо и задача на следующий контакт.",
        "Нет потребности/не актуально": "Усилить квалификацию на первом контакте и переводить неготовых клиентов в прогрев.",
        "Конкурент или уже купили": "Собрать причины выбора конкурента и обновить battlecard для менеджеров.",
        "Отложили решение": "Фиксировать дату возврата и следующий шаг в CRM, а не закрывать без плана касания.",
        "Техническое несоответствие": "Подключать тех. пресейл до КП и вести список типовых ограничений.",
        "КП/счет/документы не доведены": "Контролировать отправку КП, защиту КП и follow-up после счета.",
        "Проверка РОП/качество лида": "Разобрать источник лида и обязательную причину отклонения с РОП.",
        "Дубль/ошибка": "Настроить контроль дублей и убрать ошибочные карточки из конверсионной аналитики.",
    }
    return actions.get(category, "Добавить обязательную причину проигрыша и разбирать сделки без причины отдельно.")


def lost_deal_row(
    *,
    deal: Dict[str, Any],
    stage_map: Dict[str, str],
    manager_names: Dict[int, str],
    domain: str,
    extra_text: str,
) -> Dict[str, Any]:
    deal_id = str(deal.get("ID") or "").strip()
    stage_id = str(deal.get("STAGE_ID") or "").strip()
    manager_id = safe_int(deal.get("ASSIGNED_BY_ID"))
    stage_name = stage_display_name(stage_id, stage_map=stage_map)
    base_text = " ".join(
        [
            _clean_text(deal.get("TITLE")),
            stage_name,
            _clean_text(deal.get("COMMENTS")),
            _clean_text(deal.get("SOURCE_ID")),
            _clean_text(deal.get("SOURCE_DESCRIPTION")),
            _clean_text(extra_text),
        ]
    )
    reason = classify_loss_reason(base_text)
    row = {
        "lost_deal_url": deal_url_from_id(domain, deal_id) if deal_id else "",
        "lost_deal_title": _clean_text(deal.get("TITLE")),
        "lost_stage_name": stage_name,
        "lost_manager_name": manager_names.get(manager_id, str(manager_id or "")),
        "lost_amount": _as_float(deal.get("OPPORTUNITY")),
        "lost_date_create": deal.get("DATE_CREATE"),
        "lost_close_date": deal.get("CLOSEDATE") or deal.get("DATE_MODIFY"),
        "lost_lifetime_days": _lifetime_days(deal),
        "lost_source": _clean_text(deal.get("SOURCE_ID") or deal.get("SOURCE_DESCRIPTION")),
        "lost_analysis_basis": "CRM + звонки отчета" if extra_text else "CRM",
    }
    row.update(reason)
    return row


def build_lost_reason_summary(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    total = max(1, len(rows))
    by_reason: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_reason[str(row.get("loss_reason_category") or "Причина не указана")].append(row)

    out: List[Dict[str, Any]] = []
    for reason, reason_rows in sorted(by_reason.items(), key=lambda item: (-len(item[1]), item[0])):
        amount = round(sum(float(r.get("lost_amount") or 0.0) for r in reason_rows), 2)
        lifetime_values = [float(r["lost_lifetime_days"]) for r in reason_rows if r.get("lost_lifetime_days") is not None]
        manager_counts = Counter(str(r.get("lost_manager_name") or "") for r in reason_rows)
        tools = next((str(r.get("conversion_tools") or "") for r in reason_rows if r.get("conversion_tools")), "")
        action = conversion_next_action(reason)
        out.append(
            {
                "loss_reason_category": reason,
                "lost_deals_count": len(reason_rows),
                "lost_deals_share": round(len(reason_rows) / total * 100.0, 2),
                "lost_amount": amount,
                "lost_avg_lifetime_days": round(sum(lifetime_values) / len(lifetime_values), 2)
                if lifetime_values
                else None,
                "lost_top_managers": ", ".join([f"{name}: {count}" for name, count in manager_counts.most_common(3) if name]),
                "conversion_tools": tools,
                "conversion_next_action": action,
            }
        )
    return out


def build_conversion_action_rows(summary_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for index, row in enumerate(summary_rows, 1):
        share = float(row.get("lost_deals_share") or 0.0)
        count = int(row.get("lost_deals_count") or 0)
        if share >= 25 or count >= 10:
            priority = "Критично"
        elif share >= 10 or count >= 3:
            priority = "Высокий"
        else:
            priority = "Наблюдать"
        out.append(
            {
                "conversion_priority": priority,
                "conversion_rank": index,
                "loss_reason_category": row.get("loss_reason_category"),
                "lost_deals_count": row.get("lost_deals_count"),
                "lost_deals_share": row.get("lost_deals_share"),
                "conversion_tools": row.get("conversion_tools"),
                "conversion_next_action": row.get("conversion_next_action"),
                "conversion_expected_effect": expected_conversion_effect(str(row.get("loss_reason_category") or "")),
            }
        )
    return out


def expected_conversion_effect(category: str) -> str:
    effects = {
        "Цена/бюджет": "Больше сделок должны доходить до защиты ценности и альтернативного КП.",
        "Нет связи с клиентом": "Снижение потерь из-за недозвона и повышение доли повторных контактов.",
        "Нет потребности/не актуально": "Меньше времени на нецелевые сделки и больше прогрева для отложенного спроса.",
        "Конкурент или уже купили": "Выше шанс вернуть клиента в сравнение до финального отказа.",
        "Отложили решение": "Больше сделок останутся в контролируемом цикле касаний вместо закрытия без плана.",
        "Техническое несоответствие": "Меньше поздних отказов после КП за счет раннего пресейла.",
        "КП/счет/документы не доведены": "Больше оплат после КП за счет обязательного follow-up.",
    }
    return effects.get(category, "Повышение прозрачности причин проигрыша и качества управленческих решений.")


async def build_lost_deals_analysis(
    *,
    api: Bitrix24API,
    args: Any,
    results: List[Dict[str, Any]],
    stage_map: Dict[str, str],
) -> Dict[str, List[Dict[str, Any]]]:
    if not getattr(args, "lost_deals_analysis", False):
        return {"rows": [], "summary_rows": [], "action_rows": []}
    if getattr(args, "mode", None) != "filter" or not getattr(args, "filter_json", None):
        return {"rows": [], "summary_rows": [], "action_rows": []}

    try:
        base_filter = normalize_deal_filter_dates(json.loads(Path(args.filter_json).read_text(encoding="utf-8")))
    except Exception as e:
        logger.warning(f"[WARN] Не удалось прочитать фильтр для анализа проигранных сделок: {e}")
        return {"rows": [], "summary_rows": [], "action_rows": []}

    lost_filter = lost_filter_from_base(base_filter)
    limit = int(getattr(args, "lost_deals_limit", 500) or 500)
    logger.info(f"[LOST] Загружаю проигранные сделки для анализа отказов, лимит={limit}")
    deals = await fetch_lost_deals(api, lost_filter, limit=limit)
    if not deals:
        logger.info("[LOST] Проигранные сделки по текущим фильтрам не найдены")
        return {"rows": [], "summary_rows": [], "action_rows": []}

    lost_stage_ids = [str(deal.get("STAGE_ID") or "") for deal in deals if deal.get("STAGE_ID")]
    missing_stage_ids = [stage_id for stage_id in lost_stage_ids if stage_id and stage_id not in stage_map]
    if missing_stage_ids:
        try:
            stage_map = {**stage_map, **await fetch_stage_name_map(api, missing_stage_ids)}
        except Exception as e:
            logger.warning(f"[WARN] Не удалось загрузить названия стадий проигрыша: {e}")

    manager_ids = [safe_int(deal.get("ASSIGNED_BY_ID")) for deal in deals]
    manager_names = await user_name_map(
        api, [manager_id for manager_id in manager_ids if manager_id is not None]
    )
    text_index = result_text_index(results)
    domain = str(getattr(args, "domain", "") or "")
    rows = [
        lost_deal_row(
            deal=deal,
            stage_map=stage_map,
            manager_names=manager_names,
            domain=domain,
            extra_text=text_index.get(str(deal.get("ID") or ""), ""),
        )
        for deal in deals
    ]
    summary_rows = build_lost_reason_summary(rows)
    action_rows = build_conversion_action_rows(summary_rows)
    logger.info(f"[LOST] Проанализировано проигранных сделок: {len(rows)}")
    return {"rows": rows, "summary_rows": summary_rows, "action_rows": action_rows}
