from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
import secrets
import json
import os
import sqlite3

app = FastAPI(title="iABS - Учёт Аренды")

# Get absolute paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
DB_PATH = os.path.join(BASE_DIR, "approved_contracts.db")

def init_sqlite():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS approved_contracts (
            id               INTEGER PRIMARY KEY,
            contract_number  TEXT NOT NULL,
            contract_type    TEXT,
            counterparty     TEXT,
            lease_object     TEXT,
            start_date       TEXT,
            end_date         TEXT,
            memo_number      TEXT,
            created_by       TEXT,
            approved_by      TEXT,
            approved_at      TEXT,
            payment_type     TEXT,
            payment_deadline TEXT,
            final_status     TEXT DEFAULT 'APPROVED',
            payer            TEXT,
            payer_account    TEXT,
            payer_bank       TEXT,
            payer_mfo        TEXT,
            recipient        TEXT,
            recipient_account TEXT,
            recipient_bank   TEXT,
            recipient_mfo    TEXT,
            amount           REAL,
            currency         TEXT DEFAULT 'UZS',
            payment_purpose  TEXT,
            agreement_type   TEXT,
            lease_kind         TEXT,
            third_party        TEXT,
            payment_frequency  TEXT,
            payment_day        INTEGER,
            payments_made      INTEGER DEFAULT 0,
            amount_paid        REAL DEFAULT 0
        )
    """)
    # Add columns for existing databases that were created before this update
    new_cols = [
        ("payer", "TEXT"), ("payer_account", "TEXT"), ("payer_bank", "TEXT"),
        ("payer_mfo", "TEXT"), ("recipient", "TEXT"), ("recipient_account", "TEXT"),
        ("recipient_bank", "TEXT"), ("recipient_mfo", "TEXT"),
        ("amount", "REAL"), ("currency", "TEXT"), ("payment_purpose", "TEXT"),
        ("agreement_type", "TEXT"), ("lease_kind", "TEXT"), ("third_party", "TEXT"),
        ("payment_frequency", "TEXT"), ("payment_day", "INTEGER"),
        ("payments_made", "INTEGER"), ("amount_paid", "REAL"),
    ]
    for col, col_type in new_cols:
        try:
            conn.execute(f"ALTER TABLE approved_contracts ADD COLUMN {col} {col_type}")
        except Exception:
            pass
    conn.commit()
    conn.close()

init_sqlite()

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# In-memory database
users_db = {
    "00001": {"password": "admin123", "name": "Системный Администратор", "role": "SUPERADMIN", "status": "ACTIVE", "created_at": "2026-01-01T10:00:00"},
    "00002": {"password": "admin123", "name": "Иванов Иван Иванович", "role": "ADMIN", "status": "ACTIVE", "created_at": "2026-01-15T09:30:00"},
    "00003": {"password": "admin123", "name": "Петров Петр Петрович", "role": "CONTROLLER", "status": "ACTIVE", "created_at": "2026-02-01T14:20:00"},
    "00004": {"password": "admin123", "name": "Сидорова Анна Сергеевна", "role": "OPERATOR", "status": "ACTIVE", "created_at": "2026-02-10T11:45:00"},
}

# Role-based permissions
role_permissions = {
    "SUPERADMIN": {
        "add": True,
        "edit": True,
        "delete": True,
        "approve": True,
        "return": True,
        "payment": True,
        "protocol": True,
        "settings": True,
        "references_edit": True,
        "references_delete": True,
    },
    "ADMIN": {
        "add": True,
        "edit": True,
        "delete": True,
        "approve": True,
        "return": True,
        "payment": True,
        "protocol": True,
        "settings": False,
        "references_edit": True,
        "references_delete": True,
    },
    "CONTROLLER": {
        "add": True,
        "edit": True,
        "delete": False,
        "approve": True,
        "return": False,
        "payment": True,
        "protocol": True,
        "settings": False,
        "references_edit": True,
        "references_delete": False,
    },
    "OPERATOR": {
        "add": True,
        "edit": True,
        "delete": True,
        "approve": False,
        "return": False,
        "payment": False,
        "protocol": True,
        "settings": False,
        "references_edit": False,
        "references_delete": False,
    },
}

sessions = {}

contracts_db = []

# Read-only INN lookup reference (from counterparties.sql)
inn_lookup_db = [
    {"inn": "301234567", "name": 'OOO "Toshkent Savdo Markazi"', "kpp": "301001", "ogrn": "100123456", "address": "Toshkent sh., Chilonzor tumani, Bunyodkor ko'chasi 10", "bank_account": "20208000123456789001", "bank_name": "Asaka Bank", "bik": "ASAKAUZ22", "phone": "+998 71 123-45-67", "email": "info@tsm.uz"},
    {"inn": "302345678", "name": 'OOO "Samarqand Invest"',        "kpp": "302001", "ogrn": "100234567", "address": "Samarqand sh., Registon ko'chasi 5",                    "bank_account": "20208000123456789002", "bank_name": "Ipoteka Bank", "bik": "IPOTAUZ22", "phone": "+998 66 234-56-78", "email": "info@saminvest.uz"},
    {"inn": "303456789", "name": 'OOO "Buxoro Trade"',             "kpp": "303001", "ogrn": "100345678", "address": "Buxoro sh., Mustaqillik ko'chasi 7",                   "bank_account": "20208000123456789003", "bank_name": "Agrobank",     "bik": "AGROUZ22",  "phone": "+998 65 345-67-89", "email": "contact@buxtrade.uz"},
    {"inn": "304567890", "name": "OOO \"Farg'ona Logistika\"",     "kpp": "304001", "ogrn": "100456789", "address": "Farg'ona sh., Alisher Navoiy ko'chasi 12",             "bank_account": "20208000123456789004", "bank_name": "Xalq Banki",   "bik": "XALQUZ22",  "phone": "+998 73 456-78-90", "email": "info@flog.uz"},
    {"inn": "305678901", "name": 'OOO "Namangan Textile"',         "kpp": "305001", "ogrn": "100567890", "address": "Namangan sh., Bobur ko'chasi 3",                      "bank_account": "20208000123456789005", "bank_name": "Hamkorbank",   "bik": "HAMKUZ22",  "phone": "+998 69 567-89-01", "email": "info@namtex.uz"},
    {"inn": "306789012", "name": 'OOO "Andijon Qurilish"',         "kpp": "306001", "ogrn": "100678901", "address": "Andijon sh., Amir Temur ko'chasi 9",                  "bank_account": "20208000123456789006", "bank_name": "Kapitalbank",  "bik": "KAPAUZ22",  "phone": "+998 74 678-90-12", "email": "contact@andbuild.uz"},
    {"inn": "307890123", "name": 'OOO "Navoiy Mining Service"',    "kpp": "307001", "ogrn": "100789012", "address": "Navoiy sh., Konchilar ko'chasi 15",                   "bank_account": "20208000123456789007", "bank_name": "NBU",          "bik": "NBUZUZ22",  "phone": "+998 79 789-01-23", "email": "info@navmin.uz"},
    {"inn": "308901234", "name": 'OOO "Qarshi Agro"',              "kpp": "308001", "ogrn": "100890123", "address": "Qarshi sh., Nasaf ko'chasi 4",                        "bank_account": "20208000123456789008", "bank_name": "Agrobank",     "bik": "AGROUZ22",  "phone": "+998 75 890-12-34", "email": "info@qarshiagro.uz"},
    {"inn": "309012345", "name": 'OOO "Termiz Logistics"',         "kpp": "309001", "ogrn": "100901234", "address": "Termiz sh., Alpomish ko'chasi 6",                     "bank_account": "20208000123456789009", "bank_name": "Asaka Bank",   "bik": "ASAKAUZ22", "phone": "+998 76 901-23-45", "email": "info@terlog.uz"},
    {"inn": "310123456", "name": 'OOO "Urganch Savdo"',            "kpp": "310001", "ogrn": "101012345", "address": "Urganch sh., Xiva yo'li 2",                           "bank_account": "20208000123456789010", "bank_name": "Ipoteka Bank", "bik": "IPOTAUZ22", "phone": "+998 62 012-34-56", "email": "info@urgsavdo.uz"},
    {"inn": "311234567", "name": 'OOO "Nukus Service"',            "kpp": "311001", "ogrn": "101123456", "address": "Nukus sh., Beruniy ko'chasi 11",                      "bank_account": "20208000123456789011", "bank_name": "Xalq Banki",   "bik": "XALQUZ22",  "phone": "+998 61 123-45-67", "email": "info@nukusserv.uz"},
    {"inn": "312345678", "name": 'OOO "Jizzax Cement"',            "kpp": "312001", "ogrn": "101234567", "address": "Jizzax sh., Mustaqillik ko'chasi 8",                  "bank_account": "20208000123456789012", "bank_name": "Kapitalbank",  "bik": "KAPAUZ22",  "phone": "+998 72 234-56-78", "email": "info@jizcement.uz"},
    {"inn": "313456789", "name": 'OOO "Guliston Agro Trade"',      "kpp": "313001", "ogrn": "101345678", "address": "Guliston sh., Shodlik ko'chasi 5",                    "bank_account": "20208000123456789013", "bank_name": "Agrobank",     "bik": "AGROUZ22",  "phone": "+998 67 345-67-89", "email": "info@gulagro.uz"},
    {"inn": "314567890", "name": 'OOO "Toshkent IT Park Service"', "kpp": "314001", "ogrn": "101456789", "address": "Toshkent sh., Yunusobod tumani, IT Park 1",           "bank_account": "20208000123456789014", "bank_name": "TBC Bank",     "bik": "TBCBUZ22",  "phone": "+998 71 456-78-90", "email": "info@itpark.uz"},
    {"inn": "315678901", "name": 'OOO "Chirchiq Metall"',          "kpp": "315001", "ogrn": "101567890", "address": "Chirchiq sh., Metallurglar ko'chasi 3",               "bank_account": "20208000123456789015", "bank_name": "Asaka Bank",   "bik": "ASAKAUZ22", "phone": "+998 70 567-89-01", "email": "info@chirmet.uz"},
]

# Working directory — starts empty, populated by admin
counterparties_db = []

contract_types_db = [
    {"id": 1, "name": "Аренда офиса", "code": "OFFICE", "status": "ACTIVE"},
    {"id": 2, "name": "Аренда склада", "code": "WAREHOUSE", "status": "ACTIVE"},
    {"id": 3, "name": "Аренда торговой площади", "code": "RETAIL", "status": "ACTIVE"},
]

audit_log = []
suspicious_ops = []

memo_counter = 1

# ── Suspicious-operations detector ────────────────────────────────────────────
def check_suspicious(entry: dict):
    reasons = []
    risk = "MEDIUM"
    ts = datetime.fromisoformat(entry["timestamp"])

    # Rule 1: Late-night / off-hours (22:00 – 06:00)
    if ts.hour >= 22 or ts.hour < 6:
        reasons.append(f"🌙 Операция в нерабочее время — {ts.strftime('%H:%M')}")
        risk = "HIGH"

    # Rule 2: Rapid contract changes (≥3 create/update/delete in 10 min by same user)
    if entry["action"] in ("CREATE", "UPDATE", "DELETE") and entry["entity_type"] == "CONTRACT":
        cutoff = (ts - timedelta(minutes=10)).isoformat()
        burst = [l for l in audit_log
                 if l["user_id"] == entry["user_id"]
                 and l["action"] in ("CREATE", "UPDATE", "DELETE")
                 and l["entity_type"] == "CONTRACT"
                 and l["timestamp"] >= cutoff]
        if len(burst) >= 3:
            reasons.append(f"⚡ Серия изменений: {len(burst)} операций за 10 мин.")
            risk = "HIGH"

    # Rule 3: Mass deletion (≥2 deletes in 5 min)
    if entry["action"] == "DELETE":
        cutoff5 = (ts - timedelta(minutes=5)).isoformat()
        dels = [l for l in audit_log
                if l["user_id"] == entry["user_id"]
                and l["action"] == "DELETE"
                and l["timestamp"] >= cutoff5]
        if len(dels) >= 2:
            reasons.append(f"🗑️ Массовое удаление: {len(dels)} за 5 мин.")
            risk = "CRITICAL"

    # Rule 4: Multiple logins from different IPs in 15 min
    if entry["action"] == "LOGIN":
        cutoff15 = (ts - timedelta(minutes=15)).isoformat()
        recent_logins = [l for l in audit_log
                         if l["user_id"] == entry["user_id"]
                         and l["action"] == "LOGIN"
                         and l["timestamp"] >= cutoff15]
        ips = set(l.get("ip_address", "") for l in recent_logins if l.get("ip_address"))
        if len(ips) >= 2:
            reasons.append(f"🔑 Вход с разных IP: {', '.join(sorted(ips))}")
            risk = "HIGH"
        elif len(recent_logins) >= 5:
            reasons.append(f"🔑 Частые входы: {len(recent_logins)} за 15 мин.")

    # Rule 5: Large-amount contract approved (≥50M UZS)
    if entry["action"] == "APPROVE" and entry.get("new_value"):
        try:
            d = json.loads(entry["new_value"])
            amt = d.get("amount") or 0
            cur = d.get("currency", "UZS")
            threshold = 50_000_000 if cur == "UZS" else 50_000
            if amt >= threshold:
                reasons.append(f"💰 Крупная сумма: {amt:,.0f} {cur}")
                risk = "HIGH"
        except Exception:
            pass

    # Rule 6: Bank-account details changed (potential fraud)
    if entry["action"] == "UPDATE" and entry.get("old_value") and entry.get("new_value"):
        try:
            old_d = json.loads(entry["old_value"])
            new_d = json.loads(entry["new_value"])
            bank_fields = ["payer_account", "recipient_account", "payer_bank", "recipient_bank", "payer_mfo", "recipient_mfo"]
            changed = [f for f in bank_fields if old_d.get(f) and old_d.get(f) != new_d.get(f)]
            if changed:
                reasons.append(f"🏦 Изменение банковских реквизитов: {', '.join(changed)}")
                risk = "HIGH"
        except Exception:
            pass

    if not reasons:
        return

    # Deduplication — skip if same user got the same type of alert in last 5 min
    dedup_cutoff = (ts - timedelta(minutes=5)).isoformat()
    for existing_susp in suspicious_ops:
        if (existing_susp["user_id"] == entry["user_id"]
                and existing_susp["timestamp"] >= dedup_cutoff
                and any(r in existing_susp["reasons"] for r in reasons)):
            return

    suspicious_ops.append({
        "id": len(suspicious_ops) + 1,
        "timestamp": entry["timestamp"],
        "user_id": entry["user_id"],
        "user_name": entry["user_name"],
        "action": entry["action"],
        "entity_type": entry["entity_type"],
        "entity_id": entry["entity_id"],
        "ip_address": entry.get("ip_address", "—"),
        "reasons": reasons,
        "risk_level": risk,
        "acknowledged": False,
    })

# ── Amount-to-words (Russian) ──────────────────────────────────────────────
_ONES_M = ["", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять",
           "десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать",
           "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать"]
_ONES_F = ["", "одна", "две", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять",
           "десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать",
           "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать"]
_TENS   = ["", "", "двадцать", "тридцать", "сорок", "пятьдесят",
           "шестьдесят", "семьдесят", "восемьдесят", "девяносто"]
_HUNDS  = ["", "сто", "двести", "триста", "четыреста", "пятьсот",
           "шестьсот", "семьсот", "восемьсот", "девятьсот"]

def _plural_ru(n: int, one: str, few: str, many: str) -> str:
    n = abs(n) % 100
    n1 = n % 10
    if 11 <= n <= 14:
        return many
    if n1 == 1:
        return one
    if 2 <= n1 <= 4:
        return few
    return many

def _chunk_words(n: int, feminine: bool = False) -> list:
    if not n:
        return []
    res = []
    h, rem = divmod(n, 100)
    if h:
        res.append(_HUNDS[h])
    ones = _ONES_F if feminine else _ONES_M
    if rem < 20:
        if ones[rem]:
            res.append(ones[rem])
    else:
        t, o = divmod(rem, 10)
        res.append(_TENS[t])
        if ones[o]:
            res.append(ones[o])
    return res

def amount_to_words(amount: float, currency: str = "UZS") -> str:
    if amount is None:
        return ""
    whole = int(amount)
    frac  = round((amount - whole) * 100)
    _CURR = {
        "UZS": (("сум",    "сума",    "сумов"),    ("тийин",  "тийина",  "тийинов")),
        "USD": (("доллар", "доллара", "долларов"), ("цент",   "цента",   "центов")),
        "EUR": (("евро",   "евро",    "евро"),     ("цент",   "цента",   "центов")),
        "RUB": (("рубль",  "рубля",   "рублей"),   ("копейка","копейки", "копеек")),
    }
    mn, fn = _CURR.get(currency, (("единица","единицы","единиц"),("сотая","сотых","сотых")))
    parts = []
    if whole == 0:
        parts = ["ноль"]
    else:
        bn, r  = divmod(whole, 1_000_000_000)
        ml, r  = divmod(r,     1_000_000)
        th, r  = divmod(r,     1_000)
        if bn: parts += _chunk_words(bn);       parts.append(_plural_ru(bn, "миллиард",  "миллиарда",  "миллиардов"))
        if ml: parts += _chunk_words(ml);       parts.append(_plural_ru(ml, "миллион",   "миллиона",   "миллионов"))
        if th: parts += _chunk_words(th, True); parts.append(_plural_ru(th, "тысяча",    "тысячи",     "тысяч"))
        if r:  parts += _chunk_words(r)
    text = " ".join(parts).strip()
    text = text[0].upper() + text[1:]
    text += f" {_plural_ru(whole, *mn)}"
    if frac:
        text += f" {frac:02d} {_plural_ru(frac, *fn)}"
    return text

problem_context = {
    "title": "Проблема, которую решает iABS",
    "introduction": {
        "overview": "В банке процесс учета аренды основных средств и объектов недвижимости до сих пор ведется разрозненно, вручную и без единого центра управления. Информация хранится в Excel-файлах, локальных таблицах, бумажных документах и переписках между отделами.",
        "practical_implication": "На практике это означает, что один и тот же объект может быть отражен в нескольких файлах по-разному. Любое изменение требует ручной проверки и повторного ввода, что увеличивает риск ошибок и делает процесс очень медленным.",
    },
    "pain_points": [
        {
            "id": 1,
            "title": "Нет единой системы учета",
            "sources": ["Excel-файлы у разных сотрудников", "бумажные договоры и приложения", "отдельные почтовые сообщения", "локальные заметки или внутренние документы"],
            "consequence": "Никто не может быстро ответить: какие договоры активны, кто за них отвечает, какие платежи должны быть произведены.",
        },
        {
            "id": 2,
            "title": "Ручной ввод создает финансовые ошибки",
            "typical_errors": ["двойной учет одного и того же договора", "пропущенные платежи", "неправильные суммы аренды", "неверные реквизиты контрагента", "ошибки в сроках действия договора"],
            "bank_specific_consequences": ["переплата", "недополучение аренды", "неверная отчетность", "финансовые потери", "претензии со стороны проверок"],
        },
        {
            "id": 3,
            "title": "Нет прозрачного контроля и аудита",
            "unknown_actions": ["кто создал запись", "кто изменил договор", "кто поменял реквизиты", "когда именно было внесено изменение"],
            "audit_trail_note": "Отсутствует audit trail — история всех действий.",
        },
        {
            "id": 4,
            "title": "Нет разграничения доступа по ролям",
            "risks": ["случайное удаление важных данных", "изменение договора неуполномоченным пользователем", "внесение изменений без согласования"],
        },
        {
            "id": 5,
            "title": "Слишком много ручной работы при вводе данных",
            "manual_steps": ["сам искать данные", "сам проверять ИНН", "сам вводить название", "сам заполнять адрес", "сам вносить банковские реквизиты"],
            "conclusion": "Ввод ИНН с автоматическим подтягиванием данных убирает ручной ввод из самого уязвимого участка процесса.",
        },
    ],
    "why_bank_specific": {
        "requirements": ["точность", "прозрачность", "соблюдение регламентов", "защита от ошибок и злоупотреблений", "проверяемость действий", "актуальность данных"],
        "bank_risks": ["потеря денег", "неверная отчетность", "нарушение внутренних правил", "замечания при проверках", "конфликты между подразделениями"],
    },
    "current_obstacles": [
        {"type": "Операционная проблема",   "description": "Сотрудники тратят много времени на поиск, проверку и перенос данных."},
        {"type": "Финансовая проблема",      "description": "Ошибки в расчетах и дублирование записей ведут к прямым потерям."},
        {"type": "Контрольная проблема",     "description": "Нет прозрачности, нет истории изменений, нет полного отслеживания действий."},
        {"type": "Комплаенс проблема",       "description": "Нет разграничения прав, нет уверенности, что данные меняются только уполномоченными людьми."},
    ],
    "solution_value": {
        "components": ["единая база данных", "автоматическое заполнение по ИНН", "контроль ролей", "история всех действий", "стандартизация процесса учета аренды"],
        "conclusion": "iABS убирает ручной хаос и превращает процесс в управляемый, проверяемый и безопасный.",
    },
    "presentation_statement": (
        "Банк управляет арендой основных средств вручную, без единой системы учета, без прозрачного аудита "
        "и без разграничения прав доступа. Данные разрознены по Excel и бумажным документам, что приводит к "
        "дублированию, ошибкам в расчетах, потере контроля над изменениями и рискам финансовых нарушений. "
        "Сотрудники вынуждены вручную вводить и проверять реквизиты контрагентов, что замедляет работу и "
        "повышает вероятность ошибок."
    ),
}

# Models
class LoginRequest(BaseModel):
    personnel_number: str
    password: str

class ContractRequest(BaseModel):
    contract_number: str
    contract_type: str
    counterparty: str
    lease_object: str
    start_date: str
    end_date: str
    # Payment details
    payer: Optional[str] = None
    payer_account: Optional[str] = None
    payer_bank: Optional[str] = None
    payer_mfo: Optional[str] = None
    recipient: Optional[str] = None
    recipient_account: Optional[str] = None
    recipient_bank: Optional[str] = None
    recipient_mfo: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = "UZS"
    payment_purpose: Optional[str] = None
    agreement_type: Optional[str] = None
    lease_kind: Optional[str] = None
    third_party: Optional[str] = None
    payment_frequency: Optional[str] = None
    payment_day: Optional[int] = None

class CounterpartyRequest(BaseModel):
    name: str
    inn: str
    type: str

class PaymentRequest(BaseModel):
    payment_type: str

class EmployeeRequest(BaseModel):
    personnel_number: str
    name: str
    password: str
    role: str

class PermissionUpdateRequest(BaseModel):
    role: str
    permission: str
    value: bool

class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str

class CounterpartyUpdateRequest(BaseModel):
    name: str
    inn: str
    type: str
    bank_account: str
    unique_code: str
    address: str
    phone: str
    status: str
    kpp: Optional[str] = None
    ogrn: Optional[str] = None
    bank_name: Optional[str] = None
    bik: Optional[str] = None
    email: Optional[str] = None

class ContractTypeRequest(BaseModel):
    name: str
    code: str
    status: str

# Auth helpers
def get_current_user(request: Request):
    token = request.cookies.get("session_token")
    if not token or token not in sessions:
        return None
    return sessions[token]

def require_auth(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user

def log_action(user_id: str, action: str, entity_type: str, entity_id: int,
               old_value=None, new_value=None, ip_address: str = "—"):
    entry = {
        "id": len(audit_log) + 1,
        "user_id": user_id,
        "user_name": users_db.get(user_id, {}).get("name", user_id),
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "old_value": json.dumps(old_value, ensure_ascii=False) if old_value else None,
        "new_value": json.dumps(new_value, ensure_ascii=False) if new_value else None,
        "timestamp": datetime.now().isoformat(),
        "ip_address": ip_address,
    }
    audit_log.append(entry)
    check_suspicious(entry)

# Routes - Pages
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")
    return RedirectResponse(url="/lease-out")

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")

@app.get("/lease-out", response_class=HTMLResponse)
async def lease_out_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(request=request, name="lease_out.html", context={"user": user})

@app.get("/lease-in", response_class=HTMLResponse)
async def lease_in_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(request=request, name="lease_in.html", context={"user": user})

@app.get("/references", response_class=HTMLResponse)
async def references_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(request=request, name="references.html", context={"user": user})

@app.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(request=request, name="profile.html", context={"user": user})

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")
    if user["role"] != "SUPERADMIN":
        raise HTTPException(status_code=403, detail="Access denied")
    return templates.TemplateResponse(request=request, name="settings.html", context={"user": user})

@app.get("/audit", response_class=HTMLResponse)
async def audit_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")
    if user["role"] not in ["SUPERADMIN", "ADMIN"]:
        raise HTTPException(status_code=403, detail="Access denied")
    return templates.TemplateResponse(request=request, name="audit.html", context={"user": user})

@app.get("/memo/{contract_id}", response_class=HTMLResponse)
async def memo_page(contract_id: int, request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")

    # Try in-memory first, then SQLite (survives server restart)
    contract = next(
        (c for c in contracts_db if c["id"] == contract_id and not c.get("is_deleted", False)),
        None
    )
    if not contract:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM approved_contracts WHERE id = ?", (contract_id,)).fetchone()
        conn.close()
        if row:
            contract = dict(row)
        else:
            raise HTTPException(status_code=404, detail="Договор не найден")

    status = contract.get("status") or contract.get("final_status", "")
    if status not in ("APPROVED", "RETURNED"):
        raise HTTPException(status_code=400, detail="Мемориальный ордер доступен только для утверждённых договоров")

    maker_pn   = contract.get("created_by") or ""
    checker_pn = contract.get("approved_by") or ""
    maker_name   = users_db.get(maker_pn,   {}).get("name", maker_pn   or "—")
    checker_name = users_db.get(checker_pn, {}).get("name", checker_pn or "—")

    months_ru = ["января","февраля","марта","апреля","мая","июня",
                 "июля","августа","сентября","октября","ноября","декабря"]
    try:
        dt = datetime.fromisoformat(contract.get("approved_at") or datetime.now().isoformat())
    except Exception:
        dt = datetime.now()
    date_formatted = f'«{dt.day:02d}» {months_ru[dt.month - 1]} {dt.year} г.'

    amt      = contract.get("amount")
    currency = contract.get("currency") or "UZS"
    amount_words     = amount_to_words(amt, currency) if amt else ""
    amount_formatted = f"{amt:,.2f}".replace(",", " ") if amt else "—"

    purpose = contract.get("payment_purpose") or (
        f"Ijara shartnomasi № {contract.get('contract_number','—')} "
        f"bo'yicha asosiy vositalarni hisobga olish / berish"
    )

    return templates.TemplateResponse(
        request=request,
        name="memo.html",
        context={
            "contract":         contract,
            "date_formatted":   date_formatted,
            "amount_words":     amount_words,
            "amount_formatted": amount_formatted,
            "payment_purpose":  purpose,
            "maker_name":       maker_name,
            "checker_name":     checker_name,
            "system_log_id":    f"SYSTEM_LOG_{contract_id:08d}",
            "currency":         currency,
        }
    )

@app.get("/posting/{contract_id}", response_class=HTMLResponse)
async def posting_page(contract_id: int, request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")

    contract = next(
        (c for c in contracts_db if c["id"] == contract_id and not c.get("is_deleted", False)),
        None
    )
    if not contract:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM approved_contracts WHERE id = ?", (contract_id,)).fetchone()
        conn.close()
        if row:
            contract = dict(row)
        else:
            raise HTTPException(status_code=404, detail="Договор не найден")

    months_ru = ["января","февраля","марта","апреля","мая","июня",
                 "июля","августа","сентября","октября","ноября","декабря"]
    try:
        dt = datetime.fromisoformat(contract.get("approved_at") or datetime.now().isoformat())
    except Exception:
        dt = datetime.now()
    date_formatted = f'«{dt.day:02d}» {months_ru[dt.month - 1]} {dt.year} г.'

    amt = contract.get("amount")
    currency = contract.get("currency") or "UZS"
    amount_formatted = f"{amt:,.2f}".replace(",", " ") if amt else "—"
    amount_words = amount_to_words(amt, currency) if amt else ""

    return templates.TemplateResponse(
        request=request,
        name="posting.html",
        context={
            "contract": contract,
            "date_formatted": date_formatted,
            "amount_formatted": amount_formatted,
            "amount_words": amount_words,
            "currency": currency,
        }
    )

# API - Auth
@app.post("/api/login")
async def login(login_req: LoginRequest, request: Request):
    user = users_db.get(login_req.personnel_number)
    if not user or user["password"] != login_req.password:
        raise HTTPException(status_code=401, detail="Неверный табельный номер или пароль")

    ip = request.client.host if request.client else "—"
    token = secrets.token_urlsafe(32)
    sessions[token] = {
        "personnel_number": login_req.personnel_number,
        "name": user["name"],
        "role": user["role"],
        "ip_address": ip,
    }

    log_action(login_req.personnel_number, "LOGIN", "SESSION", 0, ip_address=ip)

    return {"token": token, "user": sessions[token]}

@app.post("/api/logout")
async def logout(request: Request):
    token = request.cookies.get("session_token")
    if token in sessions:
        user_info = sessions[token]
        log_action(user_info["personnel_number"], "LOGOUT", "SESSION", 0,
                   ip_address=user_info.get("ip_address", "—"))
        del sessions[token]
    return {"success": True}

@app.get("/api/me")
async def get_me(user: dict = Depends(require_auth)):
    user_data = users_db.get(user["personnel_number"])
    return {
        "personnel_number": user["personnel_number"],
        "name": user["name"],
        "role": user["role"],
        "status": user_data.get("status", "ACTIVE"),
        "created_at": user_data.get("created_at", "2026-01-01T00:00:00")
    }

# API - Contracts
@app.get("/api/contracts")
async def get_contracts(
    contract_type: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    user: dict = Depends(require_auth)
):
    filtered = [c for c in contracts_db if not c.get("is_deleted", False)]

    if contract_type:
        filtered = [c for c in filtered if c["contract_type"] == contract_type]
    if status:
        filtered = [c for c in filtered if c["status"] == status]
    if search:
        search_lower = search.lower()
        filtered = [c for c in filtered if
                   search_lower in c["contract_number"].lower() or
                   search_lower in c["counterparty"].lower() or
                   search_lower in c["lease_object"].lower()]

    return filtered

@app.post("/api/contracts")
async def create_contract(contract: ContractRequest, user: dict = Depends(require_auth)):
    if user["role"] not in ["SUPERADMIN", "ADMIN", "OPERATOR"]:
        raise HTTPException(status_code=403, detail="Нет прав для создания")

    new_id = max([c["id"] for c in contracts_db], default=0) + 1
    new_contract = {
        "id": new_id,
        "contract_number": contract.contract_number,
        "contract_type": contract.contract_type,
        "counterparty": contract.counterparty,
        "lease_object": contract.lease_object,
        "start_date": contract.start_date,
        "end_date": contract.end_date,
        "status": "DRAFT",
        "memo_number": None,
        "created_by": user["personnel_number"],
        "approved_by": None,
        "created_at": datetime.now().isoformat(),
        "is_deleted": False,
        "payment_type": None,
        "payment_deadline": None,
        "payer": contract.payer,
        "payer_account": contract.payer_account,
        "payer_bank": contract.payer_bank,
        "payer_mfo": contract.payer_mfo,
        "recipient": contract.recipient,
        "recipient_account": contract.recipient_account,
        "recipient_bank": contract.recipient_bank,
        "recipient_mfo": contract.recipient_mfo,
        "amount": contract.amount,
        "currency": contract.currency or "UZS",
        "payment_purpose": contract.payment_purpose,
        "agreement_type": contract.agreement_type,
        "lease_kind": contract.lease_kind,
        "third_party": contract.third_party,
        "payment_frequency": contract.payment_frequency,
        "payment_day": contract.payment_day,
        "payments_made": 0,
        "amount_paid": 0.0,
    }
    contracts_db.append(new_contract)
    log_action(user["personnel_number"], "CREATE", "CONTRACT", new_id, None, new_contract, ip_address=user.get("ip_address","—"))
    return new_contract

@app.put("/api/contracts/{contract_id}")
async def update_contract(contract_id: int, contract: ContractRequest, user: dict = Depends(require_auth)):
    if user["role"] not in ["SUPERADMIN", "ADMIN", "OPERATOR"]:
        raise HTTPException(status_code=403, detail="Нет прав для изменения")

    existing = next((c for c in contracts_db if c["id"] == contract_id and not c.get("is_deleted", False)), None)
    if not existing:
        raise HTTPException(status_code=404, detail="Договор не найден")

    if existing["status"] != "DRAFT":
        raise HTTPException(status_code=400, detail="Можно изменять только черновики")

    old_value = existing.copy()
    existing.update({
        "counterparty": contract.counterparty,
        "lease_object": contract.lease_object,
        "start_date": contract.start_date,
        "end_date": contract.end_date,
        "payer": contract.payer,
        "payer_account": contract.payer_account,
        "payer_bank": contract.payer_bank,
        "payer_mfo": contract.payer_mfo,
        "recipient": contract.recipient,
        "recipient_account": contract.recipient_account,
        "recipient_bank": contract.recipient_bank,
        "recipient_mfo": contract.recipient_mfo,
        "amount": contract.amount,
        "currency": contract.currency or "UZS",
        "payment_purpose": contract.payment_purpose,
        "agreement_type": contract.agreement_type,
        "lease_kind": contract.lease_kind,
        "third_party": contract.third_party,
        "payment_frequency": contract.payment_frequency,
        "payment_day": contract.payment_day,
    })
    log_action(user["personnel_number"], "UPDATE", "CONTRACT", contract_id, old_value, existing, ip_address=user.get("ip_address","—"))
    return existing

@app.delete("/api/contracts/{contract_id}")
async def delete_contract(contract_id: int, user: dict = Depends(require_auth)):
    if user["role"] not in ["SUPERADMIN", "ADMIN", "OPERATOR"]:
        raise HTTPException(status_code=403, detail="Нет прав для удаления")

    existing = next((c for c in contracts_db if c["id"] == contract_id and not c.get("is_deleted", False)), None)
    if not existing:
        raise HTTPException(status_code=404, detail="Договор не найден")

    if existing["status"] != "DRAFT":
        raise HTTPException(status_code=400, detail="Можно удалять только черновики")

    old_value = existing.copy()
    existing["is_deleted"] = True
    log_action(user["personnel_number"], "DELETE", "CONTRACT", contract_id, old_value, existing, ip_address=user.get("ip_address","—"))
    return {"success": True}

@app.post("/api/contracts/{contract_id}/approve")
async def approve_contract(contract_id: int, user: dict = Depends(require_auth)):
    if user["role"] not in ["SUPERADMIN", "ADMIN", "CONTROLLER"]:
        raise HTTPException(status_code=403, detail="Нет прав для утверждения")

    existing = next((c for c in contracts_db if c["id"] == contract_id and not c.get("is_deleted", False)), None)
    if not existing:
        raise HTTPException(status_code=404, detail="Договор не найден")

    if existing["status"] != "DRAFT":
        raise HTTPException(status_code=400, detail="Можно утверждать только черновики")

    if existing["created_by"] == user["personnel_number"]:
        raise HTTPException(status_code=400, detail="Нельзя утверждать свой договор")

    global memo_counter
    old_value = existing.copy()
    approved_at = datetime.now().isoformat()
    existing["status"] = "APPROVED"
    existing["memo_number"] = f"MEMO-2026-{memo_counter:05d}"
    existing["approved_by"] = user["personnel_number"]
    existing["approved_at"] = approved_at
    memo_counter += 1

    _ip = user.get("ip_address", "—")
    log_action(user["personnel_number"], "APPROVE", "CONTRACT", contract_id, old_value, existing, ip_address=_ip)
    log_action(user["personnel_number"], "POSTING", "CONTRACT", contract_id, None, {
        "contract_number": existing["contract_number"],
        "debet": existing.get("payer_account") or "—",
        "kredit": existing.get("recipient_account") or "—",
        "payer": existing.get("payer") or "—",
        "recipient": existing.get("recipient") or "—",
        "amount": existing.get("amount"),
        "currency": existing.get("currency", "UZS"),
    }, ip_address=_ip)

    # Persist to SQLite permanently
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT OR REPLACE INTO approved_contracts
        (id, contract_number, contract_type, counterparty, lease_object,
         start_date, end_date, memo_number, created_by, approved_by,
         approved_at, payment_type, payment_deadline, final_status,
         payer, payer_account, payer_bank, payer_mfo,
         recipient, recipient_account, recipient_bank, recipient_mfo,
         amount, currency, payment_purpose, agreement_type, lease_kind, third_party,
         payment_frequency, payment_day)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        existing["id"], existing["contract_number"], existing["contract_type"],
        existing["counterparty"], existing["lease_object"],
        existing["start_date"], existing["end_date"], existing["memo_number"],
        existing["created_by"], existing["approved_by"], datetime.now().isoformat(),
        existing.get("payment_type"), existing.get("payment_deadline"), "APPROVED",
        existing.get("payer"), existing.get("payer_account"),
        existing.get("payer_bank"), existing.get("payer_mfo"),
        existing.get("recipient"), existing.get("recipient_account"),
        existing.get("recipient_bank"), existing.get("recipient_mfo"),
        existing.get("amount"), existing.get("currency", "UZS"),
        existing.get("payment_purpose"), existing.get("agreement_type"),
        existing.get("lease_kind"), existing.get("third_party"),
        existing.get("payment_frequency"), existing.get("payment_day"),
    ))
    conn.commit()
    conn.close()

    return existing

@app.post("/api/contracts/{contract_id}/return")
async def return_contract(contract_id: int, user: dict = Depends(require_auth)):
    if user["role"] not in ["SUPERADMIN", "ADMIN"]:
        raise HTTPException(status_code=403, detail="Нет прав для возврата")

    existing = next((c for c in contracts_db if c["id"] == contract_id and not c.get("is_deleted", False)), None)
    if not existing:
        raise HTTPException(status_code=404, detail="Договор не найден")

    if existing["status"] != "APPROVED":
        raise HTTPException(status_code=400, detail="Можно возвращать только утверждённые договоры")

    old_value = existing.copy()
    existing["status"] = "RETURNED"

    log_action(user["personnel_number"], "RETURN", "CONTRACT", contract_id, old_value, existing, ip_address=user.get("ip_address","—"))

    # Update final_status in SQLite — row stays, just marked as RETURNED
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE approved_contracts SET final_status = 'RETURNED' WHERE id = ?",
        (contract_id,)
    )
    conn.commit()
    conn.close()

    return existing

def _add_months(d, months: int):
    import calendar
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    from datetime import date
    return date(year, month, day)

def _next_payment_date(start_str: str, freq: str, day: int, index: int) -> str:
    """Return ISO date of the (index)-th payment (0 = first)."""
    from datetime import date as dt_date
    try:
        start = dt_date.fromisoformat(start_str)
        safe_day = min(max(int(day), 1), 28)
        cur = start.replace(day=safe_day)
        if cur <= start:
            cur = _add_months(cur, 3 if freq == "QUARTERLY" else 1) if freq != "YEARLY" else cur.replace(year=cur.year + 1)
        for _ in range(index):
            cur = _add_months(cur, 3 if freq == "QUARTERLY" else 1) if freq != "YEARLY" else cur.replace(year=cur.year + 1)
        return cur.isoformat()
    except Exception:
        return (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

@app.post("/api/contracts/{contract_id}/payment")
async def set_payment(contract_id: int, user: dict = Depends(require_auth)):
    if user["role"] not in ["SUPERADMIN", "ADMIN", "CONTROLLER"]:
        raise HTTPException(status_code=403, detail="Нет прав для оплаты")

    existing = next((c for c in contracts_db if c["id"] == contract_id and not c.get("is_deleted", False)), None)
    if not existing:
        raise HTTPException(status_code=404, detail="Договор не найден")

    if existing["contract_type"] != "LEASE_IN":
        raise HTTPException(status_code=400, detail="Оплата доступна только для получения в аренду")

    total       = existing.get("amount") or 0
    freq        = existing.get("payment_frequency") or "MONTHLY"
    pay_day     = existing.get("payment_day") or 1
    start_str   = existing.get("start_date") or ""
    end_str     = existing.get("end_date") or ""
    made        = existing.get("payments_made") or 0

    # Estimate total scheduled payments
    total_sched = 1
    if start_str and end_str:
        from datetime import date as dt_date
        try:
            s = dt_date.fromisoformat(start_str)
            e = dt_date.fromisoformat(end_str)
            months = (e.year - s.year) * 12 + (e.month - s.month)
            total_sched = max(1, months // 3 if freq == "QUARTERLY" else months // 12 if freq == "YEARLY" else months)
        except Exception:
            pass

    if made >= total_sched:
        raise HTTPException(status_code=400, detail="Все платежи по договору уже внесены")

    per_payment = round(total / total_sched, 2) if total_sched else total

    old_value = existing.copy()
    existing["payment_type"]   = "ONLINE"
    existing["payments_made"]  = made + 1
    existing["amount_paid"]    = round((existing.get("amount_paid") or 0) + per_payment, 2)
    existing["payment_deadline"] = (_next_payment_date(start_str, freq, pay_day, made + 1) + "T00:00:00") if start_str else (datetime.now() + timedelta(days=30)).isoformat()

    log_action(user["personnel_number"], "PAYMENT", "CONTRACT", contract_id, old_value, existing, ip_address=user.get("ip_address","—"))
    return existing

# API - Audit
@app.get("/api/audit/all")
async def get_all_audit_logs(user: dict = Depends(require_auth)):
    if user["role"] not in ["SUPERADMIN", "ADMIN"]:
        raise HTTPException(status_code=403, detail="Нет прав")
    return sorted(audit_log, key=lambda x: x["timestamp"], reverse=True)

@app.get("/api/audit/{entity_type}/{entity_id}")
async def get_audit_logs(entity_type: str, entity_id: int, user: dict = Depends(require_auth)):
    logs = [log for log in audit_log if log["entity_type"] == entity_type and log["entity_id"] == entity_id]

    # OPERATOR can only see their own records
    if user["role"] == "OPERATOR":
        logs = [log for log in logs if log["user_id"] == user["personnel_number"]]

    return sorted(logs, key=lambda x: x["timestamp"], reverse=True)

# API - Suspicious operations
@app.get("/api/suspicious-operations")
async def get_suspicious_ops(user: dict = Depends(require_auth)):
    if user["role"] not in ["SUPERADMIN", "ADMIN"]:
        raise HTTPException(status_code=403, detail="Нет прав")
    return sorted(suspicious_ops, key=lambda x: x["timestamp"], reverse=True)

@app.post("/api/suspicious-operations/{op_id}/acknowledge")
async def acknowledge_suspicious(op_id: int, user: dict = Depends(require_auth)):
    if user["role"] not in ["SUPERADMIN", "ADMIN"]:
        raise HTTPException(status_code=403, detail="Нет прав")
    op = next((o for o in suspicious_ops if o["id"] == op_id), None)
    if op:
        op["acknowledged"] = True
    return {"success": True}

# API - Counterparties
@app.get("/api/counterparties")
async def get_counterparties(user: dict = Depends(require_auth)):
    return counterparties_db

@app.post("/api/counterparties")
async def create_counterparty(counterparty: CounterpartyUpdateRequest, user: dict = Depends(require_auth)):
    if user["role"] not in ["SUPERADMIN", "ADMIN"]:
        raise HTTPException(status_code=403, detail="Нет прав")

    # Validate INN
    if not counterparty.inn or len(counterparty.inn) not in [9, 10, 12]:
        raise HTTPException(status_code=400, detail="ИНН должен содержать 9, 10 или 12 цифр")

    # Validate bank account
    if not counterparty.bank_account or len(counterparty.bank_account) != 20:
        raise HTTPException(status_code=400, detail="Расчетный счет должен содержать 20 цифр")

    new_id = max([c["id"] for c in counterparties_db], default=0) + 1
    new_counterparty = {
        "id": new_id,
        "name": counterparty.name,
        "inn": counterparty.inn,
        "type": counterparty.type,
        "bank_account": counterparty.bank_account,
        "unique_code": counterparty.unique_code,
        "address": counterparty.address,
        "phone": counterparty.phone,
        "status": counterparty.status,
        "kpp": counterparty.kpp,
        "ogrn": counterparty.ogrn,
        "bank_name": counterparty.bank_name,
        "bik": counterparty.bik,
        "email": counterparty.email,
    }
    counterparties_db.append(new_counterparty)
    return new_counterparty

@app.put("/api/counterparties/{counterparty_id}")
async def update_counterparty(counterparty_id: int, counterparty: CounterpartyUpdateRequest, user: dict = Depends(require_auth)):
    if user["role"] not in ["SUPERADMIN", "ADMIN"]:
        raise HTTPException(status_code=403, detail="Нет прав")

    existing = next((c for c in counterparties_db if c["id"] == counterparty_id), None)
    if not existing:
        raise HTTPException(status_code=404, detail="Контрагент не найден")

    # Validate INN
    if not counterparty.inn or len(counterparty.inn) not in [9, 10, 12]:
        raise HTTPException(status_code=400, detail="ИНН должен содержать 9, 10 или 12 цифр")

    # Validate bank account
    if not counterparty.bank_account or len(counterparty.bank_account) != 20:
        raise HTTPException(status_code=400, detail="Расчетный счет должен содержать 20 цифр")

    existing.update({
        "name": counterparty.name,
        "inn": counterparty.inn,
        "type": counterparty.type,
        "bank_account": counterparty.bank_account,
        "unique_code": counterparty.unique_code,
        "address": counterparty.address,
        "phone": counterparty.phone,
        "status": counterparty.status,
        "kpp": counterparty.kpp,
        "ogrn": counterparty.ogrn,
        "bank_name": counterparty.bank_name,
        "bik": counterparty.bik,
        "email": counterparty.email,
    })
    return existing

@app.delete("/api/counterparties/{counterparty_id}")
async def delete_counterparty(counterparty_id: int, user: dict = Depends(require_auth)):
    if user["role"] not in ["SUPERADMIN", "ADMIN"]:
        raise HTTPException(status_code=403, detail="Нет прав")

    existing = next((c for c in counterparties_db if c["id"] == counterparty_id), None)
    if not existing:
        raise HTTPException(status_code=404, detail="Контрагент не найден")

    counterparties_db.remove(existing)
    return {"success": True}

# API - Contract Types
@app.get("/api/contract-types")
async def get_contract_types(user: dict = Depends(require_auth)):
    return contract_types_db

@app.post("/api/contract-types")
async def create_contract_type(contract_type: ContractTypeRequest, user: dict = Depends(require_auth)):
    if user["role"] not in ["SUPERADMIN", "ADMIN"]:
        raise HTTPException(status_code=403, detail="Нет прав")

    new_id = max([ct["id"] for ct in contract_types_db], default=0) + 1
    new_contract_type = {
        "id": new_id,
        "name": contract_type.name,
        "code": contract_type.code,
        "status": contract_type.status,
    }
    contract_types_db.append(new_contract_type)
    return new_contract_type

@app.put("/api/contract-types/{contract_type_id}")
async def update_contract_type(contract_type_id: int, contract_type: ContractTypeRequest, user: dict = Depends(require_auth)):
    if user["role"] not in ["SUPERADMIN", "ADMIN"]:
        raise HTTPException(status_code=403, detail="Нет прав")

    existing = next((ct for ct in contract_types_db if ct["id"] == contract_type_id), None)
    if not existing:
        raise HTTPException(status_code=404, detail="Тип договора не найден")

    existing.update({
        "name": contract_type.name,
        "code": contract_type.code,
        "status": contract_type.status,
    })
    return existing

@app.delete("/api/contract-types/{contract_type_id}")
async def delete_contract_type(contract_type_id: int, user: dict = Depends(require_auth)):
    if user["role"] not in ["SUPERADMIN", "ADMIN"]:
        raise HTTPException(status_code=403, detail="Нет прав")

    existing = next((ct for ct in contract_types_db if ct["id"] == contract_type_id), None)
    if not existing:
        raise HTTPException(status_code=404, detail="Тип договора не найден")

    contract_types_db.remove(existing)
    return {"success": True}

# API - Settings
@app.get("/api/users")
async def get_users(user: dict = Depends(require_auth)):
    if user["role"] != "SUPERADMIN":
        raise HTTPException(status_code=403, detail="Нет прав")

    return [{"personnel_number": k, "name": v["name"], "role": v["role"]}
            for k, v in users_db.items()]

@app.put("/api/users/{personnel_number}/role")
async def update_user_role(personnel_number: str, role: dict, user: dict = Depends(require_auth)):
    if user["role"] != "SUPERADMIN":
        raise HTTPException(status_code=403, detail="Нет прав")

    if personnel_number not in users_db:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    users_db[personnel_number]["role"] = role["role"]
    return {"success": True}

# API - Employees
@app.post("/api/employees")
async def create_employee(employee: EmployeeRequest, user: dict = Depends(require_auth)):
    if user["role"] != "SUPERADMIN":
        raise HTTPException(status_code=403, detail="Нет прав")

    if employee.personnel_number in users_db:
        raise HTTPException(status_code=400, detail="Сотрудник с таким табельным номером уже существует")

    users_db[employee.personnel_number] = {
        "password": employee.password,
        "name": employee.name,
        "role": employee.role,
        "status": "ACTIVE",
        "created_at": datetime.now().isoformat(),
    }
    return {"success": True}

@app.delete("/api/employees/{personnel_number}")
async def delete_employee(personnel_number: str, user: dict = Depends(require_auth)):
    if user["role"] != "SUPERADMIN":
        raise HTTPException(status_code=403, detail="Нет прав")

    if personnel_number not in users_db:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")

    if personnel_number == user["personnel_number"]:
        raise HTTPException(status_code=400, detail="Нельзя удалить самого себя")

    del users_db[personnel_number]
    return {"success": True}

# API - Permissions
@app.get("/api/permissions")
async def get_permissions(user: dict = Depends(require_auth)):
    if user["role"] != "SUPERADMIN":
        raise HTTPException(status_code=403, detail="Нет прав")
    return role_permissions

@app.get("/api/permissions/me")
async def get_my_permissions(user: dict = Depends(require_auth)):
    return role_permissions.get(user["role"], {})

@app.put("/api/permissions")
async def update_permission(perm: PermissionUpdateRequest, user: dict = Depends(require_auth)):
    if user["role"] != "SUPERADMIN":
        raise HTTPException(status_code=403, detail="Нет прав")

    if perm.role not in role_permissions:
        raise HTTPException(status_code=404, detail="Роль не найдена")

    if perm.permission not in role_permissions[perm.role]:
        raise HTTPException(status_code=404, detail="Разрешение не найдено")

    role_permissions[perm.role][perm.permission] = perm.value
    return {"success": True}

# API - Profile
@app.post("/api/profile/change-password")
async def change_password(password_req: PasswordChangeRequest, user: dict = Depends(require_auth)):
    personnel_number = user["personnel_number"]
    user_data = users_db.get(personnel_number)

    if not user_data:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    if user_data["password"] != password_req.current_password:
        raise HTTPException(status_code=400, detail="Неверный текущий пароль")

    if len(password_req.new_password) < 6:
        raise HTTPException(status_code=400, detail="Пароль должен содержать минимум 6 символов")

    users_db[personnel_number]["password"] = password_req.new_password
    return {"success": True}

# API - Next contract number generator
@app.get("/api/contracts/next-number")
async def get_next_contract_number(user: dict = Depends(require_auth)):
    year = datetime.now().year
    prefix = f"AP-{year}-"
    existing_numbers = [
        c["contract_number"] for c in contracts_db
        if c["contract_number"].startswith(prefix) and not c.get("is_deleted", False)
    ]
    max_seq = 0
    for num in existing_numbers:
        try:
            seq = int(num.replace(prefix, ""))
            if seq > max_seq:
                max_seq = seq
        except ValueError:
            pass
    next_seq = max_seq + 1
    return {"contract_number": f"{prefix}{next_seq:03d}"}

# API - Counterparty lookup by INN (searches inn_lookup_db, not the working directory)
@app.get("/api/counterparties/lookup")
async def lookup_counterparty_by_inn(inn: str, user: dict = Depends(require_auth)):
    match = next((c for c in inn_lookup_db if c["inn"] == inn), None)
    if not match:
        raise HTTPException(status_code=404, detail="Контрагент с таким ИНН не найден в базе")
    return match

# API - Read approved contracts from SQLite
@app.get("/api/approved-contracts")
async def get_approved_contracts(user: dict = Depends(require_auth)):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM approved_contracts ORDER BY approved_at DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]

# API - Problem context (hackathon presentation)
@app.get("/api/problem")
async def get_problem_context():
    return problem_context
