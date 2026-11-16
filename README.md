# Check & update phone numbers — workforce / valinor / saruman

Six paste-into-`python manage.py shell` scripts. Steps run in order; each one's
output CSV is the next one's input. Nothing is written to any DB until you
explicitly call `run(commit=True)` in steps 4/5/6.

## Where the phone number actually lives

| System | Repo | Model / column | Unique? |
|---|---|---|---|
| workforce (frodo) | `workforce-management-backend` | `access_management.User.phone_number` | yes |
| valinor | `valar` (django project `UserManagement`) | `auth_user.username` **and** `core.EmployeeProfile.primary_contact` | both unique |
| saruman | `saruman` | `auth_user.username` (`OperationUser` has no phone column) | yes |

Linkage: workforce `User.valinor_id` → valinor `core.Employee.id`;
workforce `User.saruman_id` → saruman `auth_user.id` (and
`OperationUser.valinor_employee_id` → valinor `Employee.id`).

The three DBs are **not** kept in sync by a phone edit — `User.save()` in
workforce fires no sync signal — which is why all three are updated separately.

## Files

| # | Script | Shell to run it in | In | Out |
|---|---|---|---|---|
| 1 | `01_workforce_check.py` | workforce | `/tmp/phone_input.csv` | `/tmp/phone_step1_wfm_ok.csv`, `/tmp/phone_step1_wfm_taken.csv` |
| 2 | `02_valinor_check.py` | valar | step 1 ok file | `/tmp/phone_step2_valinor.csv` |
| 3 | `03_saruman_check.py` | saruman | step 2 file | `/tmp/phone_step3_saruman.csv` |
| 4 | `04_workforce_update.py` | workforce | step 3 file | `/tmp/phone_step4_wfm_result.csv` |
| 5 | `05_valinor_update.py` | valar | step 3 file | `/tmp/phone_step5_valinor_result.csv` |
| 6 | `06_saruman_update.py` | saruman | step 3 file | `/tmp/phone_step6_saruman_result.csv` |

## Input format — `/tmp/phone_input.csv`

```csv
user_id,new_phone_number
SFXPROD33067,9876543210
41013,+91 9876543211
```

- `user_id` is the **workforce** `User.id`; bare (`41013`) or darsa-prefixed
  (`SFXPROD41013` / `SFXSTAG41013`) both work.
- Header aliases accepted: `user_id` / `wfm id` / `id` / `emp_id`, and
  `new_phone_number` / `new contact number` / `correct contact number`.
- Numbers are normalised to bare 10 digits; `+91`, `91`, `0`, spaces and dashes
  are stripped. Every check matches against `NNNNNNNNNN`, `91NNNNNNNNNN` and
  `0NNNNNNNNNN` so a number stored in any of those shapes is still caught.
- Numbers are **written** as bare 10 digits everywhere — the same shape
  `SyncEmployee` / `SyncDcGcUser` push from workforce.

## Running

Copy the whole file and paste it into the shell. Pasting a check script (1–3)
runs it. Pasting an update script (4–6) runs a **dry run**; then type
`run(commit=True)` to write.

```
# workforce
python manage.py shell   → paste 01_workforce_check.py
# valar
python manage.py shell   → paste 02_valinor_check.py
# saruman
python manage.py shell   → paste 03_saruman_check.py
# then, same order
python manage.py shell   → paste 04_workforce_update.py  → run(commit=True)
python manage.py shell   → paste 05_valinor_update.py    → run(commit=True)
python manage.py shell   → paste 06_saruman_update.py    → run(commit=True)
```

Move `/tmp/phone_step*.csv` between machines/pods yourself — the shells are on
different services.

## Key columns

- `valinor_exists` / `saruman_exists` — `TRUE` means the new number is held by
  **someone else** in that system (the user's own record is excluded, so a
  number already correct on their own row does not read as a conflict).
- `eligible` — `TRUE` only when `valinor_exists = FALSE` **and**
  `saruman_exists = FALSE`. Steps 4/5/6 touch only these rows.
- `wfm_already_updated`, `valinor_current_phone`, `saruman_current_phone` — what
  each system holds today, for eyeballing before commit.

Step 1 rejects a number two ways: `ALREADY_USED_IN_WORKFORCE` (another
workforce user holds it, listed with id/name/valinor_id/saruman_id/status) and
`DUPLICATE_IN_INPUT_SHEET` (the same new number requested for two input rows).

## Notes

- Rows with no `valinor_id` / no `saruman_id` still flow through — they are
  checked (the number must be free), and the corresponding update step records
  `SKIPPED / no valinor_id` (or `no saruman_id`) instead of failing.
- Steps 4/5/6 re-run the uniqueness check at write time, so a stale sheet
  reports `CONFLICT` rather than raising an IntegrityError.
- Step 5 saves `auth_user` **before** `EmployeeProfile`: the `EmployeeProfile`
  post_save signal refreshes the valinor redis auth cache, which caches
  `mobile_number` from `auth_user.username`.
- Step 6 leaves `is_active` alone, so saruman's
  `notify_workforce_on_user_deactivated` post_save receiver stays inert.
