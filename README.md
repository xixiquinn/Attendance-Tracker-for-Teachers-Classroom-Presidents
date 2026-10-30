# Attendance Tracker for Teachers & Classroom Presidents

A mobile-friendly web app for taking attendance and tracking student activities, built for
BSIT 1-B. Each teacher or class president logs in with their own username and password and
gets a private set of blocks (Block A to E by default). Data is stored in Google Firebase
(Firestore), so it is the same on every phone and computer.

Live site: https://attendance-tracker-for-teachers-cla.vercel.app

Made by Quinn.

## Features

- **Login page**: every person logs in with their own username and password and stays signed in for 30 days (Log out button at the top). Nobody sees anyone else's data.
- **Blocks**: Block A to E to start with. Add, rename or delete blocks. Each block has its own students, attendance and activities.
- **Students**: add one by one, search, remove, or import from a spreadsheet.
- **Take attendance**: mark Present, Absent, Late or Excused for any date.
- **Daily view and summary**: see a whole day at once, or one student's totals and attendance percentage.
- **Activities**: list activities (quiz, project, event...) per block and tick which students are done. Shows progress for each activity.
- **Excel export**: download one block or all blocks. Attendance and activities go in the same file (activities on a second sheet).
- **Excel import**: load names and attendance into a block from one spreadsheet.
- **Phone friendly**: add it to your home screen and it opens like an app. Dates follow Philippine time.

## Using it

1. Log in, then pick a block from the dropdown at the top.
2. **Students** tab: add or import your class list.
3. **Take** tab: choose a date, tap P, A, L or E for each student, then Save attendance.
4. **Activities** tab: type an activity name and date, press Add, then tap each student who is done (or Mark all done).
5. **Students** tab: Download this block, or Download all blocks, to get the Excel file.

### Spreadsheet format for importing

| ID | Name | 2026-10-13 | 2026-10-14 |
|---|---|---|---|
| 1 | Dela Cruz, Juan | P | L |
| 2 | Santos, Maria | A | E |

`ID` and `Name` are required. Date columns are optional and use `P`, `A`, `L`, `E` (or Present,
Absent, Late, Excused). The file you get from "Download this block" can be edited and imported back.

## Run it on your computer

1. Create a Firebase project and a Firestore database, then download a service-account key
   (Project settings > Service accounts > Generate new private key).
2. Save the key as `serviceAccountKey.json` in this folder (it is git-ignored; never upload it).
3. Install and start:

```
pip install -r requirements.txt
set USERS=juan:Pass1word,maria:Another2Pass      (Mac/Linux: export USERS=...)
set PORT=5000
python app.py
```

Open http://localhost:5000 and log in. Port 8080 can clash with other programs (Steam, for example), so 5000 is safer.

## Settings (environment variables)

| Name | What it does |
|---|---|
| `USERS` | Logins as `username:password` pairs separated by commas. Usernames: letters, numbers, `.`, `_`, `-`. Passwords cannot contain `,` or `:`. |
| `FIREBASE_CREDENTIALS` | The full text of your service-account key JSON (use this on a host instead of the key file). |
| `SECRET_KEY` | Optional. Signs the login cookie. If you leave it out, one is made from your other settings, so it works on Vercel with no extra setup. |
| `APP_PASSWORD` | Optional single shared password, only used when `USERS` is not set. |
| `PORT` | Port to listen on (hosts usually set this for you). |

If neither `USERS` nor `APP_PASSWORD` is set, the app has no login. Only use that on your own computer.

### How login works

- The login page checks the username and password against `USERS` and sets a signed, HTTP-only cookie.
- Changing someone's password in `USERS`, or removing them, signs that person out straight away.
- Wrong passwords are slowed down, but there is no lockout. Use long passwords.
- Adding or changing users: edit `USERS` in your host's settings and redeploy.

## Deploying

The included `Dockerfile` works on any Docker host such as Render. Add the environment variables
above in your host's settings (`USERS` and `FIREBASE_CREDENTIALS` at minimum). If you host
somewhere else, such as Vercel, add the same variables in that project's settings.

## Project layout

```
app.py              Flask server: logins, blocks, data, import and export
export_xlsx.py      builds the Excel files
import_xlsx.py      reads names and attendance from a spreadsheet
static/             index.html (the app), login.html (the login page), manifest and app icons
tests/test_app.py   automated tests (run: python tests/test_app.py)
Dockerfile          for Docker hosts
```

## Data layout in Firestore

```
users/{username}/blocks/{block}                    name
users/{username}/blocks/{block}/students/{id}      name
users/{username}/blocks/{block}/attendance/{date}  studentId -> P / A / L / E
users/{username}/blocks/{block}/activities/{id}    title, date, done: [studentId...]
```

## Tests

```
python tests/test_app.py
```

The same tests run automatically on GitHub for every push (see `.github/workflows/tests.yml`).
