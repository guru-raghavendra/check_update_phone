# ---------------------------------------------------------------------------
# STEP 4 - WORKFORCE update (frodo / workforce-management-backend)
# Run inside:  python manage.py shell
#
# Input : /tmp/phone_step3_saruman.csv   (output of step 3)
# Output: /tmp/phone_step4_wfm_result.csv
#
# Only rows with eligible = TRUE (free in valinor AND free in saruman) are
# touched.
#
# Where step 3 resolved saruman_id through valinor (saruman_id_source =
# valinor_lookup, i.e. hub managers), User.saruman_id is filled in as well so
# the next run finds the saruman account directly.  Set FILL_SARUMAN_ID = False
# to leave saruman_id alone.  Note that once saruman_id is set, a later
# deactivate/exit in workforce queues the DC_GC saruman sync for the user;
# saruman answers 400 for a non-DC_GC account, so nothing changes there.
#
# Pasting this runs a DRY RUN; then run:  run(commit=True)
# ---------------------------------------------------------------------------
import csv
import os
import re
from django.db import transaction
from access_management.models import User

IN_PATH = '/tmp/phone_step3_saruman.csv'
OUT_PATH = '/tmp/phone_step4_wfm_result.csv'
FILL_SARUMAN_ID = True
OUT_FIELDS = ['user_id', 'valinor_id', 'saruman_id', 'saruman_id_result', 'name',
              'old_phone', 'new_phone', 'result', 'detail']


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


def fill_saruman_id(idx, row, user, record, stats, commit):
    """Set User.saruman_id from the step 3 valinor lookup when workforce has none."""
    csv_saruman_id = as_int(row.get('saruman_id'))
    if not FILL_SARUMAN_ID or row.get('saruman_id_source') != 'valinor_lookup' or not csv_saruman_id:
        return
    if user.saruman_id == csv_saruman_id:
        record['saruman_id_result'] = 'already {}'.format(user.saruman_id)
        return
    if user.saruman_id:
        record['saruman_id_result'] = 'kept {} (sheet resolved {})'.format(user.saruman_id, csv_saruman_id)
        print("Row {}: WARN - user {} already has saruman_id {}, sheet resolved {}; left alone".format(
            idx, user.id, user.saruman_id, csv_saruman_id))
        return
    taken = User.objects.filter(saruman_id=csv_saruman_id).exclude(id=user.id).first()
    if taken:
        record['saruman_id_result'] = 'taken by user_id={}'.format(taken.id)
        print("Row {}: WARN - saruman_id {} already on workforce user {}; not set on user {}".format(
            idx, csv_saruman_id, taken.id, user.id))
        return
    if not commit:
        record['saruman_id_result'] = 'WILL_SET {}'.format(csv_saruman_id)
        stats['saruman_id_set'] += 1
        print("Row {}: WILL_SET saruman_id - user {} -> {} (via valinor {})".format(
            idx, user.id, csv_saruman_id, row.get('valinor_id')))
        return
    try:
        with transaction.atomic():
            user.saruman_id = csv_saruman_id
            user.save(update_fields=['saruman_id', 'modified'])
        record['saruman_id_result'] = 'SET {}'.format(csv_saruman_id)
        stats['saruman_id_set'] += 1
        print("Row {}: SET saruman_id - user {} -> {} (via valinor {})".format(
            idx, user.id, csv_saruman_id, row.get('valinor_id')))
    except Exception as exc:
        record['saruman_id_result'] = 'ERROR {}'.format(exc)
        stats['error'] += 1
        print("Row {}: ERROR setting saruman_id on user {}: {}".format(idx, user.id, exc))


def run(in_path=IN_PATH, out_path=OUT_PATH, commit=False):
    if not os.path.exists(in_path):
        print("Error: input csv not found at {} (run step 3 first)".format(in_path))
        return
    with open(in_path, 'r', encoding='utf-8-sig') as handle:
        rows = list(csv.DictReader(handle))
    eligible_rows = [r for r in rows if r.get('eligible') == 'TRUE']
    print("STEP 4 | workforce update | mode={} | eligible {} of {} rows".format(
        'COMMIT' if commit else 'DRY RUN', len(eligible_rows), len(rows)))
    print("=" * 110)
    results = []
    stats = {'updated': 0, 'already': 0, 'conflict': 0, 'not_found': 0,
             'saruman_id_set': 0, 'error': 0}
    for idx, row in enumerate(eligible_rows, start=1):
        user_id = as_int(row.get('user_id'))
        new_phone = normalise_phone(row.get('new_phone'))
        variations = phone_variations(new_phone)
        record = {'user_id': row.get('user_id'), 'valinor_id': row.get('valinor_id'),
                  'saruman_id': row.get('saruman_id'), 'saruman_id_result': '',
                  'name': row.get('name'), 'old_phone': '', 'new_phone': new_phone,
                  'result': '', 'detail': ''}
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            record['result'], record['detail'] = 'NOT_FOUND', 'workforce user missing'
            results.append(record)
            stats['not_found'] += 1
            print("Row {}: NOT_FOUND - workforce user {}".format(idx, user_id))
            continue
        record['old_phone'] = user.phone_number
        fill_saruman_id(idx, row, user, record, stats, commit)
        if user.phone_number in variations:
            record['result'], record['detail'] = 'ALREADY_UPDATED', 'phone already {}'.format(user.phone_number)
            results.append(record)
            stats['already'] += 1
            print("Row {}: ALREADY - user {} already on {}".format(idx, user.id, user.phone_number))
            continue
        # Re-check at write time; the sheet may be older than the DB.
        clash = User.objects.filter(phone_number__in=variations).exclude(id=user.id).first()
        if clash:
            detail = 'taken by user_id={} name={}'.format(clash.id, clash.name)
            record['result'], record['detail'] = 'CONFLICT', detail
            results.append(record)
            stats['conflict'] += 1
            print("Row {}: CONFLICT - {} {}".format(idx, new_phone, detail))
            continue
        if not commit:
            record['result'] = 'WILL_UPDATE'
            results.append(record)
            stats['updated'] += 1
            print("Row {}: WILL_UPDATE - user {} {} -> {}".format(idx, user.id, user.phone_number, new_phone))
            continue
        try:
            with transaction.atomic():
                user.phone_number = new_phone
                user.save(update_fields=['phone_number', 'modified'])
            record['result'] = 'UPDATED'
            stats['updated'] += 1
            print("Row {}: UPDATED - user {} {} -> {}".format(idx, user.id, record['old_phone'], new_phone))
        except Exception as exc:
            record['result'], record['detail'] = 'ERROR', str(exc)
            stats['error'] += 1
            print("Row {}: ERROR - user {}: {}".format(idx, user.id, exc))
        results.append(record)
    with open(out_path, 'w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=OUT_FIELDS)
        writer.writeheader()
        writer.writerows(results)
    print("=" * 110)
    print("{} : {}".format('updated' if commit else 'will update', stats['updated']))
    print("already updated  : {}".format(stats['already']))
    print("conflicts        : {}".format(stats['conflict']))
    print("not found        : {}".format(stats['not_found']))
    print("{} : {}".format('saruman_id set' if commit else 'saruman_id will set', stats['saruman_id_set']))
    print("errors           : {}".format(stats['error']))
    print("wrote {}".format(out_path))
    if not commit:
        print("DRY RUN only. Run  run(commit=True)  to write to the database.")
    return stats


run()
