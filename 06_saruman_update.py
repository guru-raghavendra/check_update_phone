
# ---------------------------------------------------------------------------
# STEP 6 - SARUMAN update (saruman repo / ecommerce)
# Run inside:  python manage.py shell
#
# Input : /tmp/phone_step3_saruman.csv   (output of step 3)
# Output: /tmp/phone_step6_saruman_result.csv
#
# The phone number in saruman is auth_user.username (OperationUser carries no
# phone column).  is_active is untouched, so the workforce deactivation signal
# on User post_save stays inert.
#
# Only rows with eligible = TRUE are touched.  Pasting this runs a DRY RUN;
# then run:  run(commit=True)
# ---------------------------------------------------------------------------
import csv
import os
import re
from django.db import transaction
from django.contrib.auth.models import User as AuthUser
from ecommerce.models import OperationUser

IN_PATH = '/tmp/phone_step3_saruman.csv'
OUT_PATH = '/tmp/phone_step6_saruman_result.csv'
OUT_FIELDS = ['user_id', 'saruman_id', 'valinor_id', 'name', 'old_username',
              'new_phone', 'saruman_role', 'result', 'detail']


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


def run(in_path=IN_PATH, out_path=OUT_PATH, commit=False):
    if not os.path.exists(in_path):
        print("Error: input csv not found at {} (run step 3 first)".format(in_path))
        return
    with open(in_path, 'r', encoding='utf-8-sig') as handle:
        rows = list(csv.DictReader(handle))
    eligible_rows = [r for r in rows if r.get('eligible') == 'TRUE']
    print("STEP 6 | saruman update | mode={} | eligible {} of {} rows".format(
        'COMMIT' if commit else 'DRY RUN', len(eligible_rows), len(rows)))
    print("=" * 110)
    results = []
    stats = {'updated': 0, 'already': 0, 'conflict': 0, 'no_saruman_id': 0,
             'not_found': 0, 'error': 0}
    for idx, row in enumerate(eligible_rows, start=1):
        saruman_id = as_int(row.get('saruman_id'))
        new_phone = normalise_phone(row.get('new_phone'))
        variations = phone_variations(new_phone)
        record = {'user_id': row.get('user_id'), 'saruman_id': row.get('saruman_id'),
                  'valinor_id': row.get('valinor_id'), 'name': row.get('name'),
                  'old_username': '', 'new_phone': new_phone, 'saruman_role': '',
                  'result': '', 'detail': ''}
        if not saruman_id:
            record['result'], record['detail'] = 'SKIPPED', 'workforce user has no saruman_id'
            results.append(record)
            stats['no_saruman_id'] += 1
            print("Row {}: SKIP - workforce user {} has no saruman_id".format(idx, row.get('user_id')))
            continue
        auth_user = AuthUser.objects.filter(id=saruman_id).first()
        if not auth_user:
            record['result'], record['detail'] = 'NOT_FOUND', 'saruman user missing'
            results.append(record)
            stats['not_found'] += 1
            print("Row {}: NOT_FOUND - saruman user {}".format(idx, saruman_id))
            continue
        op_user = OperationUser.objects.filter(user_id=auth_user.id).first()
        record['old_username'] = auth_user.username
        record['saruman_role'] = op_user.role if op_user else ''
        if auth_user.username in variations:
            record['result'], record['detail'] = 'ALREADY_UPDATED', 'already on {}'.format(auth_user.username)
            results.append(record)
            stats['already'] += 1
            print("Row {}: ALREADY - saruman user {} already on {}".format(idx, auth_user.id, auth_user.username))
            continue
        # Re-check at write time; the sheet may be older than the DB.
        clash = AuthUser.objects.filter(username__in=variations).exclude(id=auth_user.id).first()
        if clash:
            detail = 'username taken by saruman user_id={}'.format(clash.id)
            record['result'], record['detail'] = 'CONFLICT', detail
            results.append(record)
            stats['conflict'] += 1
            print("Row {}: CONFLICT - {} {}".format(idx, new_phone, detail))
            continue
        if not commit:
            record['result'] = 'WILL_UPDATE'
            results.append(record)
            stats['updated'] += 1
            print("Row {}: WILL_UPDATE - saruman user {} '{}' -> {}".format(
                idx, auth_user.id, auth_user.username, new_phone))
            continue
        try:
            with transaction.atomic():
                auth_user.username = new_phone
                auth_user.save(update_fields=['username'])
            record['result'] = 'UPDATED'
            stats['updated'] += 1
            print("Row {}: UPDATED - saruman user {} {} -> {}".format(
                idx, auth_user.id, record['old_username'], new_phone))
        except Exception as exc:
            record['result'], record['detail'] = 'ERROR', str(exc)
            stats['error'] += 1
            print("Row {}: ERROR - saruman user {}: {}".format(idx, auth_user.id, exc))
        results.append(record)
    with open(out_path, 'w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=OUT_FIELDS)
        writer.writeheader()
        writer.writerows(results)
    print("=" * 110)
    print("{} : {}".format('updated' if commit else 'will update', stats['updated']))
    print("already updated  : {}".format(stats['already']))
    print("conflicts        : {}".format(stats['conflict']))
    print("no saruman_id    : {}".format(stats['no_saruman_id']))
    print("not found        : {}".format(stats['not_found']))
    print("errors           : {}".format(stats['error']))
    print("wrote {}".format(out_path))
    if not commit:
        print("DRY RUN only. Run  run(commit=True)  to write to the database.")
    return stats


run()
