# ---------------------------------------------------------------------------
# STEP 3 - SARUMAN (saruman repo / ecommerce)
# Run inside:  python manage.py shell
#
# Input : /tmp/phone_step2_valinor.csv  (output of step 2)
# Output: /tmp/phone_step3_saruman.csv  (adds saruman columns + eligible flag)
#
# In saruman the phone number is auth_user.username; OperationUser hangs off it
# (WFM User.saruman_id == saruman auth_user.id).  saruman_exists = TRUE means
# the number is held by SOMEONE ELSE.
# eligible = TRUE only when valinor_exists = FALSE and saruman_exists = FALSE.
# ---------------------------------------------------------------------------
import csv
import os
import re
from django.contrib.auth.models import User as AuthUser
from ecommerce.models import OperationUser

IN_PATH = '/tmp/phone_step2_valinor.csv'
OUT_PATH = '/tmp/phone_step3_saruman.csv'

OUT_FIELDS = ['user_id', 'valinor_id', 'saruman_id', 'name', 'status',
              'current_phone', 'new_phone', 'wfm_already_updated',
              'valinor_employee_found', 'valinor_current_phone',
              'valinor_exists', 'valinor_conflict',
              'saruman_user_found', 'saruman_current_phone', 'saruman_role',
              'saruman_exists', 'saruman_conflict', 'eligible']


def normalise_phone(raw):
    digits = re.sub(r'\D', '', str(raw or ''))
    if len(digits) > 10:
        digits = digits[-10:]
    return digits


def phone_variations(phone):
    if not phone:
        return []
    return sorted({phone, '91' + phone, '0' + phone})


def as_int(raw):
    value = str(raw or '').strip()
    return int(value) if value.isdigit() else None


def run(in_path=IN_PATH, out_path=OUT_PATH):
    if not os.path.exists(in_path):
        print("Error: input csv not found at {} (run step 2 first)".format(in_path))
        return
    with open(in_path, 'r', encoding='utf-8-sig') as handle:
        rows = list(csv.DictReader(handle))
    print("STEP 3 | saruman check | input={} rows={}".format(in_path, len(rows)))
    print("=" * 110)
    out_rows = []
    stats = {'total': 0, 'free': 0, 'exists': 0, 'no_saruman_id': 0,
             'user_missing': 0, 'eligible': 0}
    for idx, row in enumerate(rows, start=1):
        stats['total'] += 1
        saruman_id = as_int(row.get('saruman_id'))
        new_phone = normalise_phone(row.get('new_phone'))
        variations = phone_variations(new_phone)
        own_user = AuthUser.objects.filter(id=saruman_id).first() if saruman_id else None
        own_op_user = OperationUser.objects.filter(user_id=saruman_id).first() if saruman_id else None
        saruman_current = own_user.username if own_user else ''
        saruman_role = own_op_user.role if own_op_user else ''
        if not saruman_id:
            stats['no_saruman_id'] += 1
        elif not own_user:
            stats['user_missing'] += 1
            print("Row {}: WARN - workforce user {} points at saruman id {} which does not exist".format(
                idx, row.get('user_id'), saruman_id))
        conflicts = []
        auth_qs = AuthUser.objects.filter(username__in=variations)
        if saruman_id:
            auth_qs = auth_qs.exclude(id=saruman_id)
        for auth_user in auth_qs:
            op_user = OperationUser.objects.filter(user_id=auth_user.id).first()
            conflicts.append("username '{}' held by saruman user_id={} role={} entity={}:{} active={}".format(
                auth_user.username, auth_user.id,
                op_user.role if op_user else None,
                op_user.entity_type if op_user else None,
                op_user.entity_id if op_user else None,
                auth_user.is_active))
        exists = bool(conflicts)
        if exists:
            stats['exists'] += 1
            print("Row {}: EXISTS - {} -> {}".format(idx, new_phone, ' | '.join(conflicts)))
        else:
            stats['free'] += 1
            print("Row {}: FREE - {} (saruman user {} currently on '{}')".format(
                idx, new_phone, saruman_id, saruman_current))
        eligible = (row.get('valinor_exists') == 'FALSE') and not exists
        if eligible:
            stats['eligible'] += 1
        out_row = dict(row)
        out_row['saruman_user_found'] = 'TRUE' if own_user else 'FALSE'
        out_row['saruman_current_phone'] = saruman_current
        out_row['saruman_role'] = saruman_role
        out_row['saruman_exists'] = 'TRUE' if exists else 'FALSE'
        out_row['saruman_conflict'] = ' | '.join(conflicts)
        out_row['eligible'] = 'TRUE' if eligible else 'FALSE'
        out_rows.append({field: out_row.get(field, '') for field in OUT_FIELDS})
    with open(out_path, 'w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=OUT_FIELDS)
        writer.writeheader()
        writer.writerows(out_rows)
    print("=" * 110)
    print("rows read                  : {}".format(stats['total']))
    print("saruman_exists = FALSE     : {}".format(stats['free']))
    print("saruman_exists = TRUE      : {}".format(stats['exists']))
    print("rows with no saruman_id    : {}".format(stats['no_saruman_id']))
    print("saruman user missing       : {}".format(stats['user_missing']))
    print("ELIGIBLE for update        : {}".format(stats['eligible']))
    print("wrote {} -> feed this to STEPS 4, 5 and 6".format(out_path))
    return stats


run()
