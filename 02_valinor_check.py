# ---------------------------------------------------------------------------
# STEP 2 - VALINOR (valar repo / UserManagement django project)
# Run inside:  python manage.py shell
#
# Input : /tmp/phone_step1_wfm_ok.csv   (output of step 1)
# Output: /tmp/phone_step2_valinor.csv  (same rows + valinor columns)
#
# In valinor the phone number lives in TWO places, both unique:
#   auth_user.username            (login id)
#   core.EmployeeProfile.primary_contact
# Both are checked. valinor_exists = TRUE means the number is held by SOMEONE
# ELSE, so the row is not updatable.
# ---------------------------------------------------------------------------
import csv
import os
import re
from django.contrib.auth.models import User as AuthUser
from core.models import Employee, EmployeeProfile

IN_PATH = '/tmp/phone_step1_wfm_ok.csv'
OUT_PATH = '/tmp/phone_step2_valinor.csv'

OUT_FIELDS = ['user_id', 'valinor_id', 'saruman_id', 'name', 'status',
              'current_phone', 'new_phone', 'wfm_already_updated',
              'valinor_employee_found', 'valinor_current_phone',
              'valinor_exists', 'valinor_conflict']


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
        print("Error: input csv not found at {} (run step 1 first)".format(in_path))
        return
    with open(in_path, 'r', encoding='utf-8-sig') as handle:
        rows = list(csv.DictReader(handle))
    print("STEP 2 | valinor check | input={} rows={}".format(in_path, len(rows)))
    print("=" * 110)
    out_rows = []
    stats = {'total': 0, 'free': 0, 'exists': 0, 'no_valinor_id': 0, 'employee_missing': 0}
    for idx, row in enumerate(rows, start=1):
        stats['total'] += 1
        valinor_id = as_int(row.get('valinor_id'))
        new_phone = normalise_phone(row.get('new_phone'))
        variations = phone_variations(new_phone)
        employee = Employee.objects.filter(id=valinor_id).first() if valinor_id else None
        own_auth_user_id = employee.user_id if employee else None
        valinor_current = employee.user.username if employee else ''
        if not valinor_id:
            stats['no_valinor_id'] += 1
        elif not employee:
            stats['employee_missing'] += 1
            print("Row {}: WARN - workforce user {} points at valinor id {} which does not exist".format(
                idx, row.get('user_id'), valinor_id))
        conflicts = []
        auth_qs = AuthUser.objects.filter(username__in=variations)
        if own_auth_user_id:
            auth_qs = auth_qs.exclude(id=own_auth_user_id)
        for auth_user in auth_qs:
            employee_of = Employee.objects.filter(user_id=auth_user.id).first()
            conflicts.append("username '{}' held by auth_user_id={} employee_id={} name={} {}".format(
                auth_user.username, auth_user.id,
                employee_of.id if employee_of else None,
                auth_user.first_name, auth_user.last_name))
        profile_qs = EmployeeProfile.objects.filter(primary_contact__in=variations)
        if valinor_id:
            profile_qs = profile_qs.exclude(employee_id=valinor_id)
        for profile in profile_qs.select_related('employee'):
            conflicts.append("primary_contact '{}' held by employee_id={} name={}".format(
                profile.primary_contact, profile.employee_id, profile.employee.name))
        exists = bool(conflicts)
        if exists:
            stats['exists'] += 1
            print("Row {}: EXISTS - {} -> {}".format(idx, new_phone, ' | '.join(conflicts)))
        else:
            stats['free'] += 1
            print("Row {}: FREE - {} (valinor employee {} currently on '{}')".format(
                idx, new_phone, valinor_id, valinor_current))
        out_row = dict(row)
        out_row['valinor_employee_found'] = 'TRUE' if employee else 'FALSE'
        out_row['valinor_current_phone'] = valinor_current
        out_row['valinor_exists'] = 'TRUE' if exists else 'FALSE'
        out_row['valinor_conflict'] = ' | '.join(conflicts)
        out_rows.append({field: out_row.get(field, '') for field in OUT_FIELDS})
    with open(out_path, 'w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=OUT_FIELDS)
        writer.writeheader()
        writer.writerows(out_rows)
    print("=" * 110)
    print("rows read                  : {}".format(stats['total']))
    print("valinor_exists = FALSE     : {}".format(stats['free']))
    print("valinor_exists = TRUE      : {}".format(stats['exists']))
    print("rows with no valinor_id    : {}".format(stats['no_valinor_id']))
    print("valinor employee missing   : {}".format(stats['employee_missing']))
    print("wrote {} -> feed this to STEP 3 (saruman)".format(out_path))
    return stats


run()
