# ---------------------------------------------------------------------------
# STEP 1 - WORKFORCE (frodo / workforce-management-backend)
# Run inside:  python manage.py shell
#
# Input : /tmp/phone_input.csv         cols -> user_id, new_phone_number
#         (user_id may be bare "33067" or darsa style "SFXPROD33067")
# Output: /tmp/phone_step1_wfm_ok.csv     -> numbers free in workforce
#         /tmp/phone_step1_wfm_taken.csv  -> numbers already used by someone else
# ---------------------------------------------------------------------------
import csv
import os
import re
from access_management.models import User

IN_PATH = '/tmp/phone_input.csv'
OK_PATH = '/tmp/phone_step1_wfm_ok.csv'
TAKEN_PATH = '/tmp/phone_step1_wfm_taken.csv'

ID_KEYS = ('user_id', 'user id', 'wfm id', 'wfm_id', 'id', 'emp_id', 'employee id')
PHONE_KEYS = ('new_phone_number', 'new phone number', 'new contact number',
              'new_contact_number', 'new_phone', 'correct contact number',
              'phone_number', 'contact number')

OK_FIELDS = ['user_id', 'valinor_id', 'saruman_id', 'name', 'status',
             'current_phone', 'new_phone', 'wfm_already_updated']
TAKEN_FIELDS = ['user_id', 'name', 'current_phone', 'new_phone', 'reason', 'taken_by']


def pick(row, keys):
    for key in keys:
        if key in row and str(row[key] or '').strip():
            return str(row[key]).strip()
    return ''


def parse_user_id(raw):
    """Bare id or darsa prefixed id (SFXPROD123 / SFXSTAG123) -> int, else None."""
    value = str(raw or '').strip()
    value = re.sub(r'^[A-Za-z]+', '', value)
    return int(value) if value.isdigit() else None


def normalise_phone(raw):
    """Strip separators / country code and return the bare 10 digit number."""
    digits = re.sub(r'\D', '', str(raw or ''))
    if len(digits) > 10:
        digits = digits[-10:]
    return digits


def phone_variations(phone):
    """Every shape the same number can be stored in across our DBs."""
    if not phone:
        return []
    return sorted({phone, '91' + phone, '0' + phone})


def is_valid_indian_mobile(phone):
    return bool(re.match(r'^[6-9]\d{9}$', phone or ''))


def describe(user):
    return "user_id={} name={} valinor_id={} saruman_id={} status={}".format(
        user.id, user.name, user.valinor_id, user.saruman_id, user.status)


def run(in_path=IN_PATH, ok_path=OK_PATH, taken_path=TAKEN_PATH):
    if not os.path.exists(in_path):
        print("Error: input csv not found at {}".format(in_path))
        return
    with open(in_path, 'r', encoding='utf-8-sig') as handle:
        reader = csv.DictReader(handle)
        reader.fieldnames = [(f or '').strip().lower() for f in (reader.fieldnames or [])]
        rows = list(reader)
    print("STEP 1 | workforce check | input={} rows={}".format(in_path, len(rows)))
    print("=" * 110)
    # Detect the same new number requested for two different users in one sheet.
    seen_new = {}
    for row in rows:
        phone = normalise_phone(pick(row, PHONE_KEYS))
        if phone:
            seen_new.setdefault(phone, []).append(pick(row, ID_KEYS))
    dupes_in_sheet = {p: ids for p, ids in seen_new.items() if len(ids) > 1}
    ok_rows, taken_rows = [], []
    stats = {'total': 0, 'ok': 0, 'taken': 0, 'already_updated': 0, 'bad_row': 0, 'not_found': 0}
    for idx, row in enumerate(rows, start=1):
        stats['total'] += 1
        raw_id = pick(row, ID_KEYS)
        raw_phone = pick(row, PHONE_KEYS)
        user_id = parse_user_id(raw_id)
        new_phone = normalise_phone(raw_phone)
        if not user_id:
            print("Row {}: SKIP - cannot parse user id '{}'".format(idx, raw_id))
            stats['bad_row'] += 1
            continue
        if not is_valid_indian_mobile(new_phone):
            print("Row {}: SKIP - invalid new phone '{}' for user {}".format(idx, raw_phone, user_id))
            stats['bad_row'] += 1
            continue
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            print("Row {}: SKIP - workforce user {} not found".format(idx, user_id))
            stats['not_found'] += 1
            continue
        variations = phone_variations(new_phone)
        already = user.phone_number in variations
        conflicts = list(User.objects.filter(phone_number__in=variations).exclude(id=user.id))
        if new_phone in dupes_in_sheet:
            taken_rows.append({
                'user_id': user.id, 'name': user.name, 'current_phone': user.phone_number,
                'new_phone': new_phone, 'reason': 'DUPLICATE_IN_INPUT_SHEET',
                'taken_by': "requested for input ids: {}".format(', '.join(dupes_in_sheet[new_phone])),
            })
            print("Row {}: TAKEN - {} requested for more than one input row".format(idx, new_phone))
            stats['taken'] += 1
            continue
        if conflicts:
            detail = ' | '.join(describe(c) for c in conflicts)
            taken_rows.append({
                'user_id': user.id, 'name': user.name, 'current_phone': user.phone_number,
                'new_phone': new_phone, 'reason': 'ALREADY_USED_IN_WORKFORCE', 'taken_by': detail,
            })
            print("Row {}: TAKEN - {} already on -> {}".format(idx, new_phone, detail))
            stats['taken'] += 1
            continue
        ok_rows.append({
            'user_id': user.id,
            'valinor_id': user.valinor_id or '',
            'saruman_id': user.saruman_id or '',
            'name': user.name or '',
            'status': user.status,
            'current_phone': user.phone_number,
            'new_phone': new_phone,
            'wfm_already_updated': 'TRUE' if already else 'FALSE',
        })
        stats['ok'] += 1
        if already:
            stats['already_updated'] += 1
            print("Row {}: OK - {} (valinor={} saruman={}) workforce already on {}".format(
                idx, user.id, user.valinor_id, user.saruman_id, new_phone))
        else:
            print("Row {}: OK - {} (valinor={} saruman={}) {} -> {}".format(
                idx, user.id, user.valinor_id, user.saruman_id, user.phone_number, new_phone))
    with open(ok_path, 'w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=OK_FIELDS)
        writer.writeheader()
        writer.writerows(ok_rows)
    with open(taken_path, 'w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=TAKEN_FIELDS)
        writer.writeheader()
        writer.writerows(taken_rows)
    print("=" * 110)
    print("rows read            : {}".format(stats['total']))
    print("free in workforce    : {}  (of which workforce already updated: {})".format(
        stats['ok'], stats['already_updated']))
    print("already taken        : {}".format(stats['taken']))
    print("user not found       : {}".format(stats['not_found']))
    print("bad rows             : {}".format(stats['bad_row']))
    print("wrote {}   -> feed this to STEP 2 (valinor)".format(ok_path))
    print("wrote {} -> conflicts, nothing to update".format(taken_path))
    return stats


run()
