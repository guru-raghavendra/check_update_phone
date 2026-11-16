# ---------------------------------------------------------------------------
# STEP 5 - VALINOR update (valar repo / UserManagement django project)
# Run inside:  python manage.py shell
#
# Input : /tmp/phone_step3_saruman.csv   (output of step 3)
# Output: /tmp/phone_step5_valinor_result.csv
#
# Writes both places the number lives:
#   auth_user.username                     (login id)
#   core.EmployeeProfile.primary_contact
# auth_user is saved first, then the profile - the EmployeeProfile post_save
# signal refreshes the redis auth cache, which caches mobile_number from
# auth_user.username, so the cache picks up the new number.
#
# Only rows with eligible = TRUE are touched.  Pasting this runs a DRY RUN;
# then run:  run(commit=True)
# ---------------------------------------------------------------------------
import csv
import os
import re
from django.db import transaction
from django.contrib.auth.models import User as AuthUser
from core.models import Employee, EmployeeProfile

IN_PATH = '/tmp/phone_step3_saruman.csv'
OUT_PATH = '/tmp/phone_step5_valinor_result.csv'
OUT_FIELDS = ['user_id', 'valinor_id', 'name', 'old_username', 'old_primary_contact',
              'new_phone', 'result', 'detail']


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
    print("STEP 5 | valinor update | mode={} | eligible {} of {} rows".format(
        'COMMIT' if commit else 'DRY RUN', len(eligible_rows), len(rows)))
    print("=" * 110)
    results = []
    stats = {'updated': 0, 'already': 0, 'conflict': 0, 'no_valinor_id': 0,
             'not_found': 0, 'error': 0}
    for idx, row in enumerate(eligible_rows, start=1):
        valinor_id = as_int(row.get('valinor_id'))
        new_phone = normalise_phone(row.get('new_phone'))
        variations = phone_variations(new_phone)
        record = {'user_id': row.get('user_id'), 'valinor_id': row.get('valinor_id'),
                  'name': row.get('name'), 'old_username': '', 'old_primary_contact': '',
                  'new_phone': new_phone, 'result': '', 'detail': ''}
        if not valinor_id:
            record['result'], record['detail'] = 'SKIPPED', 'workforce user has no valinor_id'
            results.append(record)
            stats['no_valinor_id'] += 1
            print("Row {}: SKIP - workforce user {} has no valinor_id".format(idx, row.get('user_id')))
            continue
        employee = Employee.objects.filter(id=valinor_id).select_related('user').first()
        if not employee:
            record['result'], record['detail'] = 'NOT_FOUND', 'valinor employee missing'
            results.append(record)
            stats['not_found'] += 1
            print("Row {}: NOT_FOUND - valinor employee {}".format(idx, valinor_id))
            continue
        auth_user = employee.user
        profile = EmployeeProfile.objects.filter(employee_id=employee.id).first()
        record['old_username'] = auth_user.username
        record['old_primary_contact'] = profile.primary_contact if profile else ''
        if auth_user.username in variations and profile and profile.primary_contact in variations:
            record['result'], record['detail'] = 'ALREADY_UPDATED', 'already on {}'.format(auth_user.username)
            results.append(record)
            stats['already'] += 1
            print("Row {}: ALREADY - employee {} already on {}".format(idx, employee.id, auth_user.username))
            continue
        # Re-check at write time; the sheet may be older than the DB.
        clash = []
        user_clash = AuthUser.objects.filter(username__in=variations).exclude(id=auth_user.id).first()
        if user_clash:
            clash.append('username taken by auth_user_id={}'.format(user_clash.id))
        profile_clash = EmployeeProfile.objects.filter(
            primary_contact__in=variations).exclude(employee_id=employee.id).first()
        if profile_clash:
            clash.append('primary_contact taken by employee_id={}'.format(profile_clash.employee_id))
        if clash:
            record['result'], record['detail'] = 'CONFLICT', ' | '.join(clash)
            results.append(record)
            stats['conflict'] += 1
            print("Row {}: CONFLICT - {} {}".format(idx, new_phone, record['detail']))
            continue
        if not commit:
            record['result'] = 'WILL_UPDATE'
            results.append(record)
            stats['updated'] += 1
            print("Row {}: WILL_UPDATE - employee {} username '{}' / primary_contact '{}' -> {}".format(
                idx, employee.id, record['old_username'], record['old_primary_contact'], new_phone))
            continue
        try:
            with transaction.atomic():
                auth_user.username = new_phone
                auth_user.save(update_fields=['username'])
                if profile:
                    profile.primary_contact = new_phone
                    profile.save()
                else:
                    EmployeeProfile.objects.create(employee=employee, primary_contact=new_phone)
            record['result'] = 'UPDATED'
            stats['updated'] += 1
            print("Row {}: UPDATED - employee {} -> {}".format(idx, employee.id, new_phone))
        except Exception as exc:
            record['result'], record['detail'] = 'ERROR', str(exc)
            stats['error'] += 1
            print("Row {}: ERROR - employee {}: {}".format(idx, employee.id, exc))
        results.append(record)
    with open(out_path, 'w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=OUT_FIELDS)
        writer.writeheader()
        writer.writerows(results)
    print("=" * 110)
    print("{} : {}".format('updated' if commit else 'will update', stats['updated']))
    print("already updated  : {}".format(stats['already']))
    print("conflicts        : {}".format(stats['conflict']))
    print("no valinor_id    : {}".format(stats['no_valinor_id']))
    print("not found        : {}".format(stats['not_found']))
    print("errors           : {}".format(stats['error']))
    print("wrote {}".format(out_path))
    if not commit:
        print("DRY RUN only. Run  run(commit=True)  to write to the database.")
    return stats


run()
